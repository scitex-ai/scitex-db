#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite -> PostgreSQL migration for scitex-db-backed stores.

SCOPE, stated because the name invites a wider reading: this is a ONE-WAY
CUTOVER, not a backend abstraction. It copies a SQLite store into PostgreSQL and
proves the copy is faithful. It does not keep the two in sync, and it deliberately
provides no way to run both as live stores.

That restraint is the point rather than an omission. The fleet's card store
(scitex-cards) once had a selectable backend and the ambiguity destroyed the
board three times -- 2170 rows -> 18, 2136 -> 21, 2138 -> 1 -- because
"reconcile" deletes rows absent from whichever store is treated as the source.
That backend switch was deleted by operator ruling on 2026-07-20 ("provide no
exceptions, switch hard, leave nothing ambiguous, carry exactly ONE way in the
source"), and a migration tool that reintroduced two live stores would be
re-creating the exact condition that ruling removed. After a cutover there is
still exactly one store; it is simply a different one.

WHAT MAKES A MIGRATION HERE "DONE" is not that the copy loop finished, but that
:mod:`._verify` compared every row and found them identical. See that module for
why a row COUNT is not sufficient -- briefly, deletion in this schema is a
``_log_meta.deleted_at`` key inside a JSON column rather than a SQL flag, only 1
of 2872 live cards carries it, and the neighbouring shortcut of treating
``status='cancelled'`` as deleted would destroy 47 legitimately-cancelled cards.
"""

from __future__ import annotations

from ._copy import MigrationRefused, MigrationResult, Quiescence
from ._preflight import PreflightReport, preflight
from ._run import Destination, RunReport, migrate
from ._transform import (
    NulEscape,
    TransformationError,
    Transformations,
    plan_nul_escapes,
)
from ._verify import (
    MigrationVerificationError,
    VerificationReport,
    normalize_value,
    row_checksum,
    verify_table,
)

__all__ = [
    # The two entry points. `preflight` writes nothing and takes no
    # destination; `migrate` runs the whole thing and refuses unless the
    # preflight is READY. They are separate names rather than one function with
    # a `dry_run` flag so that neither path can be reached by forgetting an
    # argument.
    "preflight",
    "migrate",
    "Destination",
    "Quiescence",
    # The declared-exception path: `plan_nul_escapes` enumerates what would be
    # changed, and the resulting `Transformations` must be passed explicitly.
    # Without one, a NUL column stays a blocker.
    "plan_nul_escapes",
    "Transformations",
    "NulEscape",
    "TransformationError",
    # Results.
    "PreflightReport",
    "RunReport",
    "MigrationResult",
    "VerificationReport",
    # Refusals, exported so a caller can catch them by type rather than by
    # matching on a message.
    "MigrationRefused",
    "MigrationVerificationError",
    # Comparison primitives, useful for auditing a migration by hand.
    "normalize_value",
    "row_checksum",
    "verify_table",
]

# EOF
