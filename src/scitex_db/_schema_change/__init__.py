#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Is a LIVE store ready for an IN-PLACE schema change, and what will it cost?

A sibling of :mod:`scitex_db._migrate`, deliberately NOT part of it. ``_migrate``
is a ONE-WAY CUTOVER (SQLite -> PostgreSQL) and its own docstring says so. Its
narrowness is load-bearing: a selectable backend destroyed the card board three
times (2170 rows -> 18, 2136 -> 21, 2138 -> 1), because "reconcile" deletes rows
absent from whichever store is treated as the source. The operator's 2026-07-20
ruling was "provide no exceptions, switch hard, carry exactly ONE way in the
source". A module that grew a second mode would rebuild the condition that
ruling removed -- so this is a second module, not a second mode.

THE QUESTION THIS ANSWERS is different from a cutover's. A cutover asks "can the
destination hold the source". An in-place change asks "is this store, which ~90
containers are reading and writing RIGHT NOW, in the shape this change assumes --
and how long will their board be frozen while it runs".

TWO ENTRY POINTS, NOT A ``dry_run`` FLAG -- inherited from ``_migrate._preflight``
and correct for the same reason: a ``dry_run=False`` default makes the
destructive path the one you get by forgetting an argument. :func:`preflight`
takes no DDL and therefore CANNOT write, which is a stronger guarantee than a
branch that promises not to.

FOUR REQUIREMENTS, each from a measured failure rather than from taste:

1. A LANDED-CHECK MUST PROBE A PHYSICAL ARTIFACT. Never a version stamp, never
   column state.
   - Not a stamp: scitex-cards' migration chain has a documented v3->v4 hole, so
     a store upgraded v3->v5 never received v4 while its stamp reads 5 regardless
     (``_db_migrations.py``: "check the COLUMNS, never user_version").
   - Not column state either, which is the half a reader is likely to miss: on
     the card store the ~33 typed columns are DUAL-WRITTEN on every write today
     (``_db_bootstrap.py:190-208``), so "columns exist" AND "columns populated"
     are both green BEFORE the change. No probe over column state can distinguish
     pre- from post-change. Only an artifact installed BY the change can.
   This is why :class:`ArtifactProbe` exists and why there is no
   ``ColumnProbe``: the wrong answer is not available, rather than discouraged.

2. EVERY PROBLEM IS COLLECTED, never raised on the first. A check that stops at
   the first failure turns a schema review into as many runs as there are
   problems, with no way to tell whether you are halfway or nearly done.

3. UNKNOWN IS A THIRD STATE. A check that cannot be evaluated must say so, and
   :attr:`Report.ok` must be False when anything is UNKNOWN. Collapsing unknown
   into either pole is the failure this whole module exists to prevent -- it is
   how a gate on this fleet went green for the wrong reason for four minutes,
   satisfied by a pre-existing column.

4. A ZERO MUST BE EARNED. A count of 0 from a dead connection, a typo'd table
   name or an empty result set reads exactly like a clean bill of health.
   :class:`PositiveControl` requires a query whose non-zero answer proves the
   instrument is live, and its failure invalidates the run rather than adding a
   finding.

WHAT IS NOT HERE YET, stated so absence is not read as completeness: lock-held
cost measurement per statement (ALTER takes ACCESS EXCLUSIVE and freezes every
agent's board), and migrate-a-copy-first as the default. Both are on the card.
"""

from __future__ import annotations

from ._report import Report, Finding, Status
from ._checks import ArtifactProbe, PositiveControl, ExpectedFailure, Check
from ._preflight import preflight
from ._lock_cost import LockCost, RefusedToLockLiveStore, measure_lock_cost

__all__ = [
    "preflight",
    "Report",
    "Finding",
    "Status",
    "Check",
    "ArtifactProbe",
    "PositiveControl",
    "ExpectedFailure",
    "measure_lock_cost",
    "LockCost",
    "RefusedToLockLiveStore",
]
