#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the read/write classification in _QueryMixin.

This function is the single source of truth for two things at once: the
read-only guard and observer dispatch. So a misclassification does not merely
refuse a query -- it also announces a write that never happened to every
post-save observer.

The cases that matter are the ones where the SQL CONTAINS a write keyword
without BEING a write: a column named `created_at`, a `LIKE '%dropped%'`
predicate, a comment, a string literal. Those are the real reports, measured
against the live scitex-cards schema.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import pytest

from scitex_db._sqlite3._SQLite3Mixins._QueryMixin import (
    _is_write_query,
    _script_is_write,
)

# ----------------------------------------------------------------------------
# Reads that CONTAIN a write keyword -- the reported defect
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT created_at FROM tasks",
        "SELECT id, updated_at FROM tasks WHERE deleted_at IS NULL",
        "SELECT * FROM t WHERE note LIKE '%dropped%'",
        "SELECT * FROM t WHERE body = 'INSERT INTO evil'",
        "-- CREATE TABLE in a comment\nSELECT 1",
        "/* DROP */ SELECT 1",
        'SELECT "deleted_at" FROM t',
    ],
)
def test_a_select_containing_a_write_keyword_is_a_read(sql):
    # scitex-cards has 171 occurrences of created_at/updated_at/deleted_at, so
    # this was refusing a large fraction of their ordinary reads.
    # Arrange
    query = sql
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is False


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT key, value FROM schema_meta",
        "SELECT COUNT(*) FROM tasks",
        "  \n  select lower(x) from t",
        "PRAGMA table_info('tasks')",
        "EXPLAIN QUERY PLAN SELECT 1",
    ],
)
def test_an_ordinary_read_is_a_read(sql):
    # The controls: the old check got these right too, so a fix that only
    # made everything a read would pass the tests above and fail here.
    # Arrange
    query = sql
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is False


# ----------------------------------------------------------------------------
# Writes must still be writes -- the direction that protects the data
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO tasks VALUES (1)",
        "update tasks set a = 1",
        "DELETE FROM t",
        "CREATE TABLE t (a)",
        "ALTER TABLE t ADD COLUMN b",
        "DROP TABLE t",
        "REPLACE INTO t VALUES (1)",
        "VACUUM",
    ],
)
def test_a_write_is_a_write(sql):
    # Arrange
    query = sql
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is True


def test_an_unrecognised_statement_counts_as_a_write():
    # The two errors are not symmetric. Calling an unknown statement a read
    # would let it past the read-only guard AND fire the wrong observer;
    # calling it a write costs one unnecessary refusal.
    # Arrange
    query = "FROBNICATE tasks"
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is True


# ----------------------------------------------------------------------------
# WITH -- a CTE can precede either kind, so it must be resolved not guessed
# ----------------------------------------------------------------------------


def test_a_cte_ending_in_select_is_a_read():
    # Arrange
    query = "WITH x AS (SELECT 1) SELECT * FROM x"
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is False


def test_a_cte_ending_in_insert_is_a_write():
    # Leading-keyword alone would say "WITH" and miss this.
    # Arrange
    query = "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x"
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is True


def test_a_write_keyword_inside_a_cte_literal_does_not_make_it_a_write():
    # Arrange
    query = "WITH x AS (SELECT 'INSERT') SELECT * FROM x"
    # Act
    is_write = _is_write_query(query)
    # Assert
    assert is_write is False


# ----------------------------------------------------------------------------
# Scripts -- where the leading keyword is NOT sufficient
# ----------------------------------------------------------------------------


def test_a_script_whose_first_statement_reads_but_later_one_writes():
    # This is the case where the leading-keyword fix would have been LESS safe
    # than the substring check it replaced, if scripts were not handled apart.
    # Arrange
    script = "SELECT 1; DROP TABLE t;"
    # Act
    is_write = _script_is_write(script)
    # Assert
    assert is_write is True


def test_a_script_of_only_reads_is_a_read():
    # Arrange
    script = "SELECT 1; SELECT 2;"
    # Act
    is_write = _script_is_write(script)
    # Assert
    assert is_write is False


def test_a_semicolon_inside_a_trigger_body_does_not_split_the_statement():
    # This store's append-only guards are trigger bodies full of semicolons,
    # so splitting naively would classify fragments instead of statements.
    # Arrange
    script = (
        "CREATE TRIGGER g BEFORE DELETE ON t "
        "BEGIN SELECT RAISE(ABORT, ';no;'); END;"
    )
    # Act
    is_write = _script_is_write(script)
    # Assert
    assert is_write is True


# EOF


# ----------------------------------------------------------------------------
# Exception preservation -- the half that actually blocks a caller
# ----------------------------------------------------------------------------


import os
import shutil
import sqlite3
import tempfile

from scitex_db._sqlite3._SQLite3 import SQLite3


@pytest.fixture
def db():
    """A real SQLite3 handle, opened the way the class requires.

    `SQLite3` refuses to execute outside a context manager, so the fixture
    enters one -- the failure otherwise is a RuntimeError about lifecycle,
    which would mask the exception-class behaviour these tests are about.
    """
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "store.db")
    with SQLite3(path) as handle:
        yield handle
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_a_missing_table_still_raises_operational_error(db):
    # scitex-cards catches OperationalError specifically to mean "this store
    # has no schema_meta yet". Wrapping it in the base sqlite3.Error made that
    # catch stop matching, turning a routine absent-table case into an
    # unhandled error.
    # Arrange
    query = "SELECT key FROM schema_meta"
    # Act
    execute = db.execute
    # Assert
    with pytest.raises(sqlite3.OperationalError):
        execute(query)


def test_execute_returns_a_cursor_so_reads_can_be_fetched(db):
    # The annotation said `-> None` while the body returned the cursor, which
    # made ordinary DB-API usage look unsupported to anyone reading it.
    # Arrange
    db.execute("CREATE TABLE t (a INTEGER)")
    db.execute("INSERT INTO t VALUES (7)")
    # Act
    row = db.execute("SELECT a FROM t").fetchone()
    # Assert
    assert row[0] == 7


# EOF
