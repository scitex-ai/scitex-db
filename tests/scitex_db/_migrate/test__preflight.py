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


@pytest.fixture
def store_with_index_on_excluded_table():
    """An index on a table the plan EXCLUDES -- the crossing the fixtures missed.

    Both cases existed separately (an excluded table, an index) and were never
    combined, which is why this reached a real PostgreSQL before it was caught.
    """
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "store.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE good (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("CREATE TABLE skipped (id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("CREATE INDEX idx_skipped_name ON skipped (name)")
    conn.execute("INSERT INTO good VALUES ('g1', 'x')")
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


#: Only the two tables this store has -- `build_plan` refuses a plan naming
#: tables the store lacks, which is the guard working as intended.
CROSSED_DISPOSITIONS = {
    "good": TablePlan("good", Disposition.MIGRATE),
    "skipped": TablePlan("skipped", Disposition.EXCLUDE, "deliberately not carried"),
}


def test_an_index_on_an_excluded_table_is_not_counted_as_carried(
    store_with_index_on_excluded_table,
):
    # Counting it as carried is what made `apply_schema_objects` target a
    # relation that was never created -- after every row had already copied.
    # Arrange
    source = store_with_index_on_excluded_table
    # Act
    report = preflight(source, CROSSED_DISPOSITIONS)
    # Assert
    assert report.carried == ()


def test_an_index_on_an_excluded_table_does_not_block_the_migration(
    store_with_index_on_excluded_table,
):
    # It is not a problem, so it must not be `uncarried` either -- that would
    # block a migration that is entirely correct.
    # Arrange
    source = store_with_index_on_excluded_table
    # Act
    report = preflight(source, CROSSED_DISPOSITIONS)
    # Assert
    assert report.ok is True


def test_an_index_on_an_excluded_table_is_reported_rather_than_dropped(
    store_with_index_on_excluded_table,
):
    # Silence is what turned this into a mid-run crash instead of a line of
    # output.
    # Arrange
    source = store_with_index_on_excluded_table
    # Act
    summary = preflight(source, CROSSED_DISPOSITIONS).summary()
    # Assert
    assert "idx_skipped_name" in summary


def test_the_nul_blocker_states_how_many_rows_are_affected(store):
    # The count decides the remedy -- a hand-correction with an audit trail at
    # 2 rows, something systematic at 2000 -- so a blocker naming only the
    # column leaves the reader unable to choose.
    # Arrange
    source = store
    # Act
    blockers = " ".join(_table(preflight(source, DISPOSITIONS), "nul").blockers)
    # Assert
    assert "1 row(s)" in blockers


def test_the_nul_blocker_names_the_offending_row(store):
    # Arrange
    source = store
    # Act
    blockers = " ".join(_table(preflight(source, DISPOSITIONS), "nul").blockers)
    # Assert
    assert "'n1'" in blockers


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


def _store_with_trigger(trigger_sql):
    """A one-table store carrying `trigger_sql`, returned as (path, tmpdir)."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "trig.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE good (id TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO good VALUES ('g1', 'x')")
    conn.execute(trigger_sql)
    conn.commit()
    conn.close()
    return path, tmpdir


#: A guard in the shape the live store uses -- the translator handles this.
_TRANSLATABLE = (
    "CREATE TRIGGER good_no_delete BEFORE DELETE ON good BEGIN "
    "SELECT RAISE(ABORT, 'append-only'); END"
)
#: A body that does real work; no faithful translation is known for it.
_UNTRANSLATABLE = (
    "CREATE TRIGGER good_audit AFTER INSERT ON good BEGIN "
    "INSERT INTO good (id, title) VALUES ('audit', 'x'); END"
)


def test_a_translatable_trigger_is_reported_as_carried():
    # Arrange -- the append-only guards DO have a faithful translation, so they
    # must not block: "we can move this" and "nobody decided" are different
    # states and collapsing them would block a migration that is actually safe
    path, tmpdir = _store_with_trigger(_TRANSLATABLE)
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    report = preflight(path, dispositions)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert [o.name for o in report.carried] == ["good_no_delete"]


def test_a_store_whose_objects_all_translate_is_ready():
    # Arrange
    path, tmpdir = _store_with_trigger(_TRANSLATABLE)
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    report = preflight(path, dispositions)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert report.ok is True


def test_preflight_reports_a_trigger_it_cannot_carry():
    # Arrange -- a body outside the recognised forms
    path, tmpdir = _store_with_trigger(_UNTRANSLATABLE)
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    report = preflight(path, dispositions)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert [o.name for o in report.uncarried] == ["good_audit"]


def test_a_store_with_an_uncarried_trigger_is_not_ready():
    # Arrange -- THE REGRESSION TEST. Before this gate existed, every table was
    # "ready" and the whole report said READY while the destination would
    # silently lose a trigger the source relies on.
    path, tmpdir = _store_with_trigger(_UNTRANSLATABLE)
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    report = preflight(path, dispositions)
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert report.ok is False


def test_preflight_summary_names_the_uncarried_object():
    # Arrange -- the omission has to be readable, not merely counted
    path, tmpdir = _store_with_trigger(_UNTRANSLATABLE)
    dispositions = {"good": TablePlan("good", Disposition.MIGRATE)}
    # Act
    summary = preflight(path, dispositions).summary()
    shutil.rmtree(tmpdir, ignore_errors=True)
    # Assert
    assert "good_audit" in summary


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
