#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that quiescence is SAMPLED, and that the sampling can actually fail.

THE NEGATIVE CONTROL IS THE POINT OF THIS FILE. A quiescence check that returns
"nothing seen" is trivially easy to write and impossible to distinguish from one
that works, so the load-bearing test here is the one where a writer of exactly
the shape that defeated a point-in-time check on the live scitex-cards store
must be SEEN.

Measured there, 2026-08-01: `lsof` showed nobody holding the database while a
watcher wrote it every two seconds, because the writer opens, writes and closes.
Only 0.2s-interval polling caught it. Any check built on two readings would have
reported quiescence proven over the exact process that lost the rows.

Real SQLite files and a real background thread. No mocks -- a mocked writer
would prove only that the code notices a value the test changed for it, which is
the assumption under test. One assertion per test, AAA markers.
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from scitex_db._migrate._observe import QuiescenceEvidence, observe_source

# Short enough that the suite does not drag, long enough that several samples
# land. The writer below is far faster than the interval, so the window does not
# need to be generous to catch it.
WINDOW = 0.60
INTERVAL = 0.05


@pytest.fixture
def db(tmp_path):
    """A real SQLite database with one row, closed before the test looks."""
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES ('seed')")
    conn.commit()
    conn.close()
    yield str(path)


@pytest.fixture
def open_write_close(db):
    """A writer that holds NO handle between writes -- the invisible kind.

    It opens, commits one row, and closes, repeatedly. A point-in-time check for
    "who holds this file?" finds nobody almost every time it asks.
    """
    stop = threading.Event()

    def _loop():
        while not stop.is_set():
            conn = sqlite3.connect(db)
            conn.execute("INSERT INTO t (v) VALUES ('late')")
            conn.commit()
            conn.close()
            time.sleep(0.02)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    yield db
    stop.set()
    thread.join(timeout=5)


def test_a_writer_that_opens_writes_and_closes_is_caught(open_write_close):
    """The negative control: this is the writer that defeats snapshot checks."""
    # Arrange
    source = open_write_close
    # Act
    evidence = observe_source(source, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert evidence.writes_seen > 0, evidence.summary()


def test_the_caught_writer_names_the_signal_that_fired(open_write_close):
    """A refusal a caller cannot act on is half-written."""
    # Arrange
    source = open_write_close
    # Act
    evidence = observe_source(source, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert evidence.signals_fired, evidence.summary()


def test_the_data_version_signal_is_alive_not_merely_present(open_write_close):
    """Pins the signal that shipped DEAD in the first version of this module.

    `PRAGMA data_version` only changes on a connection HELD across the write; a
    fresh connection per reading re-reads its own baseline and returns the same
    value forever. That bug passed every other test in this file, because the
    stat signals were carrying them alone -- a dead signal beside a live one is
    invisible. This test fails if the connection is ever re-opened per sample.
    """
    # Arrange
    source = open_write_close
    # Act
    evidence = observe_source(source, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert "data_version" in evidence.signals_fired, evidence.summary()


def test_a_quiet_source_reports_no_writer(db):
    """The positive control: a guard that fires on everything is not a guard."""
    # Arrange
    source = db
    # Act
    evidence = observe_source(source, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert evidence.writes_seen == 0, evidence.summary()


def test_a_quiet_source_still_took_more_than_one_reading(db):
    """A single reading can only ever say 'no writes' -- that is not evidence."""
    # Arrange
    source = db
    # Act
    evidence = observe_source(source, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert evidence.samples_taken >= 2


def test_silence_is_reported_with_the_window_it_covers(db):
    """There is no unqualified form of the negative answer."""
    # Arrange
    source = db
    # Act
    evidence = observe_source(source, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert "no writer observed over" in evidence.summary()


def test_a_missing_source_is_unobservable_not_quiet(tmp_path):
    """The third value. 'I could not look' must not read as 'I looked'."""
    # Arrange
    absent = str(tmp_path / "absent.db")
    # Act
    evidence = observe_source(absent, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert not evidence.observed


def test_an_unobservable_source_says_it_is_not_evidence_of_quiet(tmp_path):
    """The summary must refuse to be read as a clean bill of health."""
    # Arrange
    absent = str(tmp_path / "absent.db")
    # Act
    evidence = observe_source(absent, seconds=WINDOW, interval=INTERVAL)
    # Assert
    assert "not evidence of quiet" in evidence.summary()


def test_a_window_shorter_than_the_interval_is_refused(db):
    """One reading could only ever report 'no writes' -- refuse to pretend."""
    # Arrange
    source = db
    # Act
    act = lambda: observe_source(source, seconds=0.01, interval=1.0)
    # Assert
    with pytest.raises(ValueError, match="cannot fail"):
        act()


def test_a_non_positive_interval_is_refused(db):
    """A zero interval would spin without advancing the window."""
    # Arrange
    source = db
    # Act
    act = lambda: observe_source(source, seconds=1.0, interval=0.0)
    # Assert
    with pytest.raises(ValueError, match="must be positive"):
        act()


def test_evidence_of_one_sample_cannot_be_constructed():
    """The validator: fewer than two readings is not a sample, by definition."""
    # Arrange
    fields = dict(
        observed_seconds=1.0,
        sample_interval_seconds=0.1,
        samples_taken=1,
        writes_seen=0,
    )
    # Act
    act = lambda: QuiescenceEvidence(**fields)
    # Assert
    with pytest.raises(ValueError, match="is not a sample"):
        act()


def test_unobservable_evidence_cannot_also_claim_readings():
    """A contradiction must fail where it is built, not three layers down."""
    # Arrange
    fields = dict(
        observed_seconds=1.0,
        sample_interval_seconds=0.1,
        samples_taken=5,
        writes_seen=0,
        unobservable_reason="gone",
    )
    # Act
    act = lambda: QuiescenceEvidence(**fields)
    # Assert
    with pytest.raises(ValueError, match="contradictory evidence"):
        act()


def test_seen_writes_must_name_a_signal():
    """Evidence of a writer with no signal named is not actionable."""
    # Arrange
    fields = dict(
        observed_seconds=1.0,
        sample_interval_seconds=0.1,
        samples_taken=5,
        writes_seen=1,
    )
    # Act
    act = lambda: QuiescenceEvidence(**fields)
    # Assert
    with pytest.raises(ValueError, match="no signal is named"):
        act()


def test_there_is_no_unqualified_quiescent_property():
    """Guards the design: any boolean here would drop the window or the third
    value, and a caller who finds one will use it instead of the evidence."""
    # Arrange
    subject = QuiescenceEvidence
    # Act
    has_shortcut = hasattr(subject, "quiescent")
    # Assert
    assert not has_shortcut

# EOF
