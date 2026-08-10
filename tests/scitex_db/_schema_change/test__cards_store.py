#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _cards_store: the binding scitex-cards calls for the v10 rung."""

from __future__ import annotations

from scitex_db._schema_change import PositiveControl, Status, preflight
from scitex_db._schema_change._cards_store import (
    catalogue_is_visible,
    row_level_write_landed,
    v10_rung_checks,
)


def test_row_level_write_probe_reports_fail_when_trigger_absent(conn):
    # Arrange
    probe = row_level_write_landed(has_trigger=lambda c, name: False)
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.FAIL


def test_row_level_write_probe_reports_pass_when_trigger_present(conn):
    # Arrange
    probe = row_level_write_landed(has_trigger=lambda c, name: True)
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.PASS


def test_row_level_write_probe_asks_for_the_agreed_artifact_name(conn):
    """The rung name is scitex-cards' contract; drifting from it silently
    would make this probe answer a question nobody agreed to."""
    # Arrange
    asked: list[str] = []
    probe = row_level_write_landed(
        has_trigger=lambda c, name: (asked.append(name), False)[1]
    )
    # Act
    probe.run(conn)
    # Assert
    assert asked == ["tasks_row_level_write"]


def test_missing_cards_package_yields_unknown_not_fail(conn):
    """An absent package is not evidence that the change is absent."""
    # Arrange
    def unavailable(c, name):
        raise ImportError("No module named 'scitex_cards'")

    probe = row_level_write_landed(has_trigger=unavailable)
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.UNKNOWN


def test_v10_rung_checks_put_a_control_first(conn):
    """A reader must meet the instrument's verdict before findings that rest on it."""
    # Arrange
    checks = v10_rung_checks(
        fetch_one_int=lambda c, q: 3611,
        has_trigger=lambda c, name: False,
    )
    # Act
    first = checks[0]
    # Assert
    assert isinstance(first, PositiveControl)


def test_v10_rung_is_not_ready_on_a_store_without_the_trigger(conn):
    """The whole point: an honest NOT READY, from a live instrument."""
    # Arrange
    checks = v10_rung_checks(
        fetch_one_int=lambda c, q: 3611,
        has_trigger=lambda c, name: name == "tasks_bump_revision",
    )
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_blind_catalogue_makes_instrument_not_live(conn):
    """A catalogue read that sees NOTHING must not publish a verdict.

    THE ISOLATING CASE: a broken catalogue read returns False for every
    artifact, so row_level_write_landed reports "absent" -- byte-identical to
    an honest pre-flip store. This pins instrument_live rather than ok,
    because ok is False either way when the probe is blind.
    """
    # Arrange
    checks = v10_rung_checks(fetch_one_int=lambda c, q: 3611, has_trigger=lambda c, n: False)
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is False


def test_visible_catalogue_marks_instrument_live(conn):
    # Arrange
    sighted = lambda c, name: name == "tasks_bump_revision"
    checks = v10_rung_checks(fetch_one_int=lambda c, q: 3611, has_trigger=sighted)
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is True


def test_catalogue_control_asks_for_the_v7_rung(conn):
    """It must probe an artifact known to exist, through the same helper."""
    # Arrange
    asked: list[str] = []
    control = catalogue_is_visible(
        has_trigger=lambda c, name: (asked.append(name), True)[1]
    )
    # Act
    control.run(conn)
    # Assert
    assert asked == ["tasks_bump_revision"]
