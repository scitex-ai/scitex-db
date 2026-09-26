#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _preflight: collect everything, and earn every zero."""

from __future__ import annotations

from scitex_db.schema_change import ArtifactProbe, preflight


def test_zero_control_marks_instrument_not_live(conn, dead_control):
    """A dead instrument's zeros must not read as a clean store."""
    # Arrange
    checks = [dead_control]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is False


def test_zero_control_makes_report_not_ok(conn, dead_control):
    # Arrange
    checks = [dead_control]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_run_without_any_control_is_not_live(conn, present_artifact):
    """Absence of a control is absence of proof, not permission."""
    # Arrange
    checks = [present_artifact]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is False


def test_live_control_marks_instrument_live(conn, live_control):
    # Arrange
    checks = [live_control]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is True


def test_all_passing_findings_are_still_not_ok_without_a_control(conn, present_artifact):
    """A dead instrument must veto ok even when every finding PASSED.

    ADDED AFTER A SURVIVING MUTATION. Deleting the instrument_live guard from
    Report.ok left all 21 tests green: every existing case that asserted
    ok is False also had a FAILING finding, so all(...) alone produced False
    and the guard was never exercised. This is the only shape that isolates it
    -- instrument not proven live, nothing else wrong.
    """
    # Arrange
    checks = [present_artifact]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_unknown_finding_makes_report_not_ok(conn, live_control, broken_artifact):
    # Arrange
    checks = [live_control, broken_artifact]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_every_check_runs_even_after_a_failure(conn, live_control):
    """Stopping at the first problem turns one review into N runs."""
    # Arrange
    calls: list[str] = []

    def make(name: str, ok: bool) -> ArtifactProbe:
        return ArtifactProbe(
            name=name,
            artifact=name,
            exists=lambda c, n=name, o=ok: (calls.append(n), o)[1],
        )

    checks = [live_control, make("a", False), make("b", False), make("c", True)]
    # Act
    preflight(conn, checks)
    # Assert
    assert calls == ["a", "b", "c"]


def test_report_collects_every_finding(conn, live_control):
    # Arrange
    probes = [
        ArtifactProbe(name=f"p{i}", artifact=f"a{i}", exists=lambda c: False)
        for i in range(3)
    ]
    # Act
    report = preflight(conn, [live_control, *probes])
    # Assert
    assert len(report.findings) == 4
