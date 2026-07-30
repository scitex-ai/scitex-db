#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._run.

Real SQLite on both sides. The destination is a genuine database file that the
rows are genuinely written into and genuinely read back out of -- the adapters
here supply the driver's callables, they do not stand in for the database.

ONE LIMIT, STATED RATHER THAN WORKED AROUND: a translated TRIGGER is plpgsql and
only PostgreSQL can execute it, so the schema-object composition is exercised
here with an INDEX, whose translated form runs on both engines. Trigger
translation itself is covered by test__triggers.py, and the wiring under test
here -- that schema objects are applied at all, and applied after the rows --
is the same code path for both kinds.

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
    destination_is_usable,
)
from scitex_db._migrate._plan import Disposition, TablePlan
from scitex_db._migrate._run import Destination, migrate

DISPOSITIONS = {
    "tasks": TablePlan("tasks", Disposition.MIGRATE),
    "messages": TablePlan("messages", Disposition.MIGRATE),
    "vacant": TablePlan("vacant", Disposition.MIGRATE),
    "mirror_hashes": TablePlan(
        "mirror_hashes", Disposition.EXCLUDE, "YAML-mirror bookkeeping"
    ),
}

QUIET = Quiescence(mechanism="operator", stated_by="test")
WHOLE = StoreScope(database_is_whole_store=True, stated_by="test")


@pytest.fixture
def workspace():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_source(tmpdir, *, nul=False, name="source.db"):
    """A store shaped like the card store: keys, an empty table, an exclusion.

    `revision` is present because carrying it verbatim is the whole reason the
    entry point could not be written until scitex-cards' column landed.
    """
    path = os.path.join(tmpdir, name)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tasks ("
        "  id TEXT PRIMARY KEY,"
        "  title TEXT,"
        "  revision INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, body TEXT)")
    conn.execute("CREATE TABLE vacant (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE mirror_hashes (path TEXT PRIMARY KEY, digest TEXT)")
    conn.execute("CREATE INDEX idx_tasks_title ON tasks (title)")
    conn.execute("INSERT INTO tasks VALUES ('t1', 'first', 4)")
    conn.execute("INSERT INTO tasks VALUES ('t2', 'second', 9)")
    body = "hello" if not nul else "with " + chr(0) + " nul"
    conn.execute("INSERT INTO messages VALUES (?, ?)", ("m1", body))
    conn.execute("INSERT INTO mirror_hashes VALUES ('p', 'd')")
    conn.commit()
    conn.close()
    return path


def _open_destination(tmpdir, name="dest.db"):
    conn = sqlite3.connect(os.path.join(tmpdir, name))
    conn.row_factory = sqlite3.Row
    return conn


def _destination(conn, log=None):
    """Driver callables for a real SQLite destination, optionally recording SQL.

    The log records the statements in the order they were issued, which is how
    the ordering rules (rows before schema objects, marker last) are asserted --
    those rules are about sequence, and a final-state check cannot see sequence.
    """

    def execute(sql, params):
        if log is not None:
            log.append(sql)
        conn.execute(sql, params)

    def executemany(sql, rows):
        if log is not None:
            log.append(sql)
        conn.executemany(sql, rows)

    def fetch(sql):
        return conn.execute(sql).fetchall()

    def read_table(table, columns, key_columns):
        select = ", ".join(f'"{c}"' for c in columns)
        order = ", ".join(f'"{k}"' for k in key_columns)
        rows = conn.execute(
            f'SELECT {select} FROM "{table}" ORDER BY {order}'
        ).fetchall()
        return [dict(r) for r in rows]

    return Destination(
        execute=execute,
        fetch=fetch,
        read_table=read_table,
        executemany=executemany,
    )


def _corrupting_destination(conn, column, wrong_value):
    """A real destination reached through an adapter that alters one column.

    Not a stub: the rows land in a real SQLite file and are read back from it.
    Only the value in transit is changed, which is the shape of a driver-level
    coercion -- precisely the failure that keeping `revision` inside the
    checksummed set exists to catch, and one that a row COUNT cannot see.
    """
    base = _destination(conn)

    def _rewrite(sql, rows):
        names = [
            n.strip().strip('"')
            for n in sql[sql.index("(") + 1 : sql.index(")")].split(",")
        ]
        if column not in names:
            return rows
        i = names.index(column)
        return [
            tuple(wrong_value if j == i else v for j, v in enumerate(row))
            for row in rows
        ]

    return Destination(
        execute=base.execute,
        fetch=base.fetch,
        read_table=base.read_table,
        executemany=lambda sql, rows: base.executemany(sql, _rewrite(sql, rows)),
    )


def _run(source, destination):
    return migrate(
        source,
        destination,
        QUIET,
        source_identity="test-store",
        completed_at="2026-07-30T00:00:00Z",
        store_identity=None,
        store_scope=WHOLE,
        dispositions=DISPOSITIONS,
    )


# ----------------------------------------------------------------------------
# The happy path -- every row moved, verified, and marked
# ----------------------------------------------------------------------------


def test_migrate_reports_the_rows_it_actually_inserted(workspace):
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert report.rows_copied["tasks"] == 2


def test_migrate_marks_the_destination_complete(workspace):
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert report.result.marked_complete is True


def test_migrate_run_is_ok_when_every_table_verifies(workspace):
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert report.ok is True


def test_migrate_carries_the_row_values_across(workspace):
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    _run(source, _destination(conn))
    # Assert
    assert conn.execute("SELECT title FROM tasks WHERE id='t1'").fetchone()[0] == "first"


def test_migrate_verifies_an_empty_table_rather_than_refusing_it(workspace):
    # An empty table is legitimate, but the verifier refuses an empty comparison
    # unless told the table is genuinely empty -- so the entry point has to pass
    # the preflight's `empty_tables` through. Without that this run raises.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert report.rows_copied["vacant"] == 0


def test_migrate_leaves_excluded_tables_behind(workspace):
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    _run(source, _destination(conn))
    # Assert
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='mirror_hashes'"
        ).fetchone()[0]
        == 0
    )


def test_migrate_names_the_exclusion_in_its_summary(workspace):
    # An exclusion that is not reported reads as a complete copy.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert "mirror_hashes: NOT MIGRATED" in report.summary()


# ----------------------------------------------------------------------------
# Ordering -- the rules that make an interrupted run safe
# ----------------------------------------------------------------------------


def test_migrate_writes_the_completion_marker_last(workspace):
    # The marker asserts "this was checked". Anything issued after it would be
    # work the marker already claimed was finished.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    log = []
    # Act
    _run(source, _destination(conn, log))
    # Assert
    assert MARKER_TABLE in log[-1]


def test_migrate_applies_schema_objects_after_the_rows(workspace):
    # Building an index over a populated table is cheaper, and a guard trigger
    # installed early would be adjudicating the copier rather than the app.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    log = []
    # Act
    _run(source, _destination(conn, log))
    # Assert
    # The marker's own INSERT is excluded: it is written last by design, so
    # counting it here would compare the index against the marker rather than
    # against the rows.
    assert next(i for i, s in enumerate(log) if "CREATE INDEX" in s) > max(
        i
        for i, s in enumerate(log)
        if s.startswith("INSERT INTO") and MARKER_TABLE not in s
    )


def test_migrate_creates_the_source_index_on_the_destination(workspace):
    # The inherited defect: schema objects were translated but never applied.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    _run(source, _destination(conn))
    # Assert
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='index' AND name='idx_tasks_title'"
        ).fetchone()[0]
        == 1
    )


def test_migrate_reports_the_schema_objects_it_applied(workspace):
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert report.applied_objects == ("idx_tasks_title",)


# ----------------------------------------------------------------------------
# Refusals -- and, more importantly, that a refusal writes nothing
# ----------------------------------------------------------------------------


@pytest.fixture
def refused_destination(workspace):
    """A destination the migration refused to touch, because of a NUL byte.

    The refusal happens here rather than in the test body so the test that
    inspects the aftermath carries exactly one assertion.
    """
    source = _make_source(workspace, nul=True)
    conn = _open_destination(workspace)
    with pytest.raises(MigrationRefused):
        _run(source, _destination(conn))
    return conn


def test_migrate_refuses_when_the_preflight_is_not_ready(workspace):
    # Arrange
    source = _make_source(workspace, nul=True)
    destination = _destination(_open_destination(workspace))
    # Act
    run = _run
    # Assert
    with pytest.raises(MigrationRefused, match="NOT READY"):
        run(source, destination)


def test_migrate_writes_nothing_when_the_preflight_refuses(refused_destination):
    # The refusal has to come BEFORE any write. A run that created the tables
    # and then refused would leave a destination that looks initialised.
    # Arrange
    conn = refused_destination
    # Act
    objects = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
    # Assert
    assert objects == 0


def test_migrate_refuses_a_destination_that_is_already_marked(workspace):
    # Copying into a finished destination would insert every row a second time.
    # Arrange
    source = _make_source(workspace)
    destination = _destination(_open_destination(workspace))
    _run(source, destination)
    # Act
    run = _run
    # Assert
    with pytest.raises(MigrationRefused, match="already carries a completion marker"):
        run(source, destination)


# ----------------------------------------------------------------------------
# `revision` is inside the checksummed set -- the reason this waited on #650
# ----------------------------------------------------------------------------


@pytest.fixture
def failed_verification(workspace):
    """A run whose destination stored the wrong `revision`, already refused."""
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    destination = _corrupting_destination(conn, "revision", 0)
    with pytest.raises(MigrationRefused):
        _run(source, destination)
    return destination


def test_migrate_detects_a_revision_that_arrived_wrong(workspace):
    # A wrong `revision` leaves scitex-cards' optimistic lock FUNCTIONING while
    # comparing against the wrong number -- so it must fail verification, not
    # merely be copied. Row counts are identical here; only the value differs.
    # Arrange
    source = _make_source(workspace)
    destination = _corrupting_destination(_open_destination(workspace), "revision", 0)
    # Act
    run = _run
    # Assert
    with pytest.raises(MigrationRefused, match="tasks"):
        run(source, destination)


def test_migrate_leaves_no_marker_when_verification_fails(failed_verification):
    # An unverified destination must not be servable. No marker is what makes it
    # unusable, rather than silently wrong.
    # Arrange
    destination = failed_verification
    # Act
    usable = destination_is_usable(destination.fetch)
    # Assert
    assert usable is False


# ----------------------------------------------------------------------------
# The Destination adapter itself
# ----------------------------------------------------------------------------


def test_write_many_falls_back_to_execute_without_a_batch_path(workspace):
    # `executemany` is optional so the minimal adapter is three callables; the
    # fallback has to actually write, not silently do nothing.
    # Arrange
    conn = _open_destination(workspace)
    conn.execute("CREATE TABLE t (a TEXT)")
    destination = Destination(
        execute=lambda sql, params: conn.execute(sql, params),
        fetch=lambda sql: conn.execute(sql).fetchall(),
        read_table=lambda table, columns, keys: [],
    )
    # Act
    destination.write_many("INSERT INTO t (a) VALUES (?)", [("x",), ("y",)])
    # Assert
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2


# ----------------------------------------------------------------------------
# `reset` -- the hook PostgreSQL cannot migrate without
# ----------------------------------------------------------------------------


def test_migrate_resets_the_destination_after_probing_for_the_marker(workspace):
    # The probe selects from a table that does not exist on a fresh
    # destination. PostgreSQL treats that as aborting the transaction, so the
    # hook has to fire even though the probe "succeeded" in answering no.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    base = _destination(conn)
    calls = []
    destination = Destination(
        execute=base.execute,
        fetch=base.fetch,
        read_table=base.read_table,
        executemany=base.executemany,
        reset=lambda: calls.append("reset"),
    )
    # Act
    _run(source, destination)
    # Assert
    assert calls == ["reset"]


def test_migrate_explains_a_first_statement_failure_instead_of_leaking_it(workspace):
    # A poisoned transaction surfaces at the first CREATE TABLE, and the
    # driver's own message names the symptom rather than the cause. The reader
    # is looking at a statement that is not itself wrong, so the refusal has to
    # say what actually happened.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    base = _destination(conn)

    def refusing_execute(sql, params):
        raise RuntimeError("current transaction is aborted")

    destination = Destination(
        execute=refusing_execute,
        fetch=base.fetch,
        read_table=base.read_table,
    )
    # Act
    run = _run
    # Assert
    with pytest.raises(MigrationRefused, match="reset=conn.rollback"):
        run(source, destination)


def test_migrate_works_without_a_reset_hook(workspace):
    # SQLite needs no reset, so the hook stays optional and its absence must not
    # change anything.
    # Arrange
    source = _make_source(workspace)
    conn = _open_destination(workspace)
    # Act
    report = _run(source, _destination(conn))
    # Assert
    assert report.ok is True


def test_destination_defaults_to_the_sqlite_placeholder(workspace):
    # The default is sqlite3's marker; a PostgreSQL caller must pass "%s", which
    # is why the placeholder travels with the driver's callables.
    # Arrange
    destination = Destination(
        execute=lambda sql, params: None,
        fetch=lambda sql: [],
        read_table=lambda table, columns, keys: [],
    )
    # Act
    placeholder = destination.placeholder
    # Assert
    assert placeholder == "?"


# EOF
