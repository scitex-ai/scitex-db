#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prove a guarantee is ENFORCED by attempting the forbidden action.

WHY THIS IS NOT A `sqlite_master` QUERY, which is what it would obviously be.

A trigger row can exist and not fire. scitex-cards demonstrated that on
themselves on 2026-07-30: their enforcement test deleted a NONEXISTENT id "to be
safe", and a ``BEFORE DELETE`` trigger fires per row, so deleting zero rows
succeeded trivially and the test reported "not enforced" against a store where
the trigger demonstrably refuses. The test could not fail for the right reason,
so it could not pass for one either.

Presence is what you check before you know better. Enforcement is what you check
after, and the only way to check it is to try the thing that must not work.

THREE PROPERTIES CARRY THIS, and the third is the one that took a day to learn.

1. THE CALLER SUPPLIES THE FORBIDDEN STATEMENT. No table or column name from any
   particular store enters this package -- the same rule as everywhere else
   here, where tables come from the plan and columns from ``PRAGMA table_info``.
   What counts as forbidden is a fact about someone's schema, not about
   migrations.

2. IT ALWAYS ROLLS BACK, including when the statement SUCCEEDS. A probe that
   changed the store it was inspecting would be worse than no probe, and the
   success case is precisely the one where a change would land. The rollback is
   in a ``finally``, not on the happy path.

3. THE REFUSAL MUST BE PROVEN TO COME FROM THE GUARD. This is the part that is
   not obvious and that makes the difference between a check and a ritual.
   "Did it raise?" passes vacuously against:
     * a read-only connection      -> "attempt to write a readonly database"
     * a typo in the table name    -> "no such table"
     * a renamed column            -> "no such column"
     * a locked database           -> "database is locked"
   Every one of those raises, and every one would be read as "enforced" by a
   probe that only counted exceptions. So a probe MUST state what the guard's
   refusal looks like, and a probe that does not state one is REFUSED rather
   than run. An unfalsifiable check is not a weak check, it is a misleading one.

WHERE THIS BELONGS IN A CUTOVER, and it is not a free choice: an enforcement
attempt is a WRITE, and takes a write lock even though it rolls back. So it
cannot be a casual pre-check run the day before -- it has to happen inside the
quiet window, between verification and retirement. The honest check is also the
one that forces you to be quiesced in order to perform it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

__all__ = [
    "EnforcementNotProven",
    "EnforcementProbe",
    "ProbeResult",
    "probe_enforcement",
    "require_enforcement",
]


class EnforcementNotProven(Exception):
    """Raised when a guarantee could not be shown to be enforced."""


@dataclass(frozen=True)
class EnforcementProbe:
    """One forbidden action, and what its refusal is expected to look like.

    ``expect_message`` is REQUIRED and must be non-empty. It is the difference
    between proving the guard refused and merely observing that something did:
    a read-only connection, a missing table and a locked database all raise, and
    a probe without an expected message would call each of them "enforced".

    Use a fragment of the guard's own ``RAISE(ABORT, ...)`` text. Matching the
    message the guard itself emits is what ties the refusal to the guard rather
    than to the environment.
    """

    description: str
    statement: str
    expect_message: str
    params: Sequence[Any] = ()

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise EnforcementNotProven(
                "an enforcement probe with no description. The description is "
                "what a human reads when the cutover stops, so it must say "
                "which guarantee failed to prove itself."
            )
        if not self.statement.strip():
            raise EnforcementNotProven(
                f"{self.description}: no forbidden statement given. There is "
                f"nothing to attempt, so nothing can be proven."
            )
        if not self.expect_message.strip():
            raise EnforcementNotProven(
                f"{self.description}: no expected refusal message. Without one "
                f"this probe would report 'enforced' for a read-only "
                f"connection, a typo'd table, or a locked database -- every "
                f"failure raises, and only the guard's own message shows the "
                f"guard is what refused."
            )


@dataclass(frozen=True)
class ProbeResult:
    """What one probe established, and what actually happened."""

    probe: EnforcementProbe
    enforced: bool
    detail: str

    def summary(self) -> str:
        verdict = "ENFORCED" if self.enforced else "NOT ENFORCED"
        return f"{self.probe.description}: {verdict} -- {self.detail}"


def probe_enforcement(conn: Any, probe: EnforcementProbe) -> ProbeResult:
    """Attempt ``probe``'s forbidden statement; report whether the guard refused.

    ``conn`` must be WRITABLE. A read-only connection makes every probe fail for
    the wrong reason, which the expected-message requirement catches and reports
    as NOT ENFORCED rather than silently passing.

    The statement always runs inside a transaction that is rolled back in a
    ``finally``, so a store whose guard is missing -- the case where the
    statement SUCCEEDS -- is left exactly as it was found.
    """
    try:
        try:
            conn.execute(probe.statement, tuple(probe.params))
        except Exception as exc:
            text = str(exc)
            if probe.expect_message in text:
                return ProbeResult(
                    probe=probe,
                    enforced=True,
                    detail=f"refused by the guard: {text.strip()[:160]}",
                )
            return ProbeResult(
                probe=probe,
                enforced=False,
                detail=(
                    f"the statement failed, but NOT with the guard's message "
                    f"(expected {probe.expect_message!r}). Something other than "
                    f"the guard refused this, so nothing was proven: "
                    f"{text.strip()[:160]}"
                ),
            )
        return ProbeResult(
            probe=probe,
            enforced=False,
            detail=(
                "the forbidden statement SUCCEEDED. The guarantee is not "
                "enforced on this store -- rolled back, so nothing changed, but "
                "the success is the finding."
            ),
        )
    finally:
        # In a `finally` because the dangerous branch is the one where the
        # statement worked, and that is exactly the branch an early return
        # would skip.
        conn.rollback()


def require_enforcement(
    conn: Any, probes: Sequence[EnforcementProbe]
) -> tuple[ProbeResult, ...]:
    """Run every probe; RAISE unless all of them proved enforcement.

    Every probe runs even after one fails, so a stopped cutover reports all the
    missing guarantees at once rather than one per attempt.

    Raises :class:`EnforcementNotProven` naming the failures. An empty probe
    list also raises: proving nothing is not the same as proving everything, and
    a caller that passes no probes has almost certainly made a mistake rather
    than a decision.
    """
    if not probes:
        raise EnforcementNotProven(
            "no enforcement probes given. An empty check proves nothing while "
            "returning success, which is the failure mode this module exists "
            "to prevent."
        )
    results = tuple(probe_enforcement(conn, p) for p in probes)
    failed = [r for r in results if not r.enforced]
    if failed:
        raise EnforcementNotProven(
            f"{len(failed)} of {len(results)} guarantee(s) could not be shown "
            f"to be enforced on this store. Retiring or migrating a store that "
            f"cannot enforce its own invariants would be theatre -- the "
            f"operation would report success having guaranteed nothing.\n"
            + "\n".join(r.summary() for r in results)
        )
    return results


# EOF
