#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that a copy taken over a live writer cannot be marked complete.

The gap this closes is invisible to verification, which is why it needed its own
refusal rather than a better check: `verify` compares the rows the copy READ, so
a row written after the copy passed its table is missing from BOTH sides and the
comparison comes back clean. Two scitex-cards cutovers lost rows behind exactly
such a green report, and both had declared quiescence in good faith.

So every test here supplies CLEAN verification reports. If a passing verification
could talk the marker past this refusal, these tests would be the ones to notice.

Real SQLite destination. No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import sqlite3

import pytest

from scitex_db._migrate._copy import (
    MigrationRefused,
    StoreScope,
    finalize,
    read_marker,
)
from scitex_db._migrate._observe import QuiescenceEvidence
from scitex_db._migrate._provenance import Quiescence
from scitex_db._migrate._verify import VerificationReport

QUIET = Quiescence(mechanism="operator", stated_by="test")
WHOLE = StoreScope(database_is_whole_store=True, stated_by="test")
CLEAN = (
    VerificationReport(
        table="t", source_rows=1, destination_rows=1, rows_compared=1
    ),
)

SAW_A_WRITER = QuiescenceEvidence(
    observed_seconds=60.0,
    sample_interval_seconds=0.2,
    samples_taken=300,
    writes_seen=7,
    signals_fired=("data_version",),
)
SAW_NOTHING = QuiescenceEvidence(
    observed_seconds=60.0,
    sample_interval_seconds=0.2,
    samples_taken=300,
    writes_seen=0,
)
COULD_NOT_LOOK = QuiescenceEvidence(
    observed_seconds=0.0,
    sample_interval_seconds=0.2,
    samples_taken=0,
    writes_seen=0,
    unobservable_reason="source is not a local file",
)


@pytest.fixture
def write():
    """A real destination the marker is genuinely written into."""
    conn = sqlite3.connect(":memory:")

    def _write(sql, params):
        conn.execute(sql, params)

    _write.conn = conn
    yield _write
    conn.close()


def _finalize(write, evidence):
    return finalize(
        [],
        CLEAN,
        QUIET,
        write,
        source_identity="source",
        completed_at="2026-08-01T00:00:00Z",
        store_identity="successor",
        predecessor_identity="predecessor",
        store_scope=WHOLE,
        quiescence_evidence=evidence,
    )


def _fetch(write):
    def _f(sql):
        return write.conn.execute(sql).fetchall()

    return _f


def test_an_observed_writer_refuses_the_marker(write):
    """The negative control: a clean verification must NOT talk it past this."""
    # Arrange
    evidence = SAW_A_WRITER
    # Act
    act = lambda: _finalize(write, evidence)
    # Assert
    with pytest.raises(MigrationRefused, match="writer was OBSERVED"):
        act()


@pytest.fixture
def refused(write):
    """A destination on which a run over an observed writer was refused.

    The refusal is performed here rather than in each test so that asserting on
    its message and asserting on its aftermath stay one assertion each.
    """
    try:
        _finalize(write, SAW_A_WRITER)
    except MigrationRefused as exc:
        return write, str(exc)
    raise AssertionError("finalize accepted a run taken over an observed writer")


def test_the_refusal_quotes_the_window_that_was_watched(refused):
    """A refusal a caller cannot act on is half-written -- name the evidence."""
    # Arrange
    _, message = refused
    # Act
    quoted = "0.20s sampling" in message
    # Assert
    assert quoted, message


def test_the_refusal_names_the_signal_that_caught_the_writer(refused):
    """Which signal fired is what tells an operator where to look."""
    # Arrange
    _, message = refused
    # Act
    named = "data_version" in message
    # Assert
    assert named, message


def test_a_refused_run_leaves_no_marker(refused):
    """Refusing loudly is worth nothing if the destination still looks usable."""
    # Arrange
    destination, _ = refused
    # Act
    marker = read_marker(_fetch(destination))
    # Assert
    assert marker is None


def test_observing_nothing_still_completes(write):
    """The positive control: a guard that refuses every run is not a guard."""
    # Arrange
    evidence = SAW_NOTHING
    # Act
    result = _finalize(write, evidence)
    # Assert
    assert result.ok


def test_not_having_looked_still_completes(write):
    """Un-observed runs stay legal -- this is evidence, not a new precondition.

    Refusing them would make the feature a breaking change for every caller who
    cannot stop their writers, and would push them toward not upgrading at all.
    """
    # Arrange
    evidence = None
    # Act
    result = _finalize(write, evidence)
    # Assert
    assert result.ok


def test_an_unobservable_source_still_completes(write):
    """'Could not look' is not 'saw a writer' -- it must not refuse."""
    # Arrange
    evidence = COULD_NOT_LOOK
    # Act
    result = _finalize(write, evidence)
    # Assert
    assert result.ok


def test_the_marker_records_that_nobody_looked(write):
    """An explicit null, so a reader can tell 'unobserved' from 'old format'."""
    # Arrange
    _finalize(write, None)
    # Act
    marker = read_marker(_fetch(write))
    # Assert
    assert marker["quiescence"]["observed"] is None


def test_the_marker_records_the_window_that_was_watched(write):
    """The window is the result. A marker without it cannot be interpreted."""
    # Arrange
    _finalize(write, SAW_NOTHING)
    # Act
    observed = read_marker(_fetch(write))["quiescence"]["observed"]
    # Assert
    assert observed["window_seconds"] == 60.0


def test_the_marker_records_the_sampling_interval(write):
    """A silence at 0.2s and a silence at 60s are different facts."""
    # Arrange
    _finalize(write, SAW_NOTHING)
    # Act
    observed = read_marker(_fetch(write))["quiescence"]["observed"]
    # Assert
    assert observed["sample_interval_seconds"] == 0.2


def test_the_marker_keeps_the_unobservable_reason(write):
    """Why nobody could look survives into the destination's own account."""
    # Arrange
    _finalize(write, COULD_NOT_LOOK)
    # Act
    observed = read_marker(_fetch(write))["quiescence"]["observed"]
    # Assert
    assert observed["unobservable_reason"] == "source is not a local file"


def test_the_claim_is_still_recorded_beside_the_observation(write):
    """Evidence supplements the declaration; it does not replace it."""
    # Arrange
    _finalize(write, SAW_NOTHING)
    # Act
    quiescence = read_marker(_fetch(write))["quiescence"]
    # Assert
    assert quiescence["mechanism"] == "operator"

# EOF
