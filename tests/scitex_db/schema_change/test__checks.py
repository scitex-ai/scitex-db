#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _checks: the artifact probe, the control, the expected failure."""

from __future__ import annotations

from scitex_db.schema_change import ExpectedFailure, Status


def test_absent_artifact_reports_fail(conn, absent_artifact):
    # Arrange
    probe = absent_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.FAIL


def test_absent_artifact_hint_says_it_is_an_honest_no(conn, absent_artifact):
    # Arrange
    probe = absent_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert "honest NO" in finding.hint


def test_present_artifact_reports_pass(conn, present_artifact):
    # Arrange
    probe = present_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.PASS


def test_broken_probe_reports_unknown_not_fail(conn, broken_artifact):
    """A probe that cannot run says nothing about the store."""
    # Arrange
    probe = broken_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.UNKNOWN


def test_broken_probe_hint_denies_it_is_evidence(conn, broken_artifact):
    # Arrange
    probe = broken_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert "NOT evidence" in finding.hint


def test_refused_operation_reports_pass(conn):
    # Arrange
    def attempt(c):
        raise ValueError("FK violation")

    check = ExpectedFailure(
        name="missing parent refused",
        attempt=attempt,
        describe="insert with a genuinely missing parent",
    )
    # Act
    finding = check.run(conn)
    # Assert
    assert finding.status is Status.PASS


def test_accepted_operation_reports_fail(conn):
    """The guard being GONE is what this check exists to catch."""
    # Arrange
    check = ExpectedFailure(
        name="missing parent refused",
        attempt=lambda c: None,
        describe="insert with a genuinely missing parent",
    )
    # Act
    finding = check.run(conn)
    # Assert
    assert finding.status is Status.FAIL


def test_accepted_operation_hint_names_the_dangerous_direction(conn):
    # Arrange
    check = ExpectedFailure(
        name="missing parent refused",
        attempt=lambda c: None,
        describe="insert with a genuinely missing parent",
    )
    # Act
    finding = check.run(conn)
    # Assert
    assert "dangerous direction" in finding.hint
