#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that close() always leaves the object clean, including on failure.

The defect these cover: `close()` called `self.cursor.close()` outside its try
block, so a raising teardown aborted before the handles were nulled and the
object kept a DEAD connection. `__del__` then raised again.

The failure is provoked with a real closed connection rather than a stub -- the
same route a failing exit-commit takes.

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


@pytest.fixture
def after_a_failed_exit(path):
    """A handle whose exit-commit failed because the connection went away."""
    with SQLite3(path) as setup:
        setup.execute("CREATE TABLE t (a INTEGER)")
    handle = None
    with pytest.raises(sqlite3.Error):
        with SQLite3(path) as db:
            handle = db
            db.execute("INSERT INTO t VALUES (1)")
            db.conn.close()
    return handle


def test_a_failed_exit_leaves_no_connection_handle(after_a_failed_exit):
    # Was False: the object kept a handle to an already-closed database.
    # Arrange
    handle = after_a_failed_exit
    # Act
    conn = handle.conn
    # Assert
    assert conn is None


def test_a_failed_exit_leaves_no_cursor_handle(after_a_failed_exit):
    # Arrange
    handle = after_a_failed_exit
    # Act
    cursor = handle.cursor
    # Assert
    assert cursor is None


def test_close_is_idempotent_after_a_failed_exit(after_a_failed_exit):
    # __del__ calls close() again. Before the fix that raised a second time,
    # surfacing as "Exception ignored in SQLite3.__del__".
    # Arrange
    handle = after_a_failed_exit
    # Act
    handle.close()
    # Assert
    assert handle.conn is None


def test_a_later_context_still_works_after_a_failed_exit(path, after_a_failed_exit):
    # The practical consequence: the next user of this store is unaffected.
    # Arrange
    del after_a_failed_exit
    # Act
    with SQLite3(path) as db:
        db.execute("INSERT INTO t VALUES (2)")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    surviving = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    # Assert
    assert surviving == 1


# EOF
