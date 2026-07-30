#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read a SQLite store's shape: which tables, which columns, what is stored.

Everything here is SOURCE-SIDE and depends on nothing but a readable SQLite
file, which is why it can be built before the destination side is settled.

TWO THINGS THIS MODULE REFUSES TO GUESS.

Internal tables. ``sqlite_master`` lists ``sqlite_sequence``,
``sqlite_stat1`` and friends alongside real tables. Those are engine
bookkeeping, not store content, and copying them to PostgreSQL would be both
meaningless and impossible. They are filtered by prefix -- but the filter lives
here, once, rather than in every caller, because a caller that forgot it would
hand the plan a table it has no disposition for and get a confusing refusal
instead of a clean list.

Row ORDER. :func:`read_rows` always applies an explicit ``ORDER BY`` over the
table's key columns. SQLite will happily return rows in whatever order the
b-tree yields, PostgreSQL likewise, and neither guarantees stability across
runs. The verification pairs rows by key so it does not care -- but a batched
copy does: ``LIMIT/OFFSET`` paging over an unordered query can return the same
row twice and skip another, which produces a destination with the right row
COUNT and the wrong rows. That failure survives a count check and is caught only
by the checksum comparison, so it is worth not creating in the first place.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterator, Sequence

from ._ddl import Column

__all__ = [
    "IntrospectionError",
    "columns_with_nul",
    "connect_readonly",
    "list_tables",
    "primary_key_columns",
    "read_columns",
    "read_rows",
    "stored_types",
]

#: Prefix marking SQLite's own bookkeeping tables.
_INTERNAL_PREFIX = "sqlite_"


class IntrospectionError(Exception):
    """Raised when the source database cannot be described."""


def connect_readonly(path: str) -> sqlite3.Connection:
    """Open ``path`` READ-ONLY, with rows as mappings.

    Read-only is not caution for its own sake: the source of a migration is a
    live store, and this package has no business being able to write to it. A
    read-only URI turns an accidental write into an immediate error rather than
    a modification of the thing being copied.

    ``row_factory`` is set to :class:`sqlite3.Row` so callers get name access,
    which is what :mod:`._verify` needs -- it compares by column name, and a
    positional tuple would silently reorder if the SELECT ever changed.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    """The store's own tables, sorted, excluding SQLite internals and views.

    Views are excluded because a view is derived data -- copying it would
    duplicate rows that the base tables already carry, and the verification
    would then compare a projection against a projection while the underlying
    disagreement went unnoticed.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return tuple(
        r["name"] for r in rows if not str(r["name"]).startswith(_INTERNAL_PREFIX)
    )


def read_columns(conn: sqlite3.Connection, table: str) -> tuple[Column, ...]:
    """Columns of ``table`` in declaration order, as :class:`._ddl.Column`.

    Raises :class:`IntrospectionError` for an unknown table. ``PRAGMA
    table_info`` returns an EMPTY result for a table that does not exist rather
    than failing, so without this check a typo would look like a table with no
    columns -- and the DDL translator would then report "no columns", which is
    true but names the wrong problem.
    """
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise IntrospectionError(
            f"{table!r}: no such table in this database (PRAGMA table_info "
            f"returns an empty result for a missing table rather than "
            f"failing, so this is a missing table and not a table without "
            f"columns)."
        )
    return tuple(
        Column(
            name=r["name"],
            declared_type=r["type"] or "",
            not_null=bool(r["notnull"]),
            primary_key=bool(r["pk"]),
        )
        for r in rows
    )


def primary_key_columns(columns: Sequence[Column]) -> tuple[str, ...]:
    """The primary-key column names, or ``()`` if the table has none.

    Returned rather than raised on absence, because the caller is better placed
    to decide: :mod:`._verify` needs SOME unique key to pair rows, and for a
    table without a declared primary key that key has to be chosen explicitly
    rather than invented here. Silently falling back to "all columns" would
    make two identical rows collide and produce a duplicate-key refusal whose
    message pointed at the wrong thing.
    """
    return tuple(c.name for c in columns if c.primary_key)


def stored_types(
    conn: sqlite3.Connection, table: str, columns: Sequence[Column]
) -> dict[str, tuple[str, ...]]:
    """The distinct ``typeof()`` values actually present, per column.

    This is what :func:`._ddl.unstorable_columns` consumes. It is a full scan
    per column by necessity -- SQLite has no index on storage class, and the
    question "does any row in this column hold something PostgreSQL will
    reject?" cannot be answered from metadata, only from the rows.
    """
    result: dict[str, tuple[str, ...]] = {}
    for col in columns:
        rows = conn.execute(
            f'SELECT DISTINCT typeof("{col.name}") AS t FROM "{table}"'
        ).fetchall()
        result[col.name] = tuple(sorted(str(r["t"]) for r in rows))
    return result


def columns_with_nul(
    conn: sqlite3.Connection, table: str, columns: Sequence[Column]
) -> tuple[str, ...]:
    """Text/blob columns holding a NUL (0x00) byte, which PostgreSQL text rejects.

    A genuine cross-backend incompatibility that no amount of SQLite-to-SQLite
    testing surfaces, and that neither the declared type nor ``typeof()`` shows:
    SQLite stores a NUL inside a TEXT value happily and reports the storage
    class as ``text``, so it looks perfectly migratable right up until psycopg2
    raises ``ValueError: A string literal cannot contain NUL (0x00) characters``
    partway through the copy. Found on the live store 2026-07-30 -- two rows in
    ``messages.body`` -- by running the migration against a real PostgreSQL.

    Detected by asking the data (``instr(col, char(0)) > 0``), not the schema,
    for the same reason as :func:`._ddl.unstorable_columns`: the schema cannot
    answer a question about byte content. Reported as a preflight finding rather
    than raised, so every affected column is named in one pass and a human
    decides what to do -- stripping a NUL changes a stored value, which is not a
    call this tool makes silently.

    Only columns with TEXT or NUMERIC affinity are scanned. A BLOB column can
    hold 0x00 legitimately and migrates to ``BYTEA``, which accepts it; INTEGER
    and REAL cannot contain one.
    """
    from ._ddl import sqlite_affinity

    offenders = []
    for col in columns:
        if sqlite_affinity(col.declared_type) not in ("TEXT", "NUMERIC"):
            continue
        found = conn.execute(
            f'SELECT 1 FROM "{table}" WHERE instr("{col.name}", char(0)) > 0 LIMIT 1'
        ).fetchone()
        if found is not None:
            offenders.append(col.name)
    return tuple(offenders)


def read_rows(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    key_columns: Sequence[str],
    *,
    batch_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    """Stream ``table``'s rows as dicts, in a stable key order.

    Batched by keyset rather than ``LIMIT/OFFSET``: OFFSET makes the engine walk
    and discard the rows it skips, so paging a large table costs O(n^2) reads,
    and any concurrent insert shifts every subsequent page. Ordering by the key
    and asking for "the next batch after this key" is stable under insertion and
    linear in the table size.

    Requires ``key_columns`` for exactly that reason -- there is no unordered
    mode, because an unordered batched read can return one row twice and skip
    another, yielding a destination with the correct row count and the wrong
    contents.
    """
    if not key_columns:
        raise IntrospectionError(
            f"{table}: no key columns given. A batched read needs a stable "
            f"order, and neither engine guarantees one without ORDER BY; "
            f"without it a page boundary can duplicate one row and skip "
            f"another, producing a destination with the right row count and "
            f"the wrong rows."
        )
    if batch_size < 1:
        raise IntrospectionError(
            f"{table}: batch_size must be at least 1, got {batch_size}."
        )

    select = ", ".join(f'"{c}"' for c in columns)
    order = ", ".join(f'"{k}"' for k in key_columns)
    keys = ", ".join(f'"{k}"' for k in key_columns)
    placeholders = ", ".join("?" for _ in key_columns)

    last: tuple[Any, ...] | None = None
    while True:
        if last is None:
            sql = f'SELECT {select} FROM "{table}" ORDER BY {order} LIMIT ?'
            params: tuple[Any, ...] = (batch_size,)
        else:
            # Row-value comparison gives a correct multi-column keyset boundary;
            # comparing columns one at a time would either skip or repeat rows
            # that share a leading key component.
            sql = (
                f'SELECT {select} FROM "{table}" '
                f"WHERE ({keys}) > ({placeholders}) "
                f"ORDER BY {order} LIMIT ?"
            )
            params = (*last, batch_size)

        rows = conn.execute(sql, params).fetchall()
        if not rows:
            return
        for row in rows:
            yield dict(row)
        if len(rows) < batch_size:
            return
        final = rows[-1]
        last = tuple(final[k] for k in key_columns)


# EOF
