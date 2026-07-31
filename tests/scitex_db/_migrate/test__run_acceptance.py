#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that migrate() proves the destination ACCEPTS carried objects.

The defect: the preflight classified a schema object as `carried` because the
translator PRODUCED output, and nothing ever asked the destination whether that
output was valid for it. On 2026-07-31 a trigger with a subquery in its WHEN
clause translated cleanly, PostgreSQL refused it outright, and the refusal
arrived in `apply_schema_objects` -- after 21,792 rows had been written. The
destination had to be dropped and rebuilt.

THE REJECTION HERE IS REAL, NOT SIMULATED. A translated trigger is plpgsql, and
a SQLite destination genuinely cannot execute it. So the source carries a
trigger, the preflight carries it, and the destination refuses it for its own
reasons -- the same code path as the PostgreSQL failure, with a real database
doing the refusing.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._copy import (
    MARKER_TABLE,
    MigrationRefused,
    Quiescence,
    StoreScope,
)
from scitex_db._migrate._plan import Disposition, TablePlan
from scitex_db._migrate._run import Destination, migrate

DISPOSITIONS = {"tasks": TablePlan("tasks", Disposition.MIGRATE)}
QUIET = Quiescence(mechanism="operator", stated_by="test")
WHOLE = StoreScope(database_is_whole_store=True, stated_by="test")


@pytest.fixture
def workspace():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def _source(tmpdir, *, with_trigger):
    """A store with rows, an index, and optionally an untranslatable guard."""
    path = os.path.join(tmpdir, "source.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("CREATE INDEX idx_tasks_title ON tasks(title)")
    if with_trigger:
        conn.execute(
            "CREATE TRIGGER tasks_no_delete BEFORE DELETE ON tasks "
            "BEGIN SELECT RAISE(ABORT, 'tasks are append-only'); END"
        )
    conn.executemany(
        "INSERT INTO tasks (id, title) VALUES (?, ?)",
        [(f"t{i}", f"title {i}") for i in range(25)],
    )
    conn.commit()
    conn.close()
    return path


def _destination(conn):
    def execute(sql, params):
        conn.execute(sql, params)

    def executemany(sql, rows):
        conn.executemany(sql, rows)

    def fetch(sql):
        return conn.execute(sql).fetchall()

    def read_table(table, columns, key_columns):
        select = ", ".join(f'"{c}"' for c in columns)
        order = ", ".join(f'"{k}"' for k in key_columns)
        return [
            dict(r)
            for r in conn.execute(
                f'SELECT {select} FROM "{table}" ORDER BY {order}'
            ).fetchall()
        ]

    return Destination(
        execute=execute,
        fetch=fetch,
        read_table=read_table,
        placeholder="?",
        executemany=executemany,
    )


def _run(tmpdir, *, with_trigger):
    dest_path = os.path.join(tmpdir, "dest.db")
    conn = sqlite3.connect(dest_path)
    conn.row_factory = sqlite3.Row
    try:
        migrate(
            _source(tmpdir, with_trigger=with_trigger),
            _destination(conn),
            QUIET,
            source_identity="test",
            completed_at="2026-07-31T00:00:00Z",
            store_identity="test-store",
            store_scope=WHOLE,
            dispositions=DISPOSITIONS,
        )
        # COMMIT before closing, or the assertions read an empty database and
        # blame the code under test. `sqlite3.Connection.close()` discards an
        # open transaction, so every row this migration wrote would vanish at
        # teardown and a correct run would look like a total failure. The
        # positive control below caught exactly that, which is the second time
        # this shape has cost us a wrong diagnosis.
        conn.commit()
    finally:
        conn.close()
    return dest_path


@pytest.fixture
def rejected(workspace):
    """The refusal raised when the destination cannot accept a carried object."""
    with pytest.raises(MigrationRefused) as caught:
        _run(workspace, with_trigger=True)
    return caught.value, os.path.join(workspace, "dest.db")


def test_a_rejected_object_refuses_the_migration(rejected):
    # Arrange
    error, _ = rejected
    # Act
    message = str(error)
    # Assert
    assert "REJECTED schema object" in message


def test_the_refusal_names_the_rejected_object(rejected):
    # A refusal that does not say WHICH object leaves the reader to bisect.
    # Arrange
    error, _ = rejected
    # Act
    message = str(error)
    # Assert
    assert "tasks_no_delete" in message


def test_the_refusal_offers_the_two_honest_outcomes(rejected):
    # Arrange
    error, _ = rejected
    # Act
    message = str(error)
    # Assert
    assert "excluded_objects" in message


def test_no_rows_are_copied_when_an_object_is_rejected(rejected):
    # THE POINT OF THE WHOLE CHANGE: the old code found this out after the copy.
    # Arrange
    _, dest_path = rejected
    conn = sqlite3.connect(dest_path)
    # Act
    copied = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    # Assert
    assert copied == 0


def test_no_marker_is_written_when_an_object_is_rejected(rejected):
    # Arrange
    _, dest_path = rejected
    conn = sqlite3.connect(dest_path)
    # Act
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (MARKER_TABLE,),
    ).fetchall()
    conn.close()
    # Assert
    assert tables == []


def test_a_clean_run_still_copies_every_row(workspace):
    # POSITIVE CONTROL. The probe runs inside a SAVEPOINT because a plain
    # rollback would discard the just-created, still-uncommitted tables. If it
    # ever regresses to `reset()`, this is the test that fails -- and without it
    # a check that refuses everything looks identical to one that works.
    # Arrange
    dest_path = _run(workspace, with_trigger=False)
    conn = sqlite3.connect(dest_path)
    # Act
    copied = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    # Assert
    assert copied == 25


def test_a_clean_run_still_applies_the_carried_index(workspace):
    # The probe must undo itself WITHOUT undoing the real application later.
    # Arrange
    dest_path = _run(workspace, with_trigger=False)
    conn = sqlite3.connect(dest_path)
    # Act
    indexes = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    ]
    conn.close()
    # Assert
    assert "idx_tasks_title" in indexes

# EOF
