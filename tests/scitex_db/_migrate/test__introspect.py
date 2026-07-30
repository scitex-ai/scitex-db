#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._introspect.

Real SQLite databases throughout — the point of introspection is what the engine
actually reports, so nothing here is stubbed. The keyset-paging tests use a
batch size smaller than the row count so page boundaries are genuinely crossed;
a batch larger than the table would exercise none of the paging logic while
looking like it did.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._introspect import (
    IntrospectionError,
    columns_with_nul,
    connect_readonly,
    list_tables,
    primary_key_columns,
    read_columns,
    read_rows,
    stored_types,
)


@pytest.fixture
def store():
    """A real SQLite store with two tables, a view, and an internal table."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "store.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tasks ("
        " id TEXT PRIMARY KEY,"
        " title TEXT NOT NULL,"
        " priority INTEGER,"
        " payload BLOB)"
    )
    conn.execute("CREATE TABLE notes (rowid_alias INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("CREATE VIEW open_tasks AS SELECT * FROM tasks")
    # An AUTOINCREMENT column makes SQLite create sqlite_sequence for us.
    conn.execute("CREATE TABLE seq (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    conn.execute("INSERT INTO seq (v) VALUES ('x')")
    conn.executemany(
        "INSERT INTO tasks (id, title, priority, payload) VALUES (?, ?, ?, ?)",
        [(f"t{i:02d}", f"title {i}", i, None) for i in range(10)],
    )
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
# connect_readonly
# ----------------------------------------------------------------------------


def test_connect_readonly_refuses_a_write(store):
    # Arrange -- the source of a migration must not be modifiable by it
    conn = connect_readonly(store)
    # Act
    statement = "INSERT INTO tasks (id, title) VALUES ('new', 'x')"
    # Assert
    with pytest.raises(sqlite3.OperationalError):
        conn.execute(statement)


def test_connect_readonly_yields_rows_addressable_by_name(store):
    # Arrange -- verification compares by column name, not position
    conn = connect_readonly(store)
    # Act
    row = conn.execute("SELECT id, title FROM tasks ORDER BY id LIMIT 1").fetchone()
    # Assert
    assert row["id"] == "t00"


# ----------------------------------------------------------------------------
# list_tables -- internals and views are store content's neighbours, not it
# ----------------------------------------------------------------------------


def test_list_tables_includes_real_tables(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    tables = list_tables(conn)
    # Assert
    assert "tasks" in tables


def test_list_tables_excludes_sqlite_internal_tables(store):
    # Arrange -- AUTOINCREMENT caused sqlite_sequence to exist
    conn = connect_readonly(store)
    # Act
    tables = list_tables(conn)
    # Assert
    assert not any(t.startswith("sqlite_") for t in tables)


def test_list_tables_excludes_views(store):
    # Arrange -- a view is derived data; copying it would duplicate rows
    conn = connect_readonly(store)
    # Act
    tables = list_tables(conn)
    # Assert
    assert "open_tasks" not in tables


def test_list_tables_is_sorted(store):
    # Arrange -- so a plan built from it is reproducible
    conn = connect_readonly(store)
    # Act
    tables = list_tables(conn)
    # Assert
    assert list(tables) == sorted(tables)


# ----------------------------------------------------------------------------
# read_columns
# ----------------------------------------------------------------------------


def test_read_columns_preserves_declaration_order(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    columns = read_columns(conn, "tasks")
    # Assert
    assert [c.name for c in columns] == ["id", "title", "priority", "payload"]


def test_read_columns_reports_the_declared_type(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    columns = read_columns(conn, "tasks")
    # Assert
    assert columns[2].declared_type == "INTEGER"


def test_read_columns_reports_not_null(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    columns = read_columns(conn, "tasks")
    # Assert
    assert columns[1].not_null is True


def test_read_columns_reports_the_primary_key(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    columns = read_columns(conn, "tasks")
    # Assert
    assert columns[0].primary_key is True


def test_read_columns_refuses_a_missing_table(store):
    # Arrange -- PRAGMA returns empty rather than failing, so this must be
    # distinguished from a table that genuinely has no columns
    conn = connect_readonly(store)
    # Act
    missing = "no_such_table"
    # Assert
    with pytest.raises(IntrospectionError, match="no such table"):
        read_columns(conn, missing)


# ----------------------------------------------------------------------------
# primary_key_columns
# ----------------------------------------------------------------------------


def test_primary_key_columns_finds_the_key(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    keys = primary_key_columns(read_columns(conn, "tasks"))
    # Assert
    assert keys == ("id",)


def test_primary_key_columns_returns_empty_when_there_is_none(store):
    # Arrange -- the caller must choose a key, not have one invented for it
    conn = connect_readonly(store)
    conn.close()
    columns = read_columns(connect_readonly(store), "tasks")
    keyless = tuple(
        type(c)(c.name, c.declared_type, c.not_null, False) for c in columns
    )
    # Act
    keys = primary_key_columns(keyless)
    # Assert
    assert keys == ()


# ----------------------------------------------------------------------------
# stored_types -- asks the rows, because metadata cannot answer
# ----------------------------------------------------------------------------


def test_stored_types_reports_the_storage_class_actually_present(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    types = stored_types(conn, "tasks", read_columns(conn, "tasks"))
    # Assert
    assert types["priority"] == ("integer",)


def test_stored_types_reports_null_for_an_all_null_column(store):
    # Arrange -- payload was inserted as NULL for every row
    conn = connect_readonly(store)
    # Act
    types = stored_types(conn, "tasks", read_columns(conn, "tasks"))
    # Assert
    assert types["payload"] == ("null",)


# ----------------------------------------------------------------------------
# read_rows -- keyset paging, tested across genuine page boundaries
# ----------------------------------------------------------------------------


def test_read_rows_returns_every_row_across_page_boundaries(store):
    # Arrange -- 10 rows, batch of 3, so boundaries are really crossed
    conn = connect_readonly(store)
    # Act
    rows = list(read_rows(conn, "tasks", ("id", "title"), ("id",), batch_size=3))
    # Assert
    assert len(rows) == 10


def test_read_rows_returns_no_duplicates_across_pages(store):
    # Arrange -- the failure mode that yields a right count and wrong contents
    conn = connect_readonly(store)
    # Act
    ids = [r["id"] for r in read_rows(conn, "tasks", ("id",), ("id",), batch_size=3)]
    # Assert
    assert len(set(ids)) == 10


def test_read_rows_yields_rows_in_key_order(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    ids = [r["id"] for r in read_rows(conn, "tasks", ("id",), ("id",), batch_size=4)]
    # Assert
    assert ids == sorted(ids)


def test_read_rows_handles_a_batch_larger_than_the_table(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    rows = list(read_rows(conn, "tasks", ("id",), ("id",), batch_size=1000))
    # Assert
    assert len(rows) == 10


def test_read_rows_handles_a_batch_size_of_one(store):
    # Arrange -- every row is its own page, so every boundary is exercised
    conn = connect_readonly(store)
    # Act
    rows = list(read_rows(conn, "tasks", ("id",), ("id",), batch_size=1))
    # Assert
    assert len(rows) == 10


def test_read_rows_returns_nothing_for_an_empty_table(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    rows = list(read_rows(conn, "notes", ("rowid_alias", "body"), ("rowid_alias",)))
    # Assert
    assert rows == []


def test_read_rows_refuses_without_key_columns(store):
    # Arrange -- there is deliberately no unordered mode
    conn = connect_readonly(store)
    # Act
    columns = ("id", "title")
    # Assert
    with pytest.raises(IntrospectionError, match="no key columns"):
        list(read_rows(conn, "tasks", columns, ()))


def test_read_rows_refuses_a_zero_batch_size(store):
    # Arrange
    conn = connect_readonly(store)
    # Act
    columns = ("id",)
    # Assert
    with pytest.raises(IntrospectionError, match="at least 1"):
        list(read_rows(conn, "tasks", columns, ("id",), batch_size=0))


# ----------------------------------------------------------------------------
# columns_with_nul -- the cross-backend NUL-byte incompatibility
# ----------------------------------------------------------------------------


@pytest.fixture
def nul_store():
    """A real store whose TEXT column holds a NUL byte, as SQLite permits."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "nul.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, body TEXT, n INTEGER)")
    conn.execute("INSERT INTO t VALUES ('clean', 'ordinary text', 1)")
    conn.execute("INSERT INTO t VALUES ('dirty', 'has a ' || char(0) || ' nul', 2)")
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_columns_with_nul_flags_a_text_column_holding_a_nul(nul_store):
    # Arrange -- SQLite stored it; PostgreSQL text will reject it
    conn = connect_readonly(nul_store)
    # Act
    result = columns_with_nul(conn, "t", read_columns(conn, "t"))
    # Assert
    assert result == ("body",)


def test_columns_with_nul_ignores_a_clean_text_column():
    # Arrange -- a store with no NUL anywhere
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "clean.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO t VALUES ('a', 'fine')")
    conn.commit()
    conn.close()
    ro = connect_readonly(path)
    # Act
    result = columns_with_nul(ro, "t", read_columns(ro, "t"))
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert result == ()


def test_columns_with_nul_does_not_scan_integer_columns(nul_store):
    # Arrange -- INTEGER affinity cannot hold a NUL, so it is not scanned
    conn = connect_readonly(nul_store)
    # Act
    result = columns_with_nul(conn, "t", read_columns(conn, "t"))
    # Assert
    assert "n" not in result


# EOF
