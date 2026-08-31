#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What shape is this foreign key in, right now, on THIS store?

WHY A THREE-STATE PROBE RATHER THAN try-ADD-and-swallow-the-error. The card
store exists in two divergent shapes and a migration must serve both:

    LIVE store (measured 2026-08-10)   constraint ABSENT
    FRESH store (built from _SCHEMA_SQL) constraint PRESENT, NOT deferrable

scitex-cards' schema declares four foreign keys; three of them are missing from
the live database. So the same logical task -- "task_comments.task_id should be
a deferrable FK to tasks.id" -- is an ADD on one store and an ALTER on the
other, and a no-op on a store already fixed.

My own card described this work first as "make them deferrable", then I
"corrected" it to "add them" after measuring the live store and told the owner
the first framing was wrong. IT WAS RIGHT FOR FRESH STORES. Both framings were
true of different stores, and I collapsed a divergence into an error. This
module exists so the code cannot repeat that mistake: it asks which shape it is
looking at instead of assuming one.

THE NAME COLLISION IS LOAD-BEARING AND WAS NEARLY A BUG. PostgreSQL auto-names
an inline ``REFERENCES`` constraint ``<table>_<column>_fkey``. That is exactly
the name a caller would choose by convention -- ``task_comments_task_id_fkey``
-- so on a fresh store an ADD does not merely duplicate the constraint, it
collides on the identical name and fails. That failure would land on precisely
the stores that are ALREADY CORRECT, which is the worst direction to fail in.

Turned into an asset: because the names coincide, detection needs no heuristic.
Same name, same table, same column, so "already present" is a fact rather than
an inference.

POSTGRESQL ONLY, BY CONSTRUCTION RATHER THAN BY OMISSION. ``SHAPE_SQL`` reads
``pg_constraint``, so this module cannot observe a SQLite store. That is the
correct shape, not a missing backend, and two measurements say so (2026-08-11,
reproduced independently by scitex-cards):

    ALTER TABLE child ADD CONSTRAINT fk FOREIGN KEY (pid) REFERENCES parent(id)
    -> OperationalError: near "CONSTRAINT": syntax error
    ALTER TABLE child ADD COLUMN note TEXT          -> ACCEPTED  (control)

SQLite has no ADD CONSTRAINT at all -- not merely no deferrable variant. The
control matters: ALTER TABLE itself works, so the refusal is specific to adding
a constraint. Changing one there means rebuilding the table and copying every
row. An observer for an ALTER that can never run would be an instrument with
nothing to instrument.

And SQLite could not answer the question anyway. ``PRAGMA foreign_key_list``
returns BYTE-IDENTICAL rows for a deferrable and a non-deferrable FK -- its
columns are id/seq/table/from/to/on_update/on_delete/match, with no
deferrability field. The only record of deferrability is ``sqlite_master.sql``,
the DDL TEXT, which differs by BUILD PATH: ``executescript`` stores comments
verbatim while a stripping DDL helper does not, so the same logical schema
yields two different recorded texts. A probe reading that text would report a
shape that depends on how the store was created.

So the two populations are covered by two different mechanisms and neither one
is this module's ALTER:

    fresh SQLite stores   the DECLARATION (scitex-cards #796, merged
                          2026-08-11T06:39:04Z). Born deferrable; nothing to
                          reconcile, ever.
    live PostgreSQL       this module. ``pg_constraint.condeferrable`` is a
                          structured column, so the shape is observable and the
                          constraint is ALTERable.

Passing a SQLite connection here raises rather than returning ABSENT. That is
deliberate: ABSENT is a claim about a store that was successfully inspected,
and a store this module cannot inspect must not be described in the same
vocabulary as one it can.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Callable


class FKShape(enum.Enum):
    """The three states a target foreign key can be in.

    Deliberately not a bool and not None-able. "Absent" and "present but not
    deferrable" require DIFFERENT statements, and collapsing them into
    "needs work" is what makes a migration fail on half its stores.
    """

    ABSENT = "absent"
    PRESENT_NOT_DEFERRABLE = "present_not_deferrable"
    PRESENT_DEFERRABLE = "present_deferrable"


@dataclass(frozen=True)
class FKObservation:
    """What was seen, and under which name.

    ``name`` is recorded even when the shape is ABSENT, because the name a
    caller INTENDED to use is what a later run will look for, and a mismatch
    between intended and actual names is how a "no-op" run silently adds a
    second constraint alongside the first.
    """

    shape: FKShape
    name: str
    table: str
    column: str

    def summary(self) -> str:
        return f"{self.table}.{self.column} -> {self.shape.value} (as {self.name!r})"


#: Reads pg_constraint for a FK on (table, column), returning
#: (exists, condeferrable). Kept as SQL here so a caller can see exactly what is
#: being asked rather than trusting a helper's name.
SHAPE_SQL = """
SELECT c.conname, c.condeferrable
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY (c.conkey)
WHERE c.contype = 'f'
  AND t.relname = '{table}'
  AND a.attname = '{column}'
"""


def observe_fk(
    conn: Any,
    *,
    table: str,
    column: str,
    intended_name: str,
    fetch_one: Callable[[Any, str], tuple | None] | None = None,
) -> FKObservation:
    """Report the shape of the FK on ``table.column``, if any.

    POSTGRESQL ONLY. ``conn`` must be a PostgreSQL connection: the query reads
    ``pg_constraint``, and a SQLite connection RAISES rather than returning
    ABSENT. SQLite is out of scope by construction -- it has no ADD CONSTRAINT,
    and its catalogue does not record deferrability at all. See the module
    docstring for the measurements; do not "fix" this by adding a SQLite
    backend, because the operation it would inform cannot exist there.

    Matches on TABLE AND COLUMN, not on constraint name. A store that has the
    constraint under PostgreSQL's auto-generated name and a caller that expects
    its own name are the same situation, and matching on name would report
    ABSENT for a constraint that is plainly there -- then add a duplicate.

    The name actually found is returned, so a caller can see when it differs
    from what it intended.
    """
    _fetch = fetch_one or _default_fetch_one
    row = _fetch(conn, SHAPE_SQL.format(table=table, column=column))
    if row is None:
        return FKObservation(
            shape=FKShape.ABSENT, name=intended_name, table=table, column=column
        )
    found_name, deferrable = row[0], bool(row[1])
    shape = FKShape.PRESENT_DEFERRABLE if deferrable else FKShape.PRESENT_NOT_DEFERRABLE
    return FKObservation(shape=shape, name=found_name, table=table, column=column)


def _default_fetch_one(conn: Any, sql: str) -> tuple | None:
    return conn.execute(sql).fetchone()
