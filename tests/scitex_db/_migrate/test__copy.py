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
    destination_is_usable,
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
    )
    # Assert
    assert destination_is_usable(_fetch(destination)) is True


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
    )
    # Assert
    assert "mirror_hashes" in read_marker(_fetch(destination))["excluded"]


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
    )
    # Assert
    assert read_marker(_fetch(destination))["tables"]["tasks"] == 2872


# ----------------------------------------------------------------------------
# verify_plan -- an unspecified table must not be silently unverified
# ----------------------------------------------------------------------------


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
