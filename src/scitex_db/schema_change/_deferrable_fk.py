#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add a DEFERRABLE INITIALLY DEFERRED foreign key, re-checking orphans inside
the same transaction that adds it.

WHY THIS IS NOT "run the preflight, then run the DDL". scitex-cards' point, and
it is the reason this module exists rather than a two-line script:

    Orphans are a property of the data AT EXECUTION, not at measurement.

The card store is written continuously by ~90 containers -- measured 3608 tasks
at one point tonight and 3619 twenty minutes later. A preflight that reports
"0 orphans" is a statement about the instant it ran. If, between that instant
and the ALTER, one comment arrives whose parent is deleted, the validating ADD
CONSTRAINT aborts. A precondition verified OUTSIDE the transaction that depends
on it is a precondition that can expire.

So the check and the DDL share one transaction and one snapshot. Either the
store had no orphans at the moment the constraint was added, or nothing was
added.

WHY DEFERRABLE INITIALLY DEFERRED. Two independent reasons, and the second was
not mine:

1. Under directed replay a foreign key is an ORDERING constraint: a child
   arriving before its parent must not fail.
2. LIVE TODAY -- ``_db_mirror`` upserts per changed card, so a comment whose
   parent card is in the same batch depends on statement order inside one
   transaction. Deferring the check to COMMIT removes an ordering assumption
   nobody wrote down.

Deferring does NOT weaken the constraint. A genuinely missing parent is still
refused, just at COMMIT rather than at statement time -- verified 4/4 with a
control, including the case that matters: an out-of-order insert is ACCEPTED, a
non-deferrable twin REFUSES the identical insert, and a genuinely absent parent
is REFUSED either way.

MEASURED COST, on a scratch copy of the real data (3619 tasks, 8069 comments):

    ADD CONSTRAINT ... NOT VALID          0.0065s lock held
    ADD CONSTRAINT (validating, naive)    0.0239s lock held

24ms, so the NOT VALID / VALIDATE split is not worth its extra statement and
extra state at this size. That figure comes from TEMP tables, which are unlogged
and uncontended -- the order of magnitude is what it supports, not the digits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class OrphansFound(Exception):
    """Raised INSIDE the transaction, so the constraint is never added.

    An exported type rather than a message, so a caller distinguishes "the data
    was not ready" from any other failure without matching on text.
    """

    child_table: str
    parent_table: str
    count: int

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"{self.count} row(s) in {self.child_table} reference a missing "
            f"{self.parent_table}. The constraint was NOT added and the "
            f"transaction was rolled back. This is a data condition, not a "
            f"schema one: find the orphans before retrying."
        )


def add_deferrable_fk(
    conn: Any,
    *,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
    constraint_name: str,
    execute: Callable[[Any, str], None] | None = None,
    count_orphans: Callable[[Any, str], int] | None = None,
) -> int:
    """Add the constraint, or raise and leave the store untouched.

    Returns the orphan count observed inside the transaction (0 on success), so
    a caller has the number that was actually acted on rather than one measured
    earlier.

    Raises
    ------
    OrphansFound
        Orphans existed at execution time. Nothing was added.

    Notes
    -----
    The caller supplies ``execute`` and ``count_orphans`` so this module stays
    driver-agnostic and testable without a live server. The DEFAULT path issues
    plain SQL through the connection.

    IDEMPOTENCY IS THE CALLER'S: this does not check whether the constraint
    already exists, because ``ADD CONSTRAINT`` on a duplicate name fails loudly
    and that is the right outcome for a migration that should run once. Probe
    with :mod:`scitex_db.schema_change` first if you need to know.
    """
    _execute = execute or (lambda c, sql: c.execute(sql))
    _count = count_orphans or _default_count_orphans

    orphan_sql = (
        f"SELECT count(*) FROM {child_table} c "
        f"LEFT JOIN {parent_table} p ON p.{parent_column} = c.{child_column} "
        f"WHERE c.{child_column} IS NOT NULL AND p.{parent_column} IS NULL"
    )
    add_sql = (
        f"ALTER TABLE {child_table} ADD CONSTRAINT {constraint_name} "
        f"FOREIGN KEY ({child_column}) REFERENCES {parent_table}({parent_column}) "
        f"DEFERRABLE INITIALLY DEFERRED"
    )

    _execute(conn, "BEGIN")
    try:
        orphans = _count(conn, orphan_sql)
        if orphans:
            # Raise INSIDE the transaction. The rollback in `finally` is what
            # guarantees the constraint is not added -- returning a value here
            # would let a caller ignore it and proceed.
            raise OrphansFound(
                child_table=child_table, parent_table=parent_table, count=orphans
            )
        _execute(conn, add_sql)
    except BaseException:
        _execute(conn, "ROLLBACK")
        raise
    _execute(conn, "COMMIT")
    return 0


def _default_count_orphans(conn: Any, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0])
