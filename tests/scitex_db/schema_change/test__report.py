#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _report: three-valued Status, evidence-bearing Finding, derived ok."""

from __future__ import annotations

import pytest

from scitex_db.schema_change import Finding, Report, Status


def test_unknown_status_refuses_boolean_coercion():
    """UNKNOWN must not be silently readable as a definite answer."""
    # Arrange
    status = Status.UNKNOWN
    # Act
    # Assert
    with pytest.raises(TypeError, match="three-valued"):
        bool(status)


def test_pass_status_also_refuses_boolean_coercion():
    # Arrange
    status = Status.PASS
    # Act
    # Assert
    with pytest.raises(TypeError, match="three-valued"):
        bool(status)


def test_failing_finding_makes_ok_false():
    """ok is computed, so a report cannot contradict its findings."""
    # Arrange
    finding = Finding(name="x", status=Status.FAIL, detail="d", hint="h")
    # Act
    report = Report(findings=(finding,), instrument_live=True)
    # Assert
    assert report.ok is False


def test_ok_cannot_be_assigned():
    # Arrange
    report = Report(findings=(), instrument_live=True)
    # Act
    # Assert
    with pytest.raises(AttributeError):
        report.ok = True  # type: ignore[misc]


def test_finding_without_detail_is_refused():
    # Arrange
    kwargs = dict(name="x", status=Status.PASS, detail="")
    # Act
    # Assert
    with pytest.raises(ValueError, match="no detail"):
        Finding(**kwargs)


def test_non_passing_finding_without_hint_is_refused():
    """An error that only states what broke is half-written."""
    # Arrange
    kwargs = dict(name="x", status=Status.FAIL, detail="something")
    # Act
    # Assert
    with pytest.raises(ValueError, match="no hint"):
        Finding(**kwargs)


def test_summary_of_a_dead_instrument_says_it_proved_nothing():
    # Arrange
    report = Report(findings=(), instrument_live=False)
    # Act
    text = report.summary()
    # Assert
    assert "proved nothing" in text
