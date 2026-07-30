#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._verify.

Real collaborators throughout -- real values, and for the end-to-end cases two
real on-disk SQLite databases standing in for source and destination. No mocks.

The tests that matter most are the ones asserting a REFUSAL: that an empty
comparison, an unpaired key, or an absent column set fails loudly instead of
reporting a clean match. A verification that can pass without checking anything
is the defect this module was written against, so those paths are tested as
first-class behaviour rather than as error handling.

One assertion per test, AAA markers (STX-TQ001/TQ002/TQ003/TQ007).
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from decimal import Decimal

import pytest

from scitex_db._migrate._verify import (
    MigrationVerificationError,
    VerificationReport,
    normalize_value,
    row_checksum,
    verify_table,
)

COLS = ("id", "title", "status")
KEY = ("id",)


@pytest.fixture
def two_dbs():
    """Two real SQLite databases: a source and a destination."""
    tmpdir = tempfile.mkdtemp()
    src = os.path.join(tmpdir, "source.db")
    dst = os.path.join(tmpdir, "destination.db")
    for path in (src, dst):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT)")
        conn.commit()
        conn.close()
    yield src, dst
    shutil.rmtree(tmpdir, ignore_errors=True)


def _insert(path, rows):
    conn = sqlite3.connect(path)
    conn.executemany("INSERT INTO tasks (id, title, status) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _read(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT id, title, status FROM tasks")]
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# normalize_value -- the cross-backend type reconciliation
# ----------------------------------------------------------------------------


def test_normalize_value_maps_true_to_one():
    # Arrange
    value = True
    # Act
    result = normalize_value(value)
    # Assert
    assert result == 1


def test_normalize_value_maps_false_to_zero():
    # Arrange
    value = False
    # Act
    result = normalize_value(value)
    # Assert
    assert result == 0


def test_normalize_value_keeps_boolean_and_integer_indistinguishable():
    # Arrange -- SQLite genuinely cannot tell these apart, so neither may we
    # Act
    result = normalize_value(True) == normalize_value(1)
    # Assert
    assert result is True


def test_normalize_value_renders_decimal_as_tagged_text():
    # Arrange
    value = Decimal("1.500")
    # Act
    result = normalize_value(value)
    # Assert
    assert result == "D:1.5"


def test_normalize_value_converts_memoryview_to_bytes():
    # Arrange
    value = memoryview(b"blob")
    # Act
    result = normalize_value(value)
    # Assert
    assert result == b"blob"


def test_normalize_value_converts_bytearray_to_bytes():
    # Arrange
    value = bytearray(b"blob")
    # Act
    result = normalize_value(value)
    # Assert
    assert result == b"blob"


def test_normalize_value_passes_none_through():
    # Arrange
    value = None
    # Act
    result = normalize_value(value)
    # Assert
    assert result is None


# ----------------------------------------------------------------------------
# row_checksum -- content hashing that distinguishes types and column identity
# ----------------------------------------------------------------------------


def test_row_checksum_is_stable_for_equal_rows():
    # Arrange
    a = {"id": "1", "title": "t", "status": "open"}
    b = {"id": "1", "title": "t", "status": "open"}
    # Act
    result = row_checksum(a, COLS) == row_checksum(b, COLS)
    # Assert
    assert result is True


def test_row_checksum_distinguishes_string_from_integer():
    # Arrange -- a column whose type drifted must NOT verify clean
    text = {"id": "1", "title": "1", "status": None}
    number = {"id": "1", "title": 1, "status": None}
    # Act
    result = row_checksum(text, COLS) == row_checksum(number, COLS)
    # Assert
    assert result is False


def test_row_checksum_does_not_fold_integral_float_into_int():
    # Arrange -- REAL -> INTEGER drift is exactly what this must catch
    as_float = {"id": "1", "title": 1.0, "status": None}
    as_int = {"id": "1", "title": 1, "status": None}
    # Act
    result = row_checksum(as_float, COLS) == row_checksum(as_int, COLS)
    # Assert
    assert result is False


def test_row_checksum_changes_when_a_column_is_renamed():
    # Arrange -- same values, different column identity
    row = {"id": "1", "title": "t", "status": "open"}
    # Act
    result = row_checksum(row, COLS) == row_checksum(row, ("id", "name", "status"))
    # Assert
    assert result is False


def test_row_checksum_changes_when_column_order_differs():
    # Arrange
    row = {"id": "1", "title": "t", "status": "open"}
    # Act
    result = row_checksum(row, COLS) == row_checksum(row, ("status", "title", "id"))
    # Assert
    assert result is False


def test_row_checksum_treats_absent_column_as_null():
    # Arrange
    absent = {"id": "1", "title": "t"}
    explicit_null = {"id": "1", "title": "t", "status": None}
    # Act
    result = row_checksum(absent, COLS) == row_checksum(explicit_null, COLS)
    # Assert
    assert result is True


def test_row_checksum_does_not_confuse_null_with_empty_string():
    # Arrange
    null = {"id": "1", "title": None, "status": "open"}
    empty = {"id": "1", "title": "", "status": "open"}
    # Act
    result = row_checksum(null, COLS) == row_checksum(empty, COLS)
    # Assert
    assert result is False


# ----------------------------------------------------------------------------
# verify_table -- pairing and comparison against real SQLite databases
# ----------------------------------------------------------------------------


def test_verify_table_reports_ok_for_an_identical_copy(two_dbs):
    # Arrange
    src, dst = two_dbs
    rows = [("1", "a", "open"), ("2", "b", "done")]
    _insert(src, rows)
    _insert(dst, rows)
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.ok is True


def test_verify_table_counts_the_rows_it_actually_compared(two_dbs):
    # Arrange
    src, dst = two_dbs
    rows = [("1", "a", "open"), ("2", "b", "done")]
    _insert(src, rows)
    _insert(dst, rows)
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.rows_compared == 2


def test_verify_table_detects_a_dropped_row(two_dbs):
    # Arrange -- the destructive case: destination lost a card
    src, dst = two_dbs
    _insert(src, [("1", "a", "open"), ("2", "b", "done")])
    _insert(dst, [("1", "a", "open")])
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.missing_ids == ("S:2",)


def test_verify_table_is_not_ok_when_a_row_was_dropped(two_dbs):
    # Arrange
    src, dst = two_dbs
    _insert(src, [("1", "a", "open"), ("2", "b", "done")])
    _insert(dst, [("1", "a", "open")])
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.ok is False


def test_verify_table_detects_an_unexpected_extra_row(two_dbs):
    # Arrange
    src, dst = two_dbs
    _insert(src, [("1", "a", "open")])
    _insert(dst, [("1", "a", "open"), ("99", "ghost", "open")])
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.extra_ids == ("S:99",)


def test_verify_table_detects_a_row_whose_content_changed(two_dbs):
    # Arrange -- same key, altered payload
    src, dst = two_dbs
    _insert(src, [("1", "original", "open")])
    _insert(dst, [("1", "tampered", "open")])
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.mismatched_ids == ("S:1",)


def test_verify_table_ignores_row_order(two_dbs):
    # Arrange -- neither backend guarantees order without ORDER BY
    src, dst = two_dbs
    _insert(src, [("1", "a", "open"), ("2", "b", "done")])
    _insert(dst, [("2", "b", "done"), ("1", "a", "open")])
    # Act
    report = verify_table("tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS)
    # Assert
    assert report.ok is True


# ----------------------------------------------------------------------------
# verify_table -- the refusals: a pass must mean something was checked
# ----------------------------------------------------------------------------


def test_verify_table_refuses_an_empty_comparison_by_default(two_dbs):
    # Arrange -- nothing on either side
    src, dst = two_dbs
    # Act
    source, destination = _read(src), _read(dst)
    # Assert
    with pytest.raises(MigrationVerificationError, match="establishes nothing"):
        verify_table("tasks", source, destination, key_columns=KEY, columns=COLS)


def test_verify_table_accepts_an_empty_table_when_told_to(two_dbs):
    # Arrange -- this store genuinely has empty tables (notifications, users)
    src, dst = two_dbs
    # Act
    report = verify_table(
        "tasks", _read(src), _read(dst), key_columns=KEY, columns=COLS, allow_empty=True
    )
    # Assert
    assert report.ok is True


def test_verify_table_refuses_when_no_key_columns_are_given(two_dbs):
    # Arrange
    src, dst = two_dbs
    _insert(src, [("1", "a", "open")])
    # Act
    source, destination = _read(src), _read(dst)
    # Assert
    with pytest.raises(MigrationVerificationError, match="cannot be paired"):
        verify_table("tasks", source, destination, key_columns=(), columns=COLS)


def test_verify_table_refuses_when_no_columns_are_compared(two_dbs):
    # Arrange
    src, dst = two_dbs
    _insert(src, [("1", "a", "open")])
    # Act
    source, destination = _read(src), _read(dst)
    # Assert
    with pytest.raises(MigrationVerificationError, match="no columns to compare"):
        verify_table("tasks", source, destination, key_columns=KEY, columns=())


def test_verify_table_refuses_a_non_unique_key():
    # Arrange -- pairing would otherwise compare a row against the wrong partner
    rows = [
        {"id": "dup", "title": "a", "status": "open"},
        {"id": "dup", "title": "b", "status": "done"},
    ]
    # Act
    source, destination = list(rows), list(rows)
    # Assert
    with pytest.raises(MigrationVerificationError, match="duplicate key"):
        verify_table("tasks", source, destination, key_columns=KEY, columns=COLS)


# ----------------------------------------------------------------------------
# VerificationReport -- the verdict always carries its denominator
# ----------------------------------------------------------------------------


def test_report_summary_states_the_number_of_rows_compared():
    # Arrange
    report = VerificationReport(
        table="tasks", rows_compared=2872, source_rows=2872, destination_rows=2872
    )
    # Act
    summary = report.summary()
    # Assert
    assert "2872 row(s) compared" in summary


def test_report_summary_says_mismatch_when_rows_differ():
    # Arrange
    report = VerificationReport(
        table="tasks",
        rows_compared=1,
        source_rows=2,
        destination_rows=1,
        missing_ids=("S:2",),
    )
    # Act
    summary = report.summary()
    # Assert
    assert "MISMATCH" in summary


# EOF
