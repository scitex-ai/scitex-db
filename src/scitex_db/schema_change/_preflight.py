#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The read-only entry point. Takes no DDL, therefore cannot write.

This function's signature is the guarantee. There is no ``apply``, no
``execute``, no ``dry_run`` -- nothing here accepts a statement to run, so
"preflight wrote to the store" is not a bug that can be introduced by editing a
default. The writing counterpart, when it exists, will be a DIFFERENT function
with a different name, which cannot be reached by omitting an argument.
"""

from __future__ import annotations

from typing import Any, Sequence

from ._checks import Check, PositiveControl
from ._report import Finding, Report, Status


def preflight(conn: Any, checks: Sequence[Check]) -> Report:
    """Run every check against ``conn`` and collect all findings.

    Parameters
    ----------
    conn
        An open connection to the store being examined. Never written to.
    checks
        The checks to run, in order. Every one runs even if an earlier one
        failed -- stopping early turns a schema review into as many runs as
        there are problems.

    Returns
    -------
    Report
        ``ok`` is True only when a positive control proved the instrument live
        AND every finding passed. UNKNOWN counts against it.

    Notes
    -----
    A run with NO positive control is reported as ``instrument_live=False``.
    That is deliberate and is the conservative direction: an unverified
    instrument's zeros are indistinguishable from a clean store, so the absence
    of a control is treated as the absence of proof rather than as permission.
    """
    findings: list[Finding] = []
    controls_present = False
    controls_passed = True

    for check in checks:
        try:
            finding = check.run(conn)
        except Exception as exc:
            # A check that raises has not answered its question. UNKNOWN, never
            # FAIL: a broken instrument is not evidence about the store.
            finding = Finding(
                name=getattr(check, "name", type(check).__name__),
                status=Status.UNKNOWN,
                detail=f"check raised {type(exc).__name__}: {exc}",
                hint="Fix the check or the connection; this says nothing about the store.",
            )
        findings.append(finding)

        if isinstance(check, PositiveControl):
            controls_present = True
            if finding.status is not Status.PASS:
                controls_passed = False

    return Report(
        findings=tuple(findings),
        instrument_live=controls_present and controls_passed,
    )
