#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Declared value transformations applied AT THE MIGRATION BOUNDARY.

WHY THIS EXISTS AT ALL, because everything else in this package refuses to alter
a stored value and that refusal is deliberate.

A NUL byte is LEGAL in SQLite TEXT and ILLEGAL in PostgreSQL TEXT. That is a
representational difference between two backends, not corruption in the source.
For most rows the right answer is still refusal -- fix the data, then migrate.
But scitex-cards' `dm_messages` is append-only by design: a `BEFORE UPDATE`
trigger makes message bodies immutable and a `BEFORE DELETE` trigger makes rows
undeletable, so a NUL that lands there cannot be corrected by anyone, including
its owner. Measured 2026-07-30 on row `m_c7f4214deb15`.

That leaves exactly two exits, and one of them is not an exit:

* mutate the immutable row -- destroys the append-only invariant that this
  migration exists to carry across. Weakening the guarantee in order to move it
  is not moving it.
* transform at the boundary, with a manifest -- source untouched, invariant
  intact, and the destination differs from the source only in ways that were
  declared in advance and recorded afterwards.

So this is not a general "fix the data" facility and must never become one. It
is a named, enumerated exception with six properties, each of which exists
because its absence would turn this into the thing it is not allowed to be:

1. DECLARED BEFORE THE RUN. The affected rows are enumerated by
   :func:`plan_nul_escapes` and frozen before the first write. A NUL met during
   the copy in a row that was NOT declared raises, so drift cannot silently
   widen the exception.
2. CONSTRUCTED, NOT FLAGGED. There is no ``escape_nul=True``. A caller must
   build a :class:`Transformations` from what the preflight found, so nobody can
   enable this without having looked at what it will change.
3. VERIFICATION PROVES IT, rather than skipping the row. The comparison becomes
   ``destination == rule(source)`` -- never "do not compare this one". Skipping
   would put a hole in the last gate before the completion marker.
4. REVERSIBILITY LIVES IN THE MANIFEST, NOT IN THE RULE. The rule is NOT
   invertible and is not treated as such: scitex-cards measured a body that
   already contained the escape notation as ordinary prose, so un-escaping would
   produce three NULs where the original had one. The manifest therefore records
   the original bytes as HEX -- hex and not text, because a manifest holding the
   original as text would carry the NUL and re-block the destination, which is
   the same trap one level in.
5. ALWAYS PRINTED, including on success, next to the exclusions.
6. THE DEFAULT IS STILL REFUSAL. No ``Transformations`` means a NUL column is a
   blocker, exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "NUL",
    "NUL_REPLACEMENT",
    "NulEscape",
    "TransformationError",
    "Transformations",
    "escape_nuls",
    "plan_nul_escapes",
]

#: The byte itself, spelled as a code point rather than written literally.
#: Writing it as a quoted literal puts a real NUL in this file, git classifies
#: the source as binary, and the module about the byte becomes an instance of
#: the problem. scitex-cards hit exactly that in the first draft of their own
#: guard on 2026-07-30.
NUL = chr(0)

#: U+2400 SYMBOL FOR NULL. Chosen to match scitex-cards' write-time guard, so a
#: row transformed at the boundary and a row sanitised at write time look the
#: same in the destination rather than differing by provenance.
#:
#: A printable ASCII escape would have been worse for a reason worth stating: a
#: marker a human can type by accident is indistinguishable from content that
#: happens to contain it.
NUL_REPLACEMENT = "␀"


class TransformationError(Exception):
    """Raised when a transformation is undeclared, or does not apply."""


def escape_nuls(value: Any) -> Any:
    """Replace every NUL in ``value`` with :data:`NUL_REPLACEMENT`.

    Non-text values pass through untouched: a BLOB may legitimately contain
    0x00 and migrates to ``BYTEA``, which accepts it.
    """
    if not isinstance(value, str):
        return value
    return value.replace(NUL, NUL_REPLACEMENT)


@dataclass(frozen=True)
class NulEscape:
    """One declared escape: which row, which column, and what was there.

    ``key`` is the row's primary-key values in key order, so the declaration
    names a ROW rather than a count. A declaration that said only "two rows in
    messages.body" could not detect that the two rows it meets during the copy
    are different from the two it was built from.
    """

    table: str
    key: tuple[Any, ...]
    column: str
    original_hex: str
    nul_count: int

    def describe(self) -> str:
        return (
            f"{self.table}.{self.column} {self.key}: {self.nul_count} NUL "
            f"byte(s) -> {NUL_REPLACEMENT!r} (original {len(self.original_hex) // 2} "
            f"bytes recorded as hex)"
        )


@dataclass(frozen=True)
class Transformations:
    """The complete, frozen set of value changes this migration is allowed.

    ``stated_by`` is required for the same reason :class:`._copy.Quiescence`
    requires it: this is a claim the migration cannot check for itself, so the
    marker records who made it.
    """

    escapes: tuple[NulEscape, ...]
    stated_by: str

    def __post_init__(self) -> None:
        if not self.stated_by.strip():
            raise TransformationError(
                "transformations declared by nobody. Altering a stored value is "
                "the one thing this tool will not do on its own, so the marker "
                "records who authorised it."
            )

    def applies_to(self, table: str, key: tuple[Any, ...], column: str) -> bool:
        return any(
            e.table == table and e.key == key and e.column == column
            for e in self.escapes
        )

    def columns_for(self, table: str) -> frozenset[str]:
        return frozenset(e.column for e in self.escapes if e.table == table)

    def apply(
        self, table: str, key: tuple[Any, ...], column: str, value: Any
    ) -> Any:
        """Transform ``value`` if declared; RAISE if it needs one and has none.

        The raise is the point. A NUL met in a row nobody declared means the
        source changed between the declaration and the copy, and continuing
        would silently widen an exception that was supposed to be enumerable.
        """
        if not isinstance(value, str) or NUL not in value:
            return value
        if not self.applies_to(table, key, column):
            raise TransformationError(
                f"{table}.{column} {key}: contains a NUL byte but no "
                f"transformation was declared for this row. The declared set is "
                f"frozen before the run, so this means the source changed after "
                f"the preflight -- re-run the preflight rather than widening the "
                f"exception mid-copy."
            )
        return escape_nuls(value)

    def manifest(self) -> list[dict[str, Any]]:
        """The record written into the completion marker."""
        return [
            {
                "table": e.table,
                "key": list(e.key),
                "column": e.column,
                "rule": "nul->U+2400",
                "original_hex": e.original_hex,
                "nul_count": e.nul_count,
            }
            for e in self.escapes
        ]

    def summary(self) -> str:
        if not self.escapes:
            return "transformations: none declared"
        lines = [
            f"transformations: {len(self.escapes)} value(s) escaped at the "
            f"boundary, declared by {self.stated_by}"
        ]
        lines.extend(f"  {e.describe()}" for e in self.escapes)
        return "\n".join(lines)


def plan_nul_escapes(
    source_path: str,
    dispositions: Mapping[str, Any] | None = None,
    *,
    stated_by: str,
) -> Transformations:
    """Enumerate EVERY NUL-bearing value in the source, as a frozen declaration.

    Every one, not a sample: this is the set the copy is permitted to change, so
    a capped list would leave the uncapped remainder to raise mid-run. The
    preflight's own reporting is sampled because it is for a human to read; this
    is for the machine to be bound by, and the two have different needs.

    Opens the source READ-ONLY. Building the declaration cannot alter anything.
    """
    from ._ddl import sqlite_affinity
    from ._introspect import connect_readonly, primary_key_columns, read_columns
    from ._plan import CARDS_STORE_DISPOSITIONS, build_plan, tables_to_migrate
    from ._introspect import list_tables

    if dispositions is None:
        dispositions = CARDS_STORE_DISPOSITIONS

    conn = connect_readonly(source_path)
    try:
        plan = build_plan(list_tables(conn), dispositions)
        found: list[NulEscape] = []
        for table in tables_to_migrate(plan):
            columns = read_columns(conn, table)
            keys = primary_key_columns(columns)
            if not keys:
                # A keyless table is already blocked by the preflight for a
                # different reason. Declaring escapes without a key would name
                # rows it cannot identify.
                continue
            for col in columns:
                if sqlite_affinity(col.declared_type) not in ("TEXT", "NUMERIC"):
                    continue
                selected = ", ".join(f'"{k}"' for k in keys)
                rows = conn.execute(
                    f'SELECT {selected}, "{col.name}" AS v FROM "{table}" '
                    f'WHERE instr("{col.name}", char(0)) > 0'
                ).fetchall()
                for row in rows:
                    value = row["v"]
                    found.append(
                        NulEscape(
                            table=table,
                            key=tuple(row[k] for k in keys),
                            column=col.name,
                            original_hex=value.encode("utf-8").hex(),
                            nul_count=value.count(NUL),
                        )
                    )
        return Transformations(escapes=tuple(found), stated_by=stated_by)
    finally:
        conn.close()


# EOF
