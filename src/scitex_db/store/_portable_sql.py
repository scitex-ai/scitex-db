#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Spellings that survive both dialects. Not a query builder.

**There is no single spelling that works on both**, and that is the whole
reason this module exists rather than a constants file. Measured by
scitex-cards on their deployment, 2026-08-02
(``src/scitex_cards/_sql_null_safe.py``)::

    backend                col IS ?      col IS NOT DISTINCT FROM ?
    SQLite 3.37.2          WORKS         SYNTAX ERROR (needs >= 3.39)
    PostgreSQL             SYNTAX ERROR  WORKS

``IS NOT DISTINCT FROM`` is the standard-SQL spelling; SQLite learned it
only in 3.39 (2022-06). So neither literal is portable, and a constant
plus a version gate — which is what this package's own surface document
originally specified — cannot express it. The spelling has to be chosen
where the dialect is known.

That mismatch cost a **36-hour silent delivery outage** on their fleet:
every enqueue raised, a fail-soft ``except`` swallowed it, and it was
invisible in CI and in every container because the containers ran SQLite
3.45.1 while the host ran 3.37.2. Work was performed; evidence was not.

Paramstyle is the other half. SQLite writes ``?`` and PostgreSQL writes
``%s``, and the naive rewrite is worse than no rewrite:

* a ``?`` INSIDE A STRING LITERAL is not a placeholder. Card and message
  bodies routinely contain question marks, so ``sql.replace("?", "%s")``
  silently corrupts data rather than raising.
* a literal ``%`` must be doubled, or a ``LIKE '%foo%'`` pattern becomes
  a format specifier and raises at execution time.

One is a correctness hazard and the other a crash hazard, from the same
one-line shortcut.

stdlib only, by contract — see ``docs/portable-store-seam-surface.md``.
"""

from __future__ import annotations

from ._url import POSTGRESQL, SQLITE

__all__ = [
    "MIN_SQLITE_VERSION_FOR_IS_NOT_DISTINCT_FROM",
    "POSTGRESQL_NULL_SAFE",
    "SQLITE_NULL_SAFE",
    "SQLITE_ONLY_UPSERT_FORMS",
    "null_safe_eq",
    "to_paramstyle",
]

#: Standard SQL. PostgreSQL always; SQLite only from this version.
POSTGRESQL_NULL_SAFE = "IS NOT DISTINCT FROM"

#: SQLite's null-safe ``IS``. Does NOT parse on PostgreSQL.
SQLITE_NULL_SAFE = "IS"

#: SQLite gained ``IS NOT DISTINCT FROM`` in 3.39 (2022-06). Recorded as a
#: constant so a test can assert against it rather than against whatever
#: SQLite the developer happens to run — the version spread between host
#: (3.37.2) and container (3.45.1) is exactly what hid the outage.
MIN_SQLITE_VERSION_FOR_IS_NOT_DISTINCT_FROM = (3, 39, 0)

#: Upsert spellings that parse ONLY on SQLite. The portable form is
#: ``ON CONFLICT (...) DO NOTHING`` / ``DO UPDATE SET x = excluded.x``,
#: which parses on both. Recorded for callers and reviewers; this module
#: does not build queries.
SQLITE_ONLY_UPSERT_FORMS = (
    "INSERT OR IGNORE",
    "INSERT OR REPLACE",
)


def null_safe_eq(column: str, *, dialect: str) -> str:
    """``<column> <null-safe op> ?`` spelled for ``dialect``.

    Always emits a ``?`` placeholder; run the result through
    :func:`to_paramstyle` so callers keep one paramstyle.

    There is deliberately no default dialect. A default here would pick a
    spelling that raises a syntax error on the other engine, which is the
    36-hour outage restated as an API.
    """
    if dialect == SQLITE:
        operator = SQLITE_NULL_SAFE
    elif dialect == POSTGRESQL:
        operator = POSTGRESQL_NULL_SAFE
    else:
        raise ValueError(
            f"unknown dialect {dialect!r}; expected {SQLITE!r} or "
            f"{POSTGRESQL!r}. Refusing to guess: the two spellings are "
            "syntax errors on each other's engine."
        )
    return f"{column} {operator} ?"


def to_paramstyle(sql: str, *, dialect: str) -> str:
    """Rewrite SQLite ``?`` placeholders for ``dialect``.

    SQLite is returned unchanged, so the common path costs nothing and
    cannot corrupt. For PostgreSQL, ``?`` becomes ``%s`` and a literal
    ``%`` is doubled -- but only OUTSIDE single-quoted string literals,
    which are scanned and skipped, including SQL's doubled-quote escape
    (``'it''s'``).
    """
    if dialect == SQLITE:
        return sql
    if dialect != POSTGRESQL:
        raise ValueError(
            f"unknown dialect {dialect!r}; expected {SQLITE!r} or "
            f"{POSTGRESQL!r}"
        )

    out: list[str] = []
    in_literal = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if in_literal:
            if char == "'":
                # A doubled quote is an escaped quote, not the end of the
                # literal: consume both and stay inside.
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    out.append("''")
                    index += 2
                    continue
                in_literal = False
            out.append("%%" if char == "%" else char)
        elif char == "'":
            in_literal = True
            out.append(char)
        elif char == "?":
            out.append("%s")
        elif char == "%":
            out.append("%%")
        else:
            out.append(char)
        index += 1
    return "".join(out)


# EOF
