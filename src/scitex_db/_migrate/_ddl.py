#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translate a SQLite table definition into PostgreSQL DDL.

THE ASYMMETRY THAT MAKES THIS MORE THAN A LOOKUP TABLE. SQLite's declared column
type is an *affinity* -- a hint, not a constraint. A column declared ``INTEGER``
may legally hold the string ``"banana"``. PostgreSQL has no such tolerance: the
INSERT fails. So a translator that maps declared types and copies rows will work
right up until it meets a store where declaration and content disagree, and then
fail deep inside the copy with a driver-level type error naming neither the table
nor the reason.

Measured on the live scitex-cards store, 2026-07-30: **0** columns disagree with
their declaration, and only two declared types are in use at all (88 TEXT, 8
INTEGER). So today's store is well-behaved. That is a fact about today's store,
not a property of SQLite, and it is exactly the kind of fact that quietly becomes
false. :func:`unstorable_columns` therefore checks content against declaration
BEFORE any rows move, so the failure arrives during planning with a column name
attached rather than mid-copy.

It also means the mismatch path cannot be tested against the live store, since
the live store has no mismatches. Its tests build a deliberately mixed-type
SQLite table instead -- a real one, since making a column hold the wrong type is
a single INSERT in SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "Column",
    "DDLTranslationError",
    "create_table_ddl",
    "postgres_type_for",
    "quote_identifier",
    "sqlite_affinity",
    "unstorable_columns",
]


class DDLTranslationError(Exception):
    """Raised when a SQLite definition cannot be faithfully expressed."""


@dataclass(frozen=True)
class Column:
    """One column as SQLite reports it via ``PRAGMA table_info``.

    ``default_expr`` is PRAGMA's ``dflt_value`` VERBATIM, and ``None`` means the
    column genuinely has no default -- not "we did not look". It used not to be
    read at all, which is how four ``DEFAULT``s were dropped from the card store
    without anyone being told: information discarded at introspection cannot be
    reported by anything downstream, however careful the translator is.

    ``rowid_alias`` marks the one column SQLite auto-assigns: an
    ``INTEGER PRIMARY KEY`` is an alias for the rowid, so the application never
    supplies it. PostgreSQL has no such implicit behaviour, so a destination
    that carries the column without an identity is READ-ONLY IN PRACTICE while
    looking perfectly healthy -- which is exactly what happened to
    ``task_comments.id``.
    """

    name: str
    declared_type: str
    not_null: bool = False
    primary_key: bool = False
    default_expr: str | None = None
    rowid_alias: bool = False

    @property
    def default_is_literal(self) -> bool:
        """Whether the default is a constant we can carry without interpreting.

        A literal (``0``, ``'pending'``, ``1.5``, ``TRUE``, ``NULL``) means the
        same thing in both engines, so carrying it invents nothing. Anything
        else -- ``CURRENT_TIMESTAMP``, a function call, an expression -- is
        SQLite dialect whose PostgreSQL spelling is a JUDGEMENT, and a migration
        that guesses at behaviour is worse than one that refuses.
        """
        if self.default_expr is None:
            return False
        expr = self.default_expr.strip()
        if not expr:
            return False
        if expr.upper() in {"NULL", "TRUE", "FALSE"}:
            return True
        if expr.startswith("'") and expr.endswith("'") and len(expr) >= 2:
            return "'" not in expr[1:-1].replace("''", "")
        try:
            float(expr)
        except ValueError:
            return False
        return True


def sqlite_affinity(declared_type: str) -> str:
    """The affinity SQLite assigns to ``declared_type``.

    Implements the five rules from SQLite's "Determination Of Column Affinity"
    in their documented ORDER, which is load-bearing: the rules are applied
    first-match-wins, so ``"INTEGER"`` must be tested for ``INT`` before
    ``"POINT"`` -- which also contains ``INT`` -- is reached by a later rule.
    Reordering them silently changes the answer for real declarations.
    """
    decl = (declared_type or "").upper()
    if "INT" in decl:
        return "INTEGER"
    if any(token in decl for token in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in decl or decl == "":
        return "BLOB"
    if any(token in decl for token in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return "NUMERIC"


def postgres_type_for(declared_type: str) -> str:
    """The PostgreSQL type for a SQLite declaration.

    ``INTEGER`` maps to ``BIGINT``, not ``INTEGER``. SQLite integers are up to
    8 bytes; PostgreSQL ``INTEGER`` is 4. Mapping to ``INTEGER`` would reject
    any value above 2^31 at insert time -- late, and for a reason that reads
    like a data problem rather than a translation choice. ``BIGINT`` costs 4
    bytes per row and removes the class.

    ``REAL`` maps to ``DOUBLE PRECISION`` because SQLite's REAL *is* an 8-byte
    IEEE float; PostgreSQL ``REAL`` is 4-byte, so that name would silently
    round every value it stored.

    ``NUMERIC`` is unconstrained (no precision or scale) so that a value SQLite
    accepted cannot be rejected or rounded on arrival. Pinning a precision here
    would be inventing a constraint the source never had.
    """
    affinity = sqlite_affinity(declared_type)
    return {
        "INTEGER": "BIGINT",
        "TEXT": "TEXT",
        "BLOB": "BYTEA",
        "REAL": "DOUBLE PRECISION",
        "NUMERIC": "NUMERIC",
    }[affinity]


def quote_identifier(name: str) -> str:
    """Double-quote an identifier for PostgreSQL, escaping embedded quotes.

    Not optional politeness. This store already carries a column named ``grp``
    -- evidently renamed because ``group`` is reserved -- which is a reminder
    that the next such column may not get renamed. Quoting every identifier
    means a table or column whose name collides with a PostgreSQL keyword
    migrates without anyone having to notice it did.

    Quoting also preserves case. PostgreSQL folds unquoted identifiers to lower
    case, so an unquoted ``CamelCase`` column would arrive renamed and the
    verification would -- correctly -- call it a mismatch.
    """
    if "\x00" in name:
        raise DDLTranslationError(
            f"identifier {name!r} contains a NUL byte, which PostgreSQL cannot "
            f"represent in an identifier."
        )
    return '"' + name.replace('"', '""') + '"'


def create_table_ddl(table: str, columns: Sequence[Column]) -> str:
    """A ``CREATE TABLE`` statement for PostgreSQL.

    Column order is preserved from the source. It has no semantic weight in
    either engine, but keeping it makes the generated DDL diffable against the
    source schema by eye, which is how a human reviews a translation.

    NOT NULL, PRIMARY KEY, LITERAL defaults and rowid-alias identity are
    carried. CHECK constraints and foreign keys remain out of scope.

    THIS USED TO CARRY NOT NULL AND DROP EVERY DEFAULT, which is a worse
    combination than dropping both. A ``NOT NULL DEFAULT 0`` column arrived as
    bare ``NOT NULL``: the constraint survived without the thing that satisfied
    it, so the destination was STRICTER than the source and every insert that
    omitted the column failed. All four declared defaults in the card store were
    lost that way, and nothing reported it -- the reasoning ("a default
    expression is SQLite dialect") lived in this docstring, where it is read by
    nobody at the moment a write starts failing.

    The reasoning was right about EXPRESSIONS and wrong to extend to literals. A
    literal means the same thing in both engines, so carrying it invents
    nothing; an expression is a judgement and is refused by name in the
    preflight instead, the way `excluded_objects` already refuses triggers.

    A rowid-alias primary key becomes ``GENERATED BY DEFAULT AS IDENTITY``,
    because SQLite auto-assigns it and the application never supplies it.
    Without that the table is read-only in practice while looking healthy.
    """
    if not columns:
        raise DDLTranslationError(
            f"{table}: no columns. A table with no columns cannot be created, "
            f"and an empty column list almost certainly means introspection "
            f"returned nothing rather than that the table is column-free."
        )

    pk = [c.name for c in columns if c.primary_key]
    lines = []
    for col in columns:
        piece = f"    {quote_identifier(col.name)} {postgres_type_for(col.declared_type)}"
        if col.rowid_alias:
            # BY DEFAULT rather than ALWAYS: the copy supplies the source's own
            # ids explicitly, and ALWAYS would refuse them.
            piece += " GENERATED BY DEFAULT AS IDENTITY"
        elif col.default_is_literal:
            piece += f" DEFAULT {col.default_expr.strip()}"
        if col.not_null:
            piece += " NOT NULL"
        lines.append(piece)
    if pk:
        keys = ", ".join(quote_identifier(k) for k in pk)
        lines.append(f"    PRIMARY KEY ({keys})")

    body = ",\n".join(lines)
    return f"CREATE TABLE {quote_identifier(table)} (\n{body}\n)"


#: ``typeof()`` results that a given affinity can accept without PostgreSQL
#: rejecting the value. ``null`` is handled separately -- it is storable in any
#: nullable column and is not a type disagreement.
_ACCEPTED_STORED_TYPES = {
    "INTEGER": {"integer"},
    "TEXT": {"text"},
    "BLOB": {"blob", "text", "integer", "real"},
    "REAL": {"real", "integer"},
    "NUMERIC": {"integer", "real"},
}


def unstorable_columns(
    table: str,
    columns: Sequence[Column],
    stored_types: dict[str, Iterable[str]],
) -> tuple[str, ...]:
    """Columns whose CONTENT will not fit the type they are being migrated to.

    ``stored_types`` maps column name to the distinct ``typeof(col)`` values
    actually present, which the caller gets from
    ``SELECT DISTINCT typeof("col") FROM "table"``. Asking the data rather than
    trusting the declaration is the whole point: SQLite's declaration is a hint
    and PostgreSQL's is a rule, so the only way to know a copy will succeed is
    to look at what is stored.

    Returns the offending column names rather than raising, so a caller can
    report every problem in one pass. A migration that fails on one column at a
    time turns a schema review into N runs.

    ``null`` is not a disagreement: it is storable in any nullable column, and
    treating it as a mismatch would flag most of this store's columns.
    """
    by_name = {c.name: c for c in columns}
    offenders = []
    for name, seen in stored_types.items():
        col = by_name.get(name)
        if col is None:
            raise DDLTranslationError(
                f"{table}: stored types given for column {name!r}, which is "
                f"not in the column list. The introspection and the content "
                f"query disagree about this table's shape, so neither can be "
                f"trusted for it."
            )
        present = {str(s).lower() for s in seen} - {"null"}
        if not present:
            continue
        accepted = _ACCEPTED_STORED_TYPES[sqlite_affinity(col.declared_type)]
        if present - accepted:
            offenders.append(name)
    return tuple(sorted(offenders))


# EOF
