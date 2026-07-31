#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._copy.

The behaviour that matters here is ORDERING and REFUSAL: the completion marker
must not exist until verification has passed, and a destination without a marker
must read as unusable rather than as probably-fine. Both are tested against a
real SQLite database standing in for the destination, so the marker is genuinely
written and genuinely read back.

Quiescence is tested as a required, non-defaultable statement -- the migration
cannot verify it, so the tests assert that it at least cannot be claimed
anonymously or without a named mechanism.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._copy import (
    MARKER_TABLE,
    MigrationRefused,
    MigrationResult,
    Quiescence,
    StoreScope,
    destination_is_usable,
    destination_is_whole_store,
    finalize,
    read_marker,
    verify_plan,
)
from scitex_db._migrate._plan import Disposition, TablePlan
from scitex_db._migrate._verify import MigrationVerificationError, VerificationReport

PLAN = (
    TablePlan("tasks", Disposition.MIGRATE),
    TablePlan("mirror_hashes", Disposition.EXCLUDE, "no second store to mirror"),
)
QUIET = Quiescence(mechanism="operator", stated_by="ywatanabe")
WHOLE = StoreScope(database_is_whole_store=True, stated_by="test")


@pytest.fixture
def destination():
    """A real, empty SQLite database standing in for the destination."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "destination.db")
    sqlite3.connect(path).close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


def _fetch(path):
    def run(sql):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return list(conn.execute(sql))
        finally:
            conn.close()

    return run


def _write(path):
    def run(sql, params=()):
        conn = sqlite3.connect(path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    return run


def _clean(table="tasks", rows=3):
    return VerificationReport(
        table=table, rows_compared=rows, source_rows=rows, destination_rows=rows
    )


def _failed(table="tasks"):
    return VerificationReport(
        table=table,
        rows_compared=1,
        source_rows=2,
        destination_rows=1,
        missing_ids=("S:2",),
    )


# ----------------------------------------------------------------------------
# Quiescence -- a claim the migration cannot verify, so it must be attributable
# ----------------------------------------------------------------------------


def test_quiescence_accepts_a_named_mechanism_and_claimant():
    # Arrange
    mechanism = "store-mode"
    # Act
    q = Quiescence(mechanism=mechanism, stated_by="scitex-cards")
    # Assert
    assert q.mechanism == "store-mode"


def test_quiescence_refuses_a_blank_mechanism():
    # Arrange -- recording HOW writes stopped is the audit trail
    mechanism = "   "
    # Act
    claimant = "ywatanabe"
    # Assert
    with pytest.raises(MigrationRefused, match="no mechanism named"):
        Quiescence(mechanism=mechanism, stated_by=claimant)


def test_quiescence_refuses_an_anonymous_claim():
    # Arrange
    mechanism = "operator"
    # Act
    claimant = ""
    # Assert
    with pytest.raises(MigrationRefused, match="claimed by nobody"):
        Quiescence(mechanism=mechanism, stated_by=claimant)


# ----------------------------------------------------------------------------
# read_marker / destination_is_usable -- absence must mean unusable
# ----------------------------------------------------------------------------


def test_read_marker_returns_none_on_a_fresh_destination(destination):
    # Arrange -- no marker table exists at all
    fetch = _fetch(destination)
    # Act
    marker = read_marker(fetch)
    # Assert
    assert marker is None


def test_fresh_destination_is_not_usable(destination):
    # Arrange -- the case an adapter would otherwise happily serve from
    fetch = _fetch(destination)
    # Act
    usable = destination_is_usable(fetch)
    # Assert
    assert usable is False


def test_read_marker_returns_none_for_an_empty_marker_table(destination):
    # Arrange -- table created but never populated
    _write(destination)(
        f'CREATE TABLE "{MARKER_TABLE}" (payload TEXT NOT NULL)', ()
    )
    # Act
    marker = read_marker(_fetch(destination))
    # Assert
    assert marker is None


def test_read_marker_returns_none_for_an_unparseable_payload(destination):
    # Arrange -- a marker we cannot parse is not a marker we can trust
    write = _write(destination)
    write(f'CREATE TABLE "{MARKER_TABLE}" (payload TEXT NOT NULL)', ())
    write(f'INSERT INTO "{MARKER_TABLE}" (payload) VALUES (?)', ("not json",))
    # Act
    marker = read_marker(_fetch(destination))
    # Assert
    assert marker is None


# ----------------------------------------------------------------------------
# finalize -- the marker is written LAST, and only on a clean verification
# ----------------------------------------------------------------------------


def test_finalize_writes_the_marker_when_every_table_verified(destination):
    # Arrange
    reports = [_clean()]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert destination_is_usable(_fetch(destination)) is True


def test_the_marker_carries_the_store_identity(destination):
    # This is what lets a reader ask "is this THE store", not merely "is this a
    # complete store". A canonical-store guard needs the first question.
    # Arrange
    reports = [_clean()]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity="0bb1395b-6f19-4a2d-9782-7dd4d296f2a0",
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert read_marker(_fetch(destination))["store_identity"] == (
        "0bb1395b-6f19-4a2d-9782-7dd4d296f2a0"
    )


def test_an_absent_store_identity_is_recorded_as_an_explicit_null(destination):
    # An ABSENT key is ambiguous -- older marker format, erased, or never set --
    # while an explicit null is a fact. The same argument this package makes
    # about other people's data, applied to its own payload.
    # Arrange
    reports = [_clean()]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert "store_identity" in read_marker(_fetch(destination))


# ----------------------------------------------------------------------------
# StoreScope -- "was this verified" and "is this everything" are two questions
# ----------------------------------------------------------------------------


def test_a_partial_store_must_name_what_is_outside_the_database():
    # "Partial" without saying what is missing is a warning nobody can act on.
    # Arrange
    build = StoreScope
    # Act
    kwargs = dict(database_is_whole_store=False, stated_by="test")
    # Assert
    with pytest.raises(MigrationRefused, match="nothing is named as living outside"):
        build(**kwargs)


def test_a_whole_store_cannot_also_name_things_outside_it():
    # Arrange
    build = StoreScope
    # Act
    kwargs = dict(
        database_is_whole_store=True,
        stated_by="test",
        outside_the_database=("threads.json",),
    )
    # Assert
    with pytest.raises(MigrationRefused, match="contradictory store scope"):
        build(**kwargs)


def test_a_partial_copy_is_still_marked_complete(destination):
    # A partial migration can be entirely correct. `ok` is about fidelity, so
    # incompleteness must not be smuggled into it -- it gets its own question.
    # Arrange
    partial = StoreScope(
        database_is_whole_store=False,
        stated_by="test",
        outside_the_database=("threads.json", "attachments/"),
    )
    # Act
    finalize(
        PLAN,
        [_clean()],
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=partial,
    )
    # Assert
    assert destination_is_usable(_fetch(destination)) is True


def test_a_partial_copy_is_not_the_whole_store(destination):
    # The second question, and the one that was never asked on 2026-07-30.
    # Arrange
    partial = StoreScope(
        database_is_whole_store=False,
        stated_by="test",
        outside_the_database=("threads.json",),
    )
    # Act
    finalize(
        PLAN,
        [_clean()],
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=partial,
    )
    # Assert
    assert destination_is_whole_store(_fetch(destination)) is False


def test_a_whole_store_copy_says_so(destination):
    # Arrange
    reports = [_clean()]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert destination_is_whole_store(_fetch(destination)) is True


def test_a_fresh_destination_is_not_the_whole_store(destination):
    # Absent marker means "I could not tell", which must never read as yes.
    # Arrange
    fetch = _fetch(destination)
    # Act
    answer = destination_is_whole_store(fetch)
    # Assert
    assert answer is False


def test_the_marker_names_what_was_left_outside(destination):
    # Naming them is what turns a vague doubt into someone's next card.
    # Arrange
    partial = StoreScope(
        database_is_whole_store=False,
        stated_by="test",
        outside_the_database=("threads.json", "attachments/"),
    )
    # Act
    finalize(
        PLAN,
        [_clean()],
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=partial,
    )
    # Assert
    assert read_marker(_fetch(destination))["outside_the_database"] == [
        "threads.json",
        "attachments/",
    ]


def test_finalize_refuses_when_a_table_failed_verification(destination):
    # Arrange
    reports = [_failed()]
    # Act
    write = _write(destination)
    # Assert
    with pytest.raises(MigrationRefused, match="failed verification"):
        finalize(
            PLAN,
            reports,
            QUIET,
            write,
            source_identity="cards.db",
            completed_at="2026-07-30T02:00:00Z",
            store_identity=None,
            
            predecessor_identity="predecessor-store",store_scope=WHOLE,
        )


def test_a_failed_migration_leaves_the_destination_unusable(destination):
    # Arrange -- the ordering guarantee: no marker on a failed verification.
    # The refusal itself is asserted by the test above; suppressing it here
    # keeps this test to the single assertion that matters -- what state the
    # destination was left in.
    reports = [_failed()]
    # Act
    with contextlib.suppress(MigrationRefused):
        finalize(
            PLAN,
            reports,
            QUIET,
            _write(destination),
            source_identity="cards.db",
            completed_at="2026-07-30T02:00:00Z",
            store_identity=None,
            
            predecessor_identity="predecessor-store",store_scope=WHOLE,
        )
    # Assert
    assert destination_is_usable(_fetch(destination)) is False


def test_marker_records_the_quiescence_mechanism(destination):
    # Arrange -- so an auditor can see the claim was 'operator', not code
    reports = [_clean()]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert read_marker(_fetch(destination))["quiescence"]["mechanism"] == "operator"


def test_marker_records_the_excluded_tables_and_why(destination):
    # Arrange -- the omission must be auditable from the destination itself
    reports = [_clean()]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert "mirror_hashes" in read_marker(_fetch(destination))["excluded"]


def test_finalize_uses_the_placeholder_the_destination_driver_wants(destination):
    # Arrange -- PostgreSQL rejects `?`; psycopg2 wants `%s`. Hardcoding
    # sqlite3's marker would fail every real migration at its final step, so
    # the emitted SQL is captured to prove the parameter is honoured.
    seen = []

    def capture(sql, params=()):
        seen.append(sql)

    # Act
    finalize(
        PLAN,
        [_clean()],
        QUIET,
        capture,
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
        placeholder="%s",
    )
    # Assert
    assert "VALUES (%s)" in seen[-1]


def test_marker_records_rows_compared_per_table(destination):
    # Arrange -- the denominator travels with the claim
    reports = [_clean(rows=2872)]
    # Act
    finalize(
        PLAN,
        reports,
        QUIET,
        _write(destination),
        source_identity="cards.db",
        completed_at="2026-07-30T02:00:00Z",
        store_identity=None,
        
        predecessor_identity="predecessor-store",store_scope=WHOLE,
    )
    # Assert
    assert read_marker(_fetch(destination))["tables"]["tasks"] == 2872


# ----------------------------------------------------------------------------
# verify_plan -- an unspecified table must not be silently unverified
# ----------------------------------------------------------------------------


def test_apply_schema_objects_creates_indexes_before_triggers():
    # Arrange -- order is load-bearing: if a trigger body references an index
    # by name the reference must resolve, so indexes go first
    from scitex_db._migrate._copy import apply_schema_objects
    from scitex_db._migrate._introspect import SchemaObject

    objs = [
        SchemaObject(
            "t_guard",
            "t",
            "trigger",
            "CREATE TRIGGER t_guard BEFORE DELETE ON t BEGIN "
            "SELECT RAISE(ABORT, 'no'); END",
        ),
        SchemaObject("idx_t", "t", "index", "CREATE INDEX idx_t ON t (id)"),
    ]
    # Act
    applied = apply_schema_objects(objs, lambda sql, params=(): None)
    # Assert
    assert applied == ("idx_t", "t_guard")


def test_apply_schema_objects_emits_translated_sql_not_the_source():
    # Arrange -- the destination must receive PostgreSQL, not SQLite
    from scitex_db._migrate._copy import apply_schema_objects
    from scitex_db._migrate._introspect import SchemaObject

    seen = []
    objs = [
        SchemaObject(
            "t_guard",
            "t",
            "trigger",
            "CREATE TRIGGER t_guard BEFORE DELETE ON t BEGIN "
            "SELECT RAISE(ABORT, 'no'); END",
        )
    ]
    # Act
    apply_schema_objects(objs, lambda sql, params=(): seen.append(sql))
    # Assert
    assert "RAISE EXCEPTION" in seen[0]


def test_apply_schema_objects_propagates_a_translation_failure():
    # Arrange -- a destination with SOME of its triggers is more dangerous than
    # one with none: the missing ones are invisible while the present ones make
    # it look protected. So nothing is swallowed.
    from scitex_db._migrate._copy import apply_schema_objects
    from scitex_db._migrate._introspect import SchemaObject
    from scitex_db._migrate._triggers import TriggerTranslationError

    objs = [
        SchemaObject(
            "t_odd",
            "t",
            "trigger",
            "CREATE TRIGGER t_odd AFTER INSERT ON t BEGIN SELECT custom(); END",
        )
    ]
    # Act
    writer = lambda sql, params=(): None  # noqa: E731
    # Assert
    with pytest.raises(TriggerTranslationError):
        apply_schema_objects(objs, writer)


def test_verify_plan_refuses_a_table_with_no_key_columns():
    # Arrange
    rows = {"tasks": [{"id": "1"}]}
    # Act
    reader = lambda t: rows[t]  # noqa: E731
    # Assert
    with pytest.raises(MigrationVerificationError, match="no key columns"):
        verify_plan(PLAN, reader, reader, key_columns={}, columns={"tasks": ("id",)})


def test_verify_plan_refuses_a_table_with_no_comparison_columns():
    # Arrange
    rows = {"tasks": [{"id": "1"}]}
    # Act
    reader = lambda t: rows[t]  # noqa: E731
    # Assert
    with pytest.raises(MigrationVerificationError, match="no comparison columns"):
        verify_plan(PLAN, reader, reader, key_columns={"tasks": ("id",)}, columns={})


def test_verify_plan_reports_only_the_migrated_tables():
    # Arrange -- mirror_hashes is excluded and must not be verified
    rows = {"tasks": [{"id": "1", "title": "a"}]}
    # Act
    reader = lambda t: rows[t]  # noqa: E731
    reports = verify_plan(
        PLAN,
        reader,
        reader,
        key_columns={"tasks": ("id",)},
        columns={"tasks": ("id", "title")},
    )
    # Assert
    assert [r.table for r in reports] == ["tasks"]


# ----------------------------------------------------------------------------
# MigrationResult.summary -- exclusions are visible beside the successes
# ----------------------------------------------------------------------------


def test_summary_names_excluded_tables_even_when_everything_passed():
    # Arrange -- a summary listing only copies reads as a complete copy
    result = MigrationResult(
        reports=(_clean(),),
        excluded=(TablePlan("mirror_hashes", Disposition.EXCLUDE, "no second store"),),
        marked_complete=True,
    )
    # Act
    summary = result.summary()
    # Assert
    assert "mirror_hashes: NOT MIGRATED" in summary


def test_summary_says_the_destination_is_not_usable_without_a_marker():
    # Arrange
    result = MigrationResult(reports=(_clean(),), excluded=(), marked_complete=False)
    # Act
    summary = result.summary()
    # Assert
    assert "NOT usable" in summary


def test_result_is_not_ok_without_a_marker():
    # Arrange -- clean reports are not sufficient; the marker is the assertion
    result = MigrationResult(reports=(_clean(),), excluded=(), marked_complete=False)
    # Act
    ok = result.ok
    # Assert
    assert ok is False


# EOF
