#!/usr/bin/env python3
# Timestamp: "2026-05-18 (test-quality cleanup)"
# File: /tests/scitex/db/test__inspect.py

"""Tests for scitex_db.inspect and OptimizedInspector.

Real-collaborator tests against a tmp_path SQLite database — no mocks.
Each test is single-assert, AAA-marked, and named after the behaviour
it verifies (STX-TQ001/TQ002/TQ003/TQ005/TQ007 clean).
"""

import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from scitex_db import inspect
from scitex_db._inspect import OptimizedInspector


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)


@pytest.fixture
def db_path(temp_dir):
    """Get a temporary database path."""
    return os.path.join(temp_dir, "test.db")


@pytest.fixture
def sample_db(db_path):
    """Create a sample database with two tables; yield the path."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            age INTEGER
        )
        """
    )
    users_data = [
        (1, "Alice", "alice@example.com", 30),
        (2, "Bob", "bob@example.com", 25),
        (3, "Charlie", "charlie@example.com", 35),
        (4, "David", "david@example.com", 28),
        (5, "Eve", "eve@example.com", 32),
    ]
    cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users_data)

    cursor.execute(
        """
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            product TEXT,
            price REAL,
            data BLOB,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    orders_data = [
        (1, 1, "Laptop", 999.99, b"binary_data_1"),
        (2, 1, "Mouse", 29.99, b"binary_data_2"),
        (3, 2, "Keyboard", 79.99, b"binary_data_3"),
        (4, 3, "Monitor", 299.99, b"binary_data_4"),
    ]
    cursor.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders_data)
    conn.commit()
    conn.close()
    yield db_path


@pytest.fixture
def simple_users_db(db_path):
    """Smaller two-row users database; yield the path."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE
        )
        """
    )
    cursor.executemany(
        "INSERT INTO users VALUES (?, ?, ?)",
        [(1, "Alice", "alice@example.com"), (2, "Bob", "bob@example.com")],
    )
    conn.commit()
    conn.close()
    yield db_path


# ----------------------------------------------------------------------------
# OptimizedInspector — init
# ----------------------------------------------------------------------------


def test_inspector_init_records_db_path_attribute(sample_db):
    # Arrange
    target = sample_db
    # Act
    inspector = OptimizedInspector(target)
    recorded = inspector.db_path
    inspector.close()
    # Assert
    assert recorded == target


def test_inspector_init_missing_file_raises_filenotfound(temp_dir):
    # Arrange
    missing = os.path.join(temp_dir, "nonexistent.db")
    ctx = pytest.raises(FileNotFoundError)
    # Act
    action = lambda: OptimizedInspector(missing)
    # Assert
    with ctx:
        action()


def test_inspector_context_manager_returns_table_listing(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        tables = inspector.get_table_names()
    # Assert
    assert len(tables) >= 2


# ----------------------------------------------------------------------------
# OptimizedInspector — get_table_names
# ----------------------------------------------------------------------------


def test_get_table_names_lists_users_table(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        tables = inspector.get_table_names()
    # Assert
    assert "users" in tables


def test_get_table_names_lists_orders_table(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        tables = inspector.get_table_names()
    # Assert
    assert "orders" in tables


# ----------------------------------------------------------------------------
# OptimizedInspector — get_table_info_batch
# ----------------------------------------------------------------------------


def test_get_table_info_batch_keys_by_requested_table(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        info = inspector.get_table_info_batch(["users"])
    # Assert
    assert "users" in info


def test_get_table_info_batch_returns_all_four_columns(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        info = inspector.get_table_info_batch(["users"])
    # Assert
    assert len(info["users"]) == 4


def test_get_table_info_batch_marks_id_column_pk(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        info = inspector.get_table_info_batch(["users"])
        id_col = [c for c in info["users"] if c["name"] == "id"][0]
    # Assert
    assert id_col["pk"] is True


# ----------------------------------------------------------------------------
# OptimizedInspector — get_table_stats_batch
# ----------------------------------------------------------------------------


def test_get_table_stats_batch_returns_full_row_count(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        stats = inspector.get_table_stats_batch(["users"], sample_size=3)
    # Assert
    assert stats["users"]["row_count"] == 5


def test_get_table_stats_batch_respects_sample_size_limit(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        stats = inspector.get_table_stats_batch(["users"], sample_size=3)
    # Assert
    assert len(stats["users"]["sample_data"]) == 3


def test_get_table_stats_batch_skip_count_flags_row_count(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        stats = inspector.get_table_stats_batch(["users"], skip_count=True)
    # Assert
    assert stats["users"]["row_count"] == "Not counted"


# ----------------------------------------------------------------------------
# OptimizedInspector — inspect_fast
# ----------------------------------------------------------------------------


def test_inspect_fast_returns_one_result_per_table(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        results = inspector.inspect_fast(verbose=False)
    # Assert
    assert len(results) >= 2


def test_inspect_fast_specific_tables_returns_one_record(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        results = inspector.inspect_fast(table_names=["users"], verbose=False)
    # Assert
    assert len(results) == 1


def test_inspect_fast_specific_tables_counts_users_rows(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        results = inspector.inspect_fast(table_names=["users"], verbose=False)
    # Assert
    assert results[0]["row_count"] == 5


def test_inspect_fast_skip_blob_returns_one_record(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        results = inspector.inspect_fast(
            table_names=["orders"], verbose=False, skip_blob_content=True
        )
    # Assert
    assert len(results) == 1


def test_inspect_fast_skip_blob_uses_placeholder_for_blob(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        results = inspector.inspect_fast(
            table_names=["orders"], verbose=False, skip_blob_content=True
        )
        first_row = (
            results[0]["sample_data"][0] if results[0]["sample_data"] else {}
        )
    # Assert
    assert "<BLOB" in first_row.get("data", "")


def test_inspect_fast_with_blob_content_returns_bytes(sample_db):
    # Arrange
    target = sample_db
    # Act
    with OptimizedInspector(target) as inspector:
        results = inspector.inspect_fast(
            table_names=["orders"], verbose=False, skip_blob_content=False
        )
        first_row = (
            results[0]["sample_data"][0] if results[0]["sample_data"] else {}
        )
    # Assert
    assert isinstance(first_row.get("data"), bytes)


# ----------------------------------------------------------------------------
# inspect() — module-level function
# ----------------------------------------------------------------------------


def test_inspect_basic_returns_at_least_one_result(simple_users_db):
    # Arrange
    target = simple_users_db
    # Act
    results = inspect(target, verbose=False)
    # Assert
    assert len(results) >= 1


def test_inspect_basic_counts_two_user_rows(simple_users_db):
    # Arrange
    target = simple_users_db
    # Act
    results = inspect(target, verbose=False)
    # Assert
    assert results[0]["row_count"] == 2


def test_inspect_verbose_writes_table_name_to_stdout(simple_users_db, capsys):
    # Arrange
    target = simple_users_db
    # Act
    inspect(target, verbose=True)
    captured = capsys.readouterr()
    # Assert
    assert "users" in captured.out


def test_inspect_specific_tables_returns_single_table(simple_users_db):
    # Arrange
    target = simple_users_db
    # Act
    results = inspect(target, table_names=["users"], verbose=False)
    # Assert
    assert len(results) == 1


def test_inspect_skip_count_returns_not_counted_marker(simple_users_db):
    # Arrange
    target = simple_users_db
    # Act
    results = inspect(target, skip_count=True, verbose=False)
    # Assert
    assert results[0]["row_count"] == "Not counted"


def test_inspect_empty_database_returns_empty_results(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    conn.close()
    # Act
    results = inspect(db_path, verbose=False)
    # Assert
    assert len(results) == 0


def test_inspect_empty_table_reports_zero_rows(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE empty_table (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()
    # Act
    results = inspect(db_path, verbose=False)
    # Assert
    assert results[0]["row_count"] == 0


def test_inspect_complex_schema_reports_five_columns(db_path):
    # Arrange
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE complex_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            score REAL CHECK(score >= 0 AND score <= 100)
        )
        """
    )
    cursor.execute(
        "INSERT INTO complex_table (name, score) VALUES (?, ?)", ("Test", 85.5)
    )
    conn.commit()
    conn.close()
    # Act
    results = inspect(db_path, table_names=["complex_table"], verbose=False)
    # Assert
    assert len(results[0]["columns"]) == 5


def test_inspect_nonexistent_db_raises_filenotfound(temp_dir):
    # Arrange
    missing = os.path.join(temp_dir, "nonexistent.db")
    ctx = pytest.raises(FileNotFoundError)
    # Act
    action = lambda: inspect(missing)
    # Assert
    with ctx:
        action()


if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__)])
