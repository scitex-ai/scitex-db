#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._preflight.

Real SQLite stores, built to contain the specific problems the preflight exists
to find: a table with no primary key, and a column whose stored values would be
rejected by PostgreSQL. Asserting those against a well-formed store would prove
nothing, so each is constructed deliberately.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._plan import Disposition, MigrationPlanError, TablePlan
from scitex_db._migrate._preflight import preflight

DISPOSITIONS = {
    "good": TablePlan("good", Disposition.MIGRATE),
    "keyless": TablePlan("keyless", Disposition.MIGRATE),
    "mixed": TablePlan("mixed", Disposition.MIGRATE),
    "empty": TablePlan("empty", Disposition.MIGRATE),
    "nul": TablePlan("nul", Disposition.MIGRATE),
    "skipped": TablePlan("skipped", Disposition.EXCLUDE, "deliberately not carried"),
}


@pytest.fixture
def store():
    """A store containing each problem the preflight is meant to surface."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "store.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE good (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("CREATE TABLE keyless (a TEXT, b TEXT)")
    conn.execute("CREATE TABLE mixed (id TEXT PRIMARY KEY, n INTEGER)")
    conn.execute("CREATE TABLE empty (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE skipped (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE nul (id TEXT PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO good VALUES ('g1', 'x')")
    conn.execute("INSERT INTO good VALUES ('g2', 'y')")
    conn.execute("INSERT INTO keyless VALUES ('a', 'b')")
    # SQLite accepts text in an INTEGER column; PostgreSQL will not.
    conn.execute("INSERT INTO mixed VALUES ('m1', 1)")
    conn.execute("INSERT INTO mixed VALUES ('m2', 'not a number')")
    # SQLite stores a NUL in TEXT; PostgreSQL text rejects it.
    conn.execute("INSERT INTO nul VALUES ('n1', 'body with ' || char(0) || ' nul')")
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


def _table(report, name):
    return next(t for t in report.tables if t.table == name)


# ----------------------------------------------------------------------------
# The overall verdict
# ----------------------------------------------------------------------------


def test_preflight_is_not_ok_when_any_table_is_blocked(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert report.ok is False


def test_preflight_counts_rows_only_for_migrated_tables(store):
    # Arrange -- good 2 + keyless 1 + mixed 2 + empty 0 + nul 1; `skipped` excluded
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert report.total_rows == 6


def test_preflight_omits_excluded_tables_from_the_table_list(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert "skipped" not in [t.table for t in report.tables]


def test_preflight_reports_excluded_tables_separately(store):
    # Arrange -- the omission has to be visible, not merely absent
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert [p.table for p in report.excluded] == ["skipped"]


# ----------------------------------------------------------------------------
# The specific blockers
# ----------------------------------------------------------------------------


def test_preflight_flags_a_table_with_no_primary_key(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "keyless").key_columns == ()


def test_a_keyless_table_is_not_ready(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "keyless").ok is False


def test_a_keyless_table_explains_why_it_is_blocked(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert "no primary key" in _table(report, "keyless").blockers[0]


def test_preflight_flags_a_column_postgres_would_reject(store):
    # Arrange -- `mixed.n` is INTEGER but holds 'not a number'
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "mixed").unstorable == ("n",)


def test_a_table_with_unstorable_data_is_not_ready(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "mixed").ok is False


def test_preflight_flags_a_text_column_containing_a_nul_byte(store):
    # Arrange -- SQLite stored the NUL; PostgreSQL text will reject it mid-copy
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "nul").nul_columns == ("body",)


def test_a_table_with_a_nul_byte_is_not_ready(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "nul").ok is False


def test_a_nul_table_explains_the_incompatibility(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert "NUL" in " ".join(_table(report, "nul").blockers)


def test_a_well_formed_table_is_ready(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "good").ok is True


# ----------------------------------------------------------------------------
# Information the real run needs before it starts
# ----------------------------------------------------------------------------


def test_preflight_names_the_empty_tables(store):
    # Arrange -- verify_table refuses an empty comparison unless told
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert report.empty_tables == ("empty",)


def test_preflight_reports_the_row_count_per_table(store):
    # Arrange -- the denominator the real run will be measured against
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "good").row_count == 2


def test_preflight_shows_the_ddl_that_would_run(store):
    # Arrange -- so a human can read it before it executes
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert _table(report, "good").ddl.startswith('CREATE TABLE "good" (')


def test_preflight_summary_states_the_verdict_and_its_scope(store):
    # Arrange
    source = store
    # Act
    summary = preflight(source, DISPOSITIONS).summary()
    # Assert
    assert "NOT READY" in summary


def test_preflight_summary_names_excluded_tables(store):
    # Arrange -- a summary saying only "ok" invites assuming full coverage
    source = store
    # Act
    summary = preflight(source, DISPOSITIONS).summary()
    # Assert
    assert "skipped: NOT MIGRATED" in summary


# ----------------------------------------------------------------------------
# An unaccounted table is not a finding to report -- it invalidates the report
# ----------------------------------------------------------------------------


def test_preflight_raises_when_a_source_table_has_no_disposition(store):
    # Arrange -- a plan that does not describe this store would otherwise
    # produce a confident report about the wrong set of tables
    incomplete = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    source = store
    # Assert
    with pytest.raises(MigrationPlanError, match="no disposition"):
        preflight(source, incomplete)


# ----------------------------------------------------------------------------
# The read-only guarantee
# ----------------------------------------------------------------------------


def test_preflight_reports_a_trigger_it_cannot_carry():
    # Arrange -- a store whose append-only guarantee lives in a trigger, the
    # exact shape the live cards store uses (RAISE(ABORT) on DELETE)
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "trig.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE good (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO good VALUES ('g1', 'x')")
    conn.execute(
        "CREATE TRIGGER good_no_delete BEFORE DELETE ON good BEGIN "
        "SELECT RAISE(ABORT, 'append-only'); END"
    )
    conn.commit()
    conn.close()
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    report = preflight(path, dispositions)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert [o.name for o in report.uncarried] == ["good_no_delete"]


def test_a_store_with_an_uncarried_trigger_is_not_ready():
    # Arrange -- THE REGRESSION TEST. Before this, every table was "ready" and
    # the whole report said READY while the destination would silently lose
    # the trigger enforcing that rows are never removed.
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "trig.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE good (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO good VALUES ('g1', 'x')")
    conn.execute(
        "CREATE TRIGGER good_no_delete BEFORE DELETE ON good BEGIN "
        "SELECT RAISE(ABORT, 'append-only'); END"
    )
    conn.commit()
    conn.close()
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    report = preflight(path, dispositions)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert report.ok is False


def test_preflight_summary_names_the_uncarried_object():
    # Arrange -- the omission has to be readable, not merely counted
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "trig.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE good (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO good VALUES ('g1')")
    conn.execute("CREATE INDEX idx_good_id ON good (id)")
    conn.commit()
    conn.close()
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    summary = preflight(path, dispositions).summary()
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert "idx_good_id" in summary


def test_a_store_with_no_extra_schema_objects_reports_none_uncarried(store):
    # Arrange -- the fixture store has no triggers or explicit indexes, so a
    # clean store must not be penalised by the new gate
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert report.uncarried == ()


def test_preflight_does_not_modify_the_source(store):
    # Arrange
    before = os.path.getmtime(store)
    # Act
    preflight(store, DISPOSITIONS)
    # Assert
    assert os.path.getmtime(store) == before


# EOF
