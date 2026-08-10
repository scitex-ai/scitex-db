#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The answer shape. One ``ok``; named fields say why not.

THREE-VALUED BY CONSTRUCTION. :class:`Status` has no boolean coercion and
``UNKNOWN`` is a member, not a sentinel, so a caller cannot write
``if status:`` and silently treat "I could not tell" as "yes". The constitution
names collapsing unknown into either pole as the most common bug we ship; here
it is a TypeError rather than a convention.

WHY ``ok`` IS COMPUTED AND NOT SETTABLE: a report whose verdict can be assigned
independently of its findings is a report that can disagree with itself, and the
disagreement is invisible. ``ok`` is derived every time it is read.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Sequence


class Status(enum.Enum):
    """Three-valued check outcome. Deliberately not a bool.

    ``UNKNOWN`` is the value a check returns when it CANNOT BE EVALUATED -- not
    when it evaluated to "no". The distinction is the whole point: "the change
    has not landed" is actionable, "I have no way to tell whether it landed" is
    a missing instrument, and treating the second as the first is how a gate
    reports a confident answer it never computed.
    """

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"

    def __bool__(self) -> bool:  # pragma: no cover - the raise IS the behaviour
        raise TypeError(
            "Status is three-valued and must not be used in a boolean context; "
            "compare explicitly against Status.PASS / FAIL / UNKNOWN. "
            "A truthiness test would silently read UNKNOWN as a definite answer."
        )


@dataclass(frozen=True)
class Finding:
    """One check's outcome, with the evidence that produced it.

    ``detail`` carries what was actually observed, not a restatement of the
    verdict -- an error that only says what broke is half-written. ``hint`` says
    what to do next, which is the half that makes a failure actionable.
    """

    name: str
    status: Status
    detail: str
    hint: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Finding.name must be non-empty; an unnamed finding cannot be acted on")
        if not self.detail:
            raise ValueError(
                f"Finding {self.name!r} has no detail. A verdict without evidence "
                "is unreviewable; record what was observed."
            )
        if self.status is not Status.PASS and not self.hint:
            raise ValueError(
                f"Finding {self.name!r} is {self.status.value} but carries no hint. "
                "A non-passing finding must say what to do about it."
            )


@dataclass(frozen=True)
class Report:
    """Every finding from one preflight run. ``ok`` is derived, never assigned.

    ``instrument_live`` is separate from the findings on purpose. If a positive
    control failed, the run did not merely find problems -- it PROVED NOTHING,
    and its zeros are meaningless. A caller must be able to tell "the store is
    clean" from "the probe was dead" without reading prose.
    """

    findings: Sequence[Finding] = field(default_factory=tuple)
    instrument_live: bool = True

    @property
    def ok(self) -> bool:
        """True only when the instrument was live AND every finding passed.

        UNKNOWN counts against ``ok``. A change must not proceed on a question
        nobody could answer.
        """
        if not self.instrument_live:
            return False
        return all(f.status is Status.PASS for f in self.findings)

    @property
    def unknowns(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status is Status.UNKNOWN)

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.status is Status.FAIL)

    def summary(self) -> str:
        if not self.instrument_live:
            return "NOT READY - instrument not live; this run proved nothing"
        if self.ok:
            return f"READY - {len(self.findings)} checks passed"
        return (
            f"NOT READY - {len(self.failures)} failed, "
            f"{len(self.unknowns)} unknown, of {len(self.findings)}"
        )
