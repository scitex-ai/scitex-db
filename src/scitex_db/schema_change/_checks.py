#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The check types. Each exists because a weaker one was measured to fail.

There is deliberately NO ``ColumnProbe`` and NO ``VersionProbe``. Both were
available, both are the obvious thing to reach for, and both are wrong for
answering "has this change landed" -- see the package docstring. Omitting them
is the mechanism; a warning in a comment would not be.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from ._report import Finding, Status


@runtime_checkable
class Check(Protocol):
    """Anything that can look at a live connection and produce one Finding.

    A check NEVER raises for a condition it is testing -- that is what
    :class:`~scitex_db.schema_change._report.Status` is for. It may raise only
    if the connection itself is unusable, which is a different failure and
    belongs to the caller.
    """

    name: str

    def run(self, conn: Any) -> Finding: ...


@dataclass(frozen=True)
class ArtifactProbe:
    """Has the change landed? Answered ONLY by a physical artifact's existence.

    The artifact must be something the change ITSELF installs -- a trigger, a
    constraint, a generated column. Then "landed" and "artifact present" are the
    same fact rather than two facts that can drift, and the probe cannot go
    green early.

    WORKED EXAMPLE, and the reason this class is shaped this way: scitex-cards'
    row-level write path is rung ``tasks_row_level_write`` at schema version 10.
    Probing ``revision`` (a column) returned green four minutes after the gate
    was written, because ``revision`` has existed since v6 and says nothing about
    which write path is live. Probing the trigger returns False today and True
    the moment the flip installs it.

    ``exists`` is supplied by the caller so this module does not depend on any
    particular store package: pass ``scitex_cards._schema_probe.has_trigger``
    partially applied, or any callable of ``(conn) -> bool``.
    """

    name: str
    artifact: str
    exists: Callable[[Any], bool]

    def run(self, conn: Any) -> Finding:
        try:
            present = self.exists(conn)
        except Exception as exc:  # the probe itself broke -> UNKNOWN, never FAIL
            return Finding(
                name=self.name,
                status=Status.UNKNOWN,
                detail=f"probe for artifact {self.artifact!r} raised {type(exc).__name__}: {exc}",
                hint=(
                    "The probe could not run, so this is NOT evidence the change is absent. "
                    "Fix the probe or the connection, then re-run."
                ),
            )
        if present:
            return Finding(
                name=self.name,
                status=Status.PASS,
                detail=f"artifact {self.artifact!r} is present",
            )
        return Finding(
            name=self.name,
            status=Status.FAIL,
            detail=f"artifact {self.artifact!r} is absent",
            hint=(
                f"The change that installs {self.artifact!r} has not run against this store. "
                "This is an honest NO, not an error."
            ),
        )


@dataclass(frozen=True)
class PositiveControl:
    """Proves the instrument is LIVE. Its failure invalidates the whole run.

    WHY: a count of 0 from a dead connection, a typo'd table name, or a query
    against the wrong database reads exactly like a clean bill of health. Every
    zero in a report is only as trustworthy as the proof that a non-zero was
    reachable.

    ``expect_nonzero`` must be a query whose answer is known to be > 0 on any
    healthy store -- typically a row count of a table that is never empty.
    """

    name: str
    query: str
    fetch_one_int: Callable[[Any, str], int]

    def run(self, conn: Any) -> Finding:
        try:
            value = self.fetch_one_int(conn, self.query)
        except Exception as exc:
            return Finding(
                name=self.name,
                status=Status.UNKNOWN,
                detail=f"control query raised {type(exc).__name__}: {exc}",
                hint="The instrument could not be verified; treat every zero in this run as meaningless.",
            )
        if value > 0:
            return Finding(
                name=self.name,
                status=Status.PASS,
                detail=f"control returned {value}, instrument is live",
            )
        return Finding(
            name=self.name,
            status=Status.FAIL,
            detail=f"control returned {value}; a healthy store must return > 0",
            hint=(
                "The instrument is not reaching live data -- wrong database, wrong schema, "
                "or a dead connection. Every zero in this run is uninformative, not clean."
            ),
        )


@dataclass(frozen=True)
class ExpectedFailure:
    """A constraint that MUST refuse. Success is the alarming outcome.

    WHY THIS IS A CHECK TYPE and not a test: the properties that matter most on
    a live store are the refusals -- a missing parent must still be rejected, a
    downgrade must still be refused. A suite that only asserts things succeed
    cannot tell a working guard from a deleted one.

    ``attempt`` must perform the operation and let it raise. Rolling back is the
    caller's business; this class never commits.
    """

    name: str
    attempt: Callable[[Any], None]
    describe: str

    def run(self, conn: Any) -> Finding:
        try:
            self.attempt(conn)
        except Exception as exc:
            return Finding(
                name=self.name,
                status=Status.PASS,
                detail=f"{self.describe} was refused ({type(exc).__name__}), as required",
            )
        return Finding(
            name=self.name,
            status=Status.FAIL,
            detail=f"{self.describe} was ACCEPTED; the guard that should refuse it is not in force",
            hint=(
                "This is the dangerous direction: the store accepted something it must reject. "
                "Do not run the change until the guard is restored."
            ),
        )
