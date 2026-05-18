#!/usr/bin/env python3
# Timestamp: "2026-05-18 (test-quality cleanup)"
# File: /tests/scitex/db/_sqlite3/test__SQLite3.py

"""Tests for the SQLite3 database manager.

Real-collaborator tests against an on-disk SQLite database — no mocks.
Each test exercises a single behaviour with one assertion in the
AAA-marker shape required by STX-TQ001/TQ002/TQ003/TQ007.
"""

import os
import shutil
import sqlite3
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../src"))

from scitex_db import SQLite3


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


# ----------------------------------------------------------------------------
# Initialization
# ----------------------------------------------------------------------------


def test_init_creates_database_file_on_disk(db_path):
    # Arrange
    target = db_path
    # Act
    with SQLite3(target):
        pass
    # Assert
    assert os.path.exists(target)


def test_init_records_supplied_db_path_attribute(db_path):
    # Arrange
    target = db_path
    # Act
    with SQLite3(target) as db:
        recorded = db.db_path
    # Assert
    assert recorded == target


def test_init_opens_connection_object_on_enter(db_path):
    # Arrange
    target = db_path
    # Act
    with SQLite3(target) as db:
        conn = db.conn
    # Assert
    assert conn is not None


def test_init_opens_cursor_object_on_enter(db_path):
    # Arrange
    target = db_path
    # Act
    with SQLite3(target) as db:
        cursor = db.cursor
    # Assert
    assert cursor is not None


def test_init_with_use_temp_keeps_connection_open(temp_dir):
    # Arrange
    original_path = os.path.join(temp_dir, "original.db")
    with SQLite3(original_path) as db1:
        db1.create_table("test", {"id": "INTEGER"})
    # Act
    with SQLite3(original_path, use_temp=True) as db2:
        conn = db2.conn
    # Assert
    assert conn is not None


# ----------------------------------------------------------------------------
# Context manager
# ----------------------------------------------------------------------------


def test_context_manager_clears_connection_after_exit(db_path):
    # Arrange
    target = db_path
    # Act
    with SQLite3(target) as db:
        pass
    # Assert
    assert db.conn is None


def test_context_manager_clears_cursor_after_exit(db_path):
    # Arrange
    target = db_path
    # Act
    with SQLite3(target) as db:
        pass
    # Assert
    assert db.cursor is None


def test_execute_outside_context_manager_raises_runtime_error(db_path):
    # Arrange
    db = SQLite3(db_path)
    ctx = pytest.raises(RuntimeError, match="must be used with context manager")
    # Act
    action = lambda: db.execute("SELECT 1")
    # Assert
    with ctx:
        action()
    db.close()


# ----------------------------------------------------------------------------
# __call__ / summary
# ----------------------------------------------------------------------------


def test_call_returns_summary_dict_of_tables(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        db.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)", ("test1", 1.5)
        )
        # Act
        summary = db(return_summary=True, print_summary=False)
    # Assert
    assert isinstance(summary, dict)


def test_call_summary_includes_created_table_name(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table("test_table", {"id": "INTEGER PRIMARY KEY"})
        # Act
        summary = db(return_summary=True, print_summary=False)
    # Assert
    assert "test_table" in summary


def test_summary_property_exists_on_db_instance(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table("test_table", {"id": "INTEGER PRIMARY KEY"})
        # Act
        has_summary = hasattr(db, "summary")
    # Assert
    assert has_summary


# ----------------------------------------------------------------------------
# create_table
# ----------------------------------------------------------------------------


def test_create_table_basic_lists_new_table(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "users",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "email": "TEXT"},
        )
        # Act
        tables = db.get_table_names()
    # Assert
    assert "users" in tables


def test_create_table_basic_schema_row_count(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "users",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "email": "TEXT"},
        )
        # Act
        schema = db.get_table_schema("users")
    # Assert
    assert len(schema) == 3


def test_create_table_with_blob_adds_dtype_column(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "images", {"id": "INTEGER PRIMARY KEY", "image_data": "BLOB"}
        )
        # Act
        schema = db.get_table_schema("images")
    # Assert
    assert "image_data_dtype" in schema["name"].values


def test_create_table_with_blob_adds_shape_column(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "images", {"id": "INTEGER PRIMARY KEY", "image_data": "BLOB"}
        )
        # Act
        schema = db.get_table_schema("images")
    # Assert
    assert "image_data_shape" in schema["name"].values


def test_create_table_if_not_exists_avoids_error(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table("test", {"id": "INTEGER"})
        # Act
        db.create_table("test", {"id": "INTEGER"}, if_not_exists=True)
        tables = db.get_table_names()
    # Assert
    assert "test" in tables


# ----------------------------------------------------------------------------
# drop_table
# ----------------------------------------------------------------------------


def test_drop_table_removes_table_from_listing(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table("test_table", {"id": "INTEGER PRIMARY KEY"})
        # Act
        db.drop_table("test_table")
        tables = db.get_table_names()
    # Assert
    assert "test_table" not in tables


# ----------------------------------------------------------------------------
# CRUD primitives
# ----------------------------------------------------------------------------


def test_insert_then_get_rows_returns_inserted_row(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        db.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)",
            ("test_item", 42.0),
        )
        # Act
        result = db.get_rows("test_table", where="name='test_item'")
    # Assert
    assert len(result) == 1


def test_update_changes_existing_value(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        db.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)",
            ("item", 42.0),
        )
        db.execute(
            "UPDATE test_table SET value = ? WHERE name = ?", (99.0, "item")
        )
        # Act
        result = db.get_rows("test_table", where="name='item'")
    # Assert
    assert result.iloc[0]["value"] == 99.0


def test_delete_removes_matching_row(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        db.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)", ("item", 1.0)
        )
        db.execute("DELETE FROM test_table WHERE name = ?", ("item",))
        # Act
        result = db.get_rows("test_table", where="name='item'")
    # Assert
    assert len(result) == 0


# ----------------------------------------------------------------------------
# Transactions
# ----------------------------------------------------------------------------


def test_transaction_commit_persists_inserted_row(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        with db.transaction():
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                ("transaction_test", 1.0),
            )
        # Act
        result = db.get_rows("test_table", where="name='transaction_test'")
    # Assert
    assert len(result) == 1


def test_transaction_rollback_discards_inserted_row(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        try:
            with db.transaction():
                db.execute(
                    "INSERT INTO test_table (name, value) VALUES (?, ?)",
                    ("rollback_test", 1.0),
                )
                raise RuntimeError("Test error")
        except RuntimeError:
            pass
        # Act
        result = db.get_rows("test_table", where="name='rollback_test'")
    # Assert
    assert len(result) == 0


# ----------------------------------------------------------------------------
# Batch operations
# ----------------------------------------------------------------------------


def test_insert_many_writes_all_rows_with_batching(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        rows = [{"name": f"item_{i}", "value": float(i)} for i in range(100)]
        db.insert_many("test_table", rows, batch_size=10)
        # Act
        count = db.get_row_count("test_table")
    # Assert
    assert count == 100


def test_update_many_returns_full_row_count(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        rows = [{"name": f"item_{i}", "value": 0.0} for i in range(10)]
        db.insert_many("test_table", rows)
        updates = [{"name": f"item_{i}", "value": float(i * 10)} for i in range(10)]
        db.update_many("test_table", updates, where="name = ?")
        # Act
        result = db.get_rows("test_table", order_by="name")
    # Assert
    assert len(result) == 10


# ----------------------------------------------------------------------------
# Array / BLOB round-trip
# ----------------------------------------------------------------------------


def test_save_array_load_array_preserves_dtype(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "data": "BLOB"},
        )
        arr = np.random.rand(10, 20).astype(np.float32)
        db.execute(
            "INSERT INTO test_table (id, name) VALUES (?, ?)", (1, "array_test")
        )
        db.save_array("test_table", arr, column="data", ids=1)
        # Act
        loaded = db.load_array("test_table", column="data", ids=1)
    # Assert
    assert loaded.dtype == arr.dtype


def test_save_array_load_array_preserves_shape_dim(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "data": "BLOB"},
        )
        arr = np.random.rand(10, 20).astype(np.float32)
        db.execute(
            "INSERT INTO test_table (id, name) VALUES (?, ?)", (1, "array_test")
        )
        db.save_array("test_table", arr, column="data", ids=1)
        # Act
        loaded = db.load_array("test_table", column="data", ids=1)
    # Assert
    assert loaded.shape == (1, 10, 20)


# ----------------------------------------------------------------------------
# Indexes
# ----------------------------------------------------------------------------


def test_create_unique_index_blocks_duplicate_inserts(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        db.create_index("test_table", ["name"], unique=True)
        db.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)",
            ("unique_name", 1.0),
        )
        ctx = pytest.raises(sqlite3.IntegrityError)
        # Act
        action = lambda: db.execute(
            "INSERT INTO test_table (name, value) VALUES (?, ?)",
            ("unique_name", 2.0),
        )
        # Assert
        with ctx:
            action()


# ----------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------


def test_get_table_schema_returns_dataframe_instance(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        # Act
        schema = db.get_table_schema("test_table")
    # Assert
    assert isinstance(schema, pd.DataFrame)


def test_get_table_schema_identifies_primary_key_row(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        schema = db.get_table_schema("test_table")
        # Act
        pk_rows = schema[schema["pk"] == 1]
    # Assert
    assert pk_rows.iloc[0]["name"] == "id"


def test_get_rows_filter_returns_expected_count(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        for i in range(20):
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                (f"item_{i}", float(i)),
            )
        # Act
        result = db.get_rows("test_table", where="value > 10")
    # Assert
    assert len(result) == 9


def test_get_rows_order_by_descending_picks_highest_value(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        for i in range(20):
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                (f"item_{i}", float(i)),
            )
        # Act
        result = db.get_rows("test_table", order_by="value DESC", limit=5)
    # Assert
    assert result.iloc[0]["value"] == 19.0


def test_get_rows_offset_limit_pagination_returns_window(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        for i in range(20):
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                (f"item_{i}", float(i)),
            )
        # Act
        result = db.get_rows("test_table", limit=5, offset=10)
    # Assert
    assert len(result) == 5


# ----------------------------------------------------------------------------
# Foreign keys
# ----------------------------------------------------------------------------


def test_foreign_key_violation_raises_integrity_error(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "departments", {"id": "INTEGER PRIMARY KEY", "name": "TEXT"}
        )
        db.create_table(
            "employees",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "dept_id": "INTEGER"},
            foreign_keys=[
                {
                    "tgt_column": "dept_id",
                    "src_table": "departments",
                    "src_column": "id",
                }
            ],
        )
        db.enable_foreign_keys()
        db.execute("INSERT INTO departments (id, name) VALUES (1, 'Engineering')")
        ctx = pytest.raises(sqlite3.IntegrityError)
        # Act
        action = lambda: db.execute(
            "INSERT INTO employees (name, dept_id) VALUES ('Jane', 999)"
        )
        # Assert
        with ctx:
            action()


# ----------------------------------------------------------------------------
# CSV import/export
# ----------------------------------------------------------------------------


def test_save_to_csv_creates_export_file(db_path, temp_dir):
    # Arrange
    csv_path = os.path.join(temp_dir, "export.csv")
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        for i in range(10):
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                (f"item_{i}", float(i)),
            )
        # Act
        db.save_to_csv("test_table", csv_path)
    # Assert
    assert os.path.exists(csv_path)


def test_load_from_csv_imports_full_row_count(db_path, temp_dir):
    # Arrange
    csv_path = os.path.join(temp_dir, "export.csv")
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        for i in range(10):
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                (f"item_{i}", float(i)),
            )
        db.save_to_csv("test_table", csv_path)
        db.create_table("imported_table", {"name": "TEXT", "value": "REAL"})
        db.load_from_csv("imported_table", csv_path)
        # Act
        imported_count = db.get_row_count("imported_table")
    # Assert
    assert imported_count == 10


# ----------------------------------------------------------------------------
# Maintenance
# ----------------------------------------------------------------------------


def test_vacuum_and_optimize_preserve_row_count(db_path):
    # Arrange
    with SQLite3(db_path) as db:
        db.create_table(
            "test_table",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        for i in range(100):
            db.execute(
                "INSERT INTO test_table (name, value) VALUES (?, ?)",
                (f"item_{i}", float(i)),
            )
        db.vacuum()
        db.optimize()
        # Act
        count = db.get_row_count("test_table")
    # Assert
    assert count == 100


# ----------------------------------------------------------------------------
# Mixin integration — split by mixin into single-assert tests
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    [
        "connect",
        "close",
        "reconnect",
        "execute",
        "executemany",
        "transaction",
        "begin",
        "commit",
        "rollback",
        "create_table",
        "drop_table",
        "get_table_names",
        "get_table_schema",
        "create_index",
        "drop_index",
        "get_rows",
        "get_row_count",
        "insert_many",
        "update_many",
        "delete_where",
        "save_array",
        "load_array",
        "load_from_csv",
        "save_to_csv",
        "vacuum",
        "optimize",
        "backup",
    ],
)
def test_sqlite3_exposes_mixin_method(method, db_path):
    # Arrange
    with SQLite3(db_path) as db:
        # Act
        present = hasattr(db, method)
    # Assert
    assert present


if __name__ == "__main__":
    pytest.main([os.path.abspath(__file__)])
