#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that leaving a context manager persists work instead of discarding it.

Every assertion here is made from a SEPARATE connection, deliberately. The
defect these cover was invisible from inside the block: `close()` issues an
explicit `conn.rollback()`, so with the default `autocommit=False` a write was
visible to every read in the same block and gone to everyone else. A test that
opened, wrote and asserted in one block would have passed against the bug.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._sqlite3._SQLite3 import SQLite3


@pytest.fixture
def path():
    tmpdir = tempfile.mkdtemp()
    yield os.path.join(tmpdir, "store.db")
    shutil.rmtree(tmpdir, ignore_errors=True)


def _count(db_path, table="t"):
    """Read from a FRESH connection -- the only reader that sees the truth."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_a_write_survives_leaving_the_context(path):
    # The reported defect: this used to be 0.
    # Arrange
    with SQLite3(path) as db:
        db.execute("CREATE TABLE t (a INTEGER)")
        db.execute("INSERT INTO t VALUES (1)")
    # Act
    surviving = _count(path)
    # Assert
    assert surviving == 1


def test_many_writes_survive_leaving_the_context(path):
    # Arrange
    with SQLite3(path) as db:
        db.execute("CREATE TABLE t (a INTEGER)")
        for value in range(5):
            db.execute("INSERT INTO t VALUES (?)", (value,))
    # Act
    surviving = _count(path)
    # Assert
    assert surviving == 5


@pytest.fixture
def after_a_failed_block(path):
    """A store whose context exited via an exception, mid-write.

    The raising happens here rather than in the test body so the test that
    inspects the aftermath carries exactly one assertion.
    """
    with SQLite3(path) as setup:
        setup.execute("CREATE TABLE t (a INTEGER)")
    with pytest.raises(RuntimeError):
        with SQLite3(path) as db:
            db.execute("INSERT INTO t VALUES (1)")
            raise RuntimeError("something went wrong mid-block")
    return path


def test_an_exception_inside_the_block_rolls_the_work_back(after_a_failed_block):
    # A half-applied write must not survive a failure. This is the reason
    # `__exit__` distinguishes the two exits rather than always committing.
    # Arrange
    db_path = after_a_failed_block
    # Act
    surviving = _count(db_path)
    # Assert
    assert surviving == 0


def test_the_original_exception_is_not_replaced_by_the_rollback(path):
    # If the exception on the way out were swallowed or substituted, the caller
    # would debug the database instead of their own bug.
    # Arrange
    with SQLite3(path) as setup:
        setup.execute("CREATE TABLE t (a INTEGER)")
    # Act
    raiser = SQLite3
    # Assert
    with pytest.raises(ValueError, match="caller's own error"):
        with raiser(path) as db:
            db.execute("INSERT INTO t VALUES (1)")
            raise ValueError("caller's own error")


def test_a_table_created_in_the_context_is_visible_afterwards(path):
    # A CONTROL, and it passed against the bug too -- which is the point.
    # sqlite3 commits implicitly before DDL, so CREATE TABLE survived while the
    # INSERTs after it were rolled away. The old failure was therefore
    # SELECTIVE: the schema persisted and the rows did not, leaving a store
    # that looks correctly initialised and is empty. That is a worse-looking
    # outcome than losing everything, because nothing about it reads as broken.
    # Arrange
    with SQLite3(path) as db:
        db.execute("CREATE TABLE t (a INTEGER)")
    # Act
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )]
    conn.close()
    # Assert
    assert "t" in names


# EOF
