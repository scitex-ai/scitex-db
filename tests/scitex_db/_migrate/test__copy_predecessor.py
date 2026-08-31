#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that the destination cannot be an identity TWIN of its source.

The defect, measured on the live scitex-cards cutover 2026-07-31:

    retired SQLite   store_uuid            = 0bb1395b-...
                     retired_in_favour_of  = 0bb1395b-...   <- itself
    PostgreSQL       store_uuid            = 0bb1395b-...   <- twin

`retired_in_favour_of` is a uuid-shaped POINTER, so against twins it names both
stores and identifies neither, and `expected_uuid` -- whose whole job is "am I
on the right store?" -- passes against the RETIRED one.

`store_identity` was already keyword-only with no default, precisely so a caller
had to decide. The caller decided wrong, because the source's own uuid is the
value sitting in front of them. Requiring a decision is not the same as
rejecting the answer that is always wrong.

Real SQLite destination. No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import sqlite3

import pytest

from scitex_db._migrate._copy import MigrationRefused, StoreScope, finalize
from scitex_db._migrate._provenance import Quiescence
from scitex_db._migrate._verify import VerificationReport

QUIET = Quiescence(mechanism="operator", stated_by="test")
WHOLE = StoreScope(database_is_whole_store=True, stated_by="test")
CLEAN = (
    VerificationReport(
        table="t", source_rows=1, destination_rows=1, rows_compared=1
    ),
)


@pytest.fixture
def write():
    """A real destination the marker is genuinely written into."""
    conn = sqlite3.connect(":memory:")

    def _write(sql, params):
        conn.execute(sql, params)

    _write.conn = conn
    yield _write
    conn.close()


def _finalize(write, *, identity, predecessor):
    return finalize(
        [],
        CLEAN,
        QUIET,
        write,
        source_identity="src",
        completed_at="2026-07-31T00:00:00Z",
        store_identity=identity,
        predecessor_identity=predecessor,
        store_scope=WHOLE,
        quiescence_evidence=None,
    )


def test_a_twin_identity_is_refused(write):
    # The exact shape shipped on the live store.
    # Arrange
    same = "0bb1395b-6f19-4a2d-9782-7dd4d296f2a0"
    # Act
    raises = pytest.raises(MigrationRefused, match="identity TWIN")
    # Assert
    with raises:
        _finalize(write, identity=same, predecessor=same)


def test_the_refusal_says_what_to_do_instead(write):
    # An error that only states what broke is half-written.
    # Arrange
    same = "same-uuid"
    # Act
    raises = pytest.raises(MigrationRefused, match="Mint a NEW identity")
    # Assert
    with raises:
        _finalize(write, identity=same, predecessor=same)


def test_distinct_identities_are_accepted(write):
    # POSITIVE CONTROL. A guard that refuses every pair is indistinguishable
    # from one that works, and this is the pair a correct cutover passes.
    # Arrange
    new, old = "1d55dd6e-successor", "0bb1395b-predecessor"
    # Act
    result = _finalize(write, identity=new, predecessor=old)
    # Assert
    assert result.marked_complete is True


def test_the_predecessor_is_recorded_on_the_successor(write):
    # Lineage points BACKWARD, and lives on the store that survives. The forward
    # pointer only exists if the source is ever retired -- this run was reversed.
    # Arrange
    _finalize(write, identity="new", predecessor="old")
    # Act
    row = write.conn.execute(
        "SELECT payload FROM scitex_migration_complete"
    ).fetchone()
    # Assert
    assert '"predecessor_identity": "old"' in row[0]


def test_two_nulls_are_not_a_twin(write):
    # `None` is the explicit claim "declares no identity", which a generic store
    # may legitimately make. Two stores declaring nothing are not the same store,
    # and treating them as twins would block a legitimate migration.
    # Arrange
    both_none = None
    # Act
    result = _finalize(write, identity=both_none, predecessor=both_none)
    # Assert
    assert result.marked_complete is True


def test_a_named_successor_of_an_unidentified_source_is_accepted(write):
    # The source declaring nothing does not stop the destination declaring
    # something -- that is a store GAINING an identity, which is progress.
    # Arrange
    new = "1d55dd6e-successor"
    # Act
    result = _finalize(write, identity=new, predecessor=None)
    # Assert
    assert result.marked_complete is True

# EOF
