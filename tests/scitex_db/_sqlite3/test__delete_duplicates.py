#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Timestamp: "2026-05-18 (test-quality cleanup)"
# File: /tests/scitex/db/_sqlite3/test__delete_duplicates.py

"""Tests for scitex_db._sqlite3._delete_duplicates.

Real SQLite collaborator under tmp_path — no mocks. Each test is
single-assert, AAA-marked, and named after the behaviour it verifies
(STX-TQ001/TQ002/TQ003/TQ005/TQ007 clean).
"""

import os
import shutil
import sqlite3
import sys
import tempfile

import pandas as pd
import pytest

pytest.importorskip("psycopg2")

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../src"))

from scitex_db import delete_duplicates  # Test backward compatibility
from scitex_db._sqlite3._delete_duplicates import (
    _delete_entry,
    _determine_columns,
    _fetch_as_df,
    _find_duplicated,
    _sort_db,
    verify_duplicated_index,
)


@pytest.fixture
def temp_dir():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)


@pytest.fixture
def db_path(temp_dir):
    return os.path.join(temp_dir, "test.db")


@pytest.fixture
def db_with_duplicates(db_path):
    """Create a SQLite db with three duplicates and yield its path."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL,
            data BLOB
        )
        """
    )
    data = [
        (1, "Alice", 100.0, b"data1"),
        (2, "Bob", 200.0, b"data2"),
        (3, "Alice", 100.0, b"data1"),
        (4, "Charlie", 300.0, b"data3"),
        (5, "Bob", 200.0, b"data2"),
        (6, "Alice", 100.0, b"data1"),
    ]
    cursor.executemany("INSERT INTO test_table VALUES (?, ?, ?, ?)", data)
    conn.commit()
    conn.close()
    yield db_path


# ----------------------------------------------------------------------------
# delete_duplicates — basic counts
# ----------------------------------------------------------------------------


def test_delete_duplicates_basic_reports_three_duplicates(db_with_duplicates):
    # Arrange
    target = db_with_duplicates
    # Act
    _, total_duplicates = delete_duplicates(
        target, "test_table", columns=["name", "value"], dry_run=False
    )
    # Assert
    assert total_duplicates == 3


def test_delete_duplicates_basic_leaves_three_rows(db_with_duplicates):
    # Arrange
    target = db_with_duplicates
    # Act
    delete_duplicates(
        target, "test_table", columns=["name", "value"], dry_run=False
    )
    conn = sqlite3.connect(target)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM test_table")
    count = cursor.fetchone()[0]
    conn.close()
    # Assert
    assert count == 3


def test_delete_duplicates_dry_run_preserves_row_count(db_with_duplicates):
    # Arrange
    target = db_with_duplicates
    conn = sqlite3.connect(target)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM test_table")
    initial_count = cursor.fetchone()[0]
    conn.close()
    # Act
    delete_duplicates(
        target, "test_table", columns=["name", "value"], dry_run=True
    )
    conn = sqlite3.connect(target)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM test_table")
    final_count = cursor.fetchone()[0]
    conn.close()
    # Assert
    assert final_count == initial_count


def test_delete_duplicates_all_columns_reports_three_duplicates(
    db_with_duplicates,
):
    # Arrange
    target = db_with_duplicates
    # Act
    _, total_duplicates = delete_duplicates(
        target, "test_table", columns="all", include_blob=True, dry_run=False
    )
    # Assert
    assert total_duplicates == 3


def test_delete_duplicates_exclude_blob_reports_three_duplicates(
    db_with_duplicates,
):
    # Arrange
    target = db_with_duplicates
    # Act
    _, total_duplicates = delete_duplicates(
        target,
        "test_table",
        columns="all",
        include_blob=False,
        dry_run=False,
    )
    # Assert
    assert total_duplicates == 3


# ----------------------------------------------------------------------------
# _sort_db
# ----------------------------------------------------------------------------


def test_sort_db_reorders_rows_alphabetically(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL
        )
        """
    )
    cursor.executemany(
        "INSERT INTO test_table VALUES (?, ?, ?)",
        [(1, "Charlie", 300.0), (2, "Alice", 100.0), (3, "Bob", 200.0)],
    )
    conn.commit()
    # Act
    _sort_db(cursor, "test_table", ["name"])
    conn.commit()
    cursor.execute("SELECT name FROM test_table")
    names = [row[0] for row in cursor.fetchall()]
    conn.close()
    # Assert
    assert names == ["Alice", "Bob", "Charlie"]


# ----------------------------------------------------------------------------
# _determine_columns
# ----------------------------------------------------------------------------


@pytest.fixture
def schema_only_db(db_path):
    """Empty DB with id/name/value/data schema; yield path."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL,
            data BLOB
        )
        """
    )
    conn.commit()
    conn.close()
    yield db_path


def test_determine_columns_all_excludes_primary_key(schema_only_db):
    # Arrange
    conn = sqlite3.connect(schema_only_db)
    cursor = conn.cursor()
    # Act
    columns = _determine_columns(
        cursor, "test_table", "all", include_blob=True
    )
    conn.close()
    # Assert
    assert "id" not in columns


def test_determine_columns_all_includes_blob_when_enabled(schema_only_db):
    # Arrange
    conn = sqlite3.connect(schema_only_db)
    cursor = conn.cursor()
    # Act
    columns = _determine_columns(
        cursor, "test_table", "all", include_blob=True
    )
    conn.close()
    # Assert
    assert "data" in columns


def test_determine_columns_excludes_blob_when_disabled(schema_only_db):
    # Arrange
    conn = sqlite3.connect(schema_only_db)
    cursor = conn.cursor()
    # Act
    columns = _determine_columns(
        cursor, "test_table", "all", include_blob=False
    )
    conn.close()
    # Assert
    assert "data" not in columns


def test_determine_columns_list_input_returns_same_list(schema_only_db):
    # Arrange
    conn = sqlite3.connect(schema_only_db)
    cursor = conn.cursor()
    # Act
    columns = _determine_columns(
        cursor, "test_table", ["name", "value"], include_blob=False
    )
    conn.close()
    # Assert
    assert columns == ["name", "value"]


def test_determine_columns_string_input_returns_one_item_list(schema_only_db):
    # Arrange
    conn = sqlite3.connect(schema_only_db)
    cursor = conn.cursor()
    # Act
    columns = _determine_columns(
        cursor, "test_table", "name", include_blob=False
    )
    conn.close()
    # Assert
    assert columns == ["name"]


# ----------------------------------------------------------------------------
# _fetch_as_df
# ----------------------------------------------------------------------------


def test_fetch_as_df_returns_dataframe_instance(db_with_duplicates):
    # Arrange
    conn = sqlite3.connect(db_with_duplicates)
    cursor = conn.cursor()
    # Act
    df = _fetch_as_df(cursor, ["name", "value"], "test_table")
    conn.close()
    # Assert
    assert isinstance(df, pd.DataFrame)


def test_fetch_as_df_returns_all_six_rows(db_with_duplicates):
    # Arrange
    conn = sqlite3.connect(db_with_duplicates)
    cursor = conn.cursor()
    # Act
    df = _fetch_as_df(cursor, ["name", "value"], "test_table")
    conn.close()
    # Assert
    assert len(df) == 6


def test_fetch_as_df_returns_requested_columns(db_with_duplicates):
    # Arrange
    conn = sqlite3.connect(db_with_duplicates)
    cursor = conn.cursor()
    # Act
    df = _fetch_as_df(cursor, ["name", "value"], "test_table")
    conn.close()
    # Assert
    assert list(df.columns) == ["name", "value"]


# ----------------------------------------------------------------------------
# _find_duplicated
# ----------------------------------------------------------------------------


def test_find_duplicated_returns_two_duplicate_rows():
    # Arrange
    df = pd.DataFrame(
        {
            "name": ["Alice", "Bob", "Alice", "Charlie", "Bob"],
            "value": [100, 200, 100, 300, 200],
        }
    )
    # Act
    duplicates = _find_duplicated(df)
    # Assert
    assert len(duplicates) == 2


# ----------------------------------------------------------------------------
# verify_duplicated_index
# ----------------------------------------------------------------------------


def test_verify_duplicated_index_flags_present_row_verified(db_with_duplicates):
    # Arrange
    conn = sqlite3.connect(db_with_duplicates)
    cursor = conn.cursor()
    duplicated_row = pd.Series({"name": "Alice", "value": 100.0})
    # Act
    _, is_verified = verify_duplicated_index(
        cursor, duplicated_row, "test_table", dry_run=False
    )
    conn.close()
    # Assert
    assert is_verified is True


def test_verify_duplicated_index_query_contains_where_clause(
    db_with_duplicates,
):
    # Arrange
    conn = sqlite3.connect(db_with_duplicates)
    cursor = conn.cursor()
    duplicated_row = pd.Series({"name": "Alice", "value": 100.0})
    # Act
    query, _ = verify_duplicated_index(
        cursor, duplicated_row, "test_table", dry_run=False
    )
    conn.close()
    # Assert
    assert "WHERE" in query


# ----------------------------------------------------------------------------
# _delete_entry
# ----------------------------------------------------------------------------


def test_delete_entry_decrements_matching_row_count(db_with_duplicates):
    # Arrange
    conn = sqlite3.connect(db_with_duplicates)
    cursor = conn.cursor()
    duplicated_row = pd.Series({"name": "Alice", "value": 100.0})
    cursor.execute(
        "SELECT COUNT(*) FROM test_table WHERE name='Alice' AND value=100.0"
    )
    initial_count = cursor.fetchone()[0]
    # Act
    _delete_entry(cursor, duplicated_row, "test_table", dry_run=False)
    conn.commit()
    cursor.execute(
        "SELECT COUNT(*) FROM test_table WHERE name='Alice' AND value=100.0"
    )
    final_count = cursor.fetchone()[0]
    conn.close()
    # Assert
    assert final_count == initial_count - 1


# ----------------------------------------------------------------------------
# delete_duplicates chunks + edge cases
# ----------------------------------------------------------------------------


def test_delete_duplicates_with_chunks_leaves_unique_rows_only(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL
        )
        """
    )
    rows = [
        (i, f"Person_{i % 20}", float(i % 10)) for i in range(100)
    ]
    cursor.executemany("INSERT INTO test_table VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    # Act
    delete_duplicates(
        db_path,
        "test_table",
        columns=["name", "value"],
        chunk_size=10,
        dry_run=False,
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT name || value) FROM test_table")
    unique_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM test_table")
    total_count = cursor.fetchone()[0]
    conn.close()
    # Assert
    assert total_count == unique_count


def test_delete_duplicates_missing_database_returns_none_tuple(temp_dir):
    # Arrange
    missing = os.path.join(temp_dir, "non_existent.db")
    # Act
    result = delete_duplicates(missing, "test_table", dry_run=False)
    # Assert
    assert result == (None, None)


def test_delete_duplicates_empty_table_returns_zero_processed(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    # Act
    total_processed, _ = delete_duplicates(
        db_path, "test_table", dry_run=False
    )
    # Assert
    assert total_processed == 0


def test_delete_duplicates_empty_table_returns_zero_duplicates(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    # Act
    _, total_duplicates = delete_duplicates(
        db_path, "test_table", dry_run=False
    )
    # Assert
    assert total_duplicates == 0


def test_delete_duplicates_no_duplicates_reports_zero(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL
        )
        """
    )
    cursor.executemany(
        "INSERT INTO test_table VALUES (?, ?, ?)",
        [(1, "Alice", 100.0), (2, "Bob", 200.0), (3, "Charlie", 300.0)],
    )
    conn.commit()
    conn.close()
    # Act
    _, total_duplicates = delete_duplicates(
        db_path, "test_table", columns=["name", "value"], dry_run=False
    )
    # Assert
    assert total_duplicates == 0


def test_delete_duplicates_no_duplicates_preserves_row_count(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT,
            value REAL
        )
        """
    )
    cursor.executemany(
        "INSERT INTO test_table VALUES (?, ?, ?)",
        [(1, "Alice", 100.0), (2, "Bob", 200.0), (3, "Charlie", 300.0)],
    )
    conn.commit()
    conn.close()
    # Act
    delete_duplicates(
        db_path, "test_table", columns=["name", "value"], dry_run=False
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM test_table")
    count = cursor.fetchone()[0]
    conn.close()
    # Assert
    assert count == 3


if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__)])
