#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run schema DDL statement by statement, and count what actually ran.

Two hazards, and the second one is not the one this module was
originally specified for.

**A batch that runs nothing looks exactly like a batch that worked.**
``executescript`` and friends accept a blob, and a splitter that
produces zero usable statements returns success having submitted
nothing. So :func:`execute_ddl` submits statements ONE AT A TIME and
returns counts. ``executed`` is the artifact; a caller that asserts on
it cannot be fooled by a silent no-op.

**Running DDL you did not need to run is the outage.** Measured by
scitex-cards on the shared fleet store, 2026-08-02
(``cards-pg-proc-deadlock-from-stale-client-ddl-20260802``): their
schema gate compared client and store versions with ``!=``, "a strict
inequality that fails in BOTH directions". A client AHEAD of the store
should run the DDL — that is what migrates the store up. A client
BEHIND it re-ran the entire function DDL **on every connection open**,
taking ``ShareRowExclusiveLock`` on ``pg_proc`` each time while being
"structurally incapable of adding anything the store lacked. It could
not help and could only serialise."

So the guard is a PRECONDITION, not a lock discipline, and
:data:`DDLResult.skipped` is not an optimisation counter — it is the
observable that makes the guard checkable. A run reporting
``skipped == 0`` against a store that is already current IS the defect.

Worth keeping: the two reporters of that outage both blamed contention
with a concurrent writer, because it correlated. That would have sent
the fix into the write path, "where there is nothing to fix". The
antagonist is any stale client OPENING A CONNECTION anywhere in the
fleet.

**Unknown refuses to compare.** ``observed is None`` means the store
cannot be placed on the version ladder at all. ``None < int`` raises
rather than decides, so a naive ``<`` crashes exactly there. Unknown
falls through to running the DDL — the conservative branch.

One portability note that no version check covers:
``CREATE TRIGGER IF NOT EXISTS`` has **no PostgreSQL form**, so a
portable schema script cannot lean on ``IF NOT EXISTS`` for triggers
the way it can for tables.

stdlib only, by contract — see ``docs/portable-store-seam-surface.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = ["DDLResult", "execute_ddl", "should_run_ddl"]


@dataclass(frozen=True)
class DDLResult:
    """How many statements were submitted, ran, and were deliberately not run.

    ``executed + skipped == submitted`` is enforced, so a caller can
    never be handed a result whose arithmetic hides a lost statement.
    """

    submitted: int = 0
    executed: int = 0
    skipped: int = 0

    def __post_init__(self) -> None:
        for name in ("submitted", "executed", "skipped"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int, got {value!r}")
            if value < 0:
                raise ValueError(f"{name} cannot be negative (got {value})")
        if self.executed + self.skipped != self.submitted:
            raise ValueError(
                "executed + skipped must equal submitted "
                f"(got {self.executed} + {self.skipped} != {self.submitted}); "
                "a mismatch means a statement was neither run nor accounted "
                "for, which is the silent-no-op this type exists to expose"
            )


def should_run_ddl(observed: int | None, required: int) -> bool:
    """Whether a client at ``required`` should run DDL against ``observed``.

    ``observed is None`` means UNKNOWN — the store cannot be placed on
    the ladder — and returns ``True``, the conservative branch. It is
    deliberately not compared: ``None < int`` raises rather than
    decides.

    Otherwise the test is ``observed < required``, NOT ``!=``. A store
    already at or ahead of the client needs nothing; re-running DDL
    there cannot add anything and only serialises every connection
    behind a catalogue lock.
    """
    if observed is None:
        return True
    if not isinstance(observed, int) or isinstance(observed, bool):
        raise TypeError(
            f"observed must be an int or None, got {observed!r}"
        )
    if not isinstance(required, int) or isinstance(required, bool):
        raise TypeError(f"required must be an int, got {required!r}")
    return observed < required


def _usable(statements: Iterable[str]) -> list[str]:
    """Statements with something in them, in order."""
    return [s for s in statements if isinstance(s, str) and s.strip()]


def execute_ddl(
    conn: object,
    statements: Sequence[str],
    *,
    run: bool = True,
) -> DDLResult:
    """Execute ``statements`` one at a time and report the counts.

    ``run=False`` submits nothing and reports every statement as
    skipped — the shape a caller uses when :func:`should_run_ddl` says
    the store is already current. It is a real result rather than an
    early ``return None``, so the caller's assertions still have
    something to read.

    Blank and whitespace-only entries are not submitted and are not
    counted; a splitter that produced them was not describing work.
    """
    usable = _usable(statements)
    submitted = len(usable)

    if not run:
        return DDLResult(submitted=submitted, executed=0, skipped=submitted)

    cursor = conn.cursor()
    executed = 0
    try:
        for statement in usable:
            cursor.execute(statement)
            executed += 1
    finally:
        try:
            cursor.close()
        except Exception:
            pass

    return DDLResult(
        submitted=submitted,
        executed=executed,
        skipped=submitted - executed,
    )


# EOF
