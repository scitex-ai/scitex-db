#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._enforce.

Real SQLite stores with real triggers. The point of this module is that a
trigger's PRESENCE is not its ENFORCEMENT, so every test here works by
attempting the forbidden action rather than by inspecting the schema.

The cases that matter most are the ones where something OTHER than the guard
refuses -- a read-only connection, a missing table -- because a probe that
counted exceptions would call those "enforced" and be wrong in the direction
that lets a cutover proceed.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._enforce import (
    EnforcementNotProven,
    EnforcementProbe,
    probe_enforcement,
    require_enforcement,
)

GUARD_MESSAGE = "store retirement is one-way"

FORBIDDEN = EnforcementProbe(
    description="retirement is one-way",
    statement="UPDATE meta SET value = 'current' WHERE key = 'store_status'",
    expect_message=GUARD_MESSAGE,
)


def _store(tmpdir, *, guarded: bool):
    path = os.path.join(tmpdir, "guarded.db" if guarded else "bare.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('store_status', 'retired')")
    if guarded:
        conn.execute(
            "CREATE TRIGGER meta_retirement_is_one_way "
            "BEFORE UPDATE ON meta FOR EACH ROW "
            "WHEN OLD.key = 'store_status' AND OLD.value = 'retired' "
            "     AND NEW.value <> 'retired' "
            f"BEGIN SELECT RAISE(ABORT, '{GUARD_MESSAGE}: a retired store "
            "cannot become current'); END"
        )
    conn.commit()
    return conn


@pytest.fixture
def workspace():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
# The two real outcomes
# ----------------------------------------------------------------------------


def test_a_guarded_store_proves_enforcement(workspace):
    # Arrange
    conn = _store(workspace, guarded=True)
    # Act
    result = probe_enforcement(conn, FORBIDDEN)
    # Assert
    assert result.enforced is True


def test_an_unguarded_store_does_not_prove_enforcement(workspace):
    # The forbidden statement SUCCEEDS here, and that success is the finding.
    # This is the store where retiring would silently no-op.
    # Arrange
    conn = _store(workspace, guarded=False)
    # Act
    result = probe_enforcement(conn, FORBIDDEN)
    # Assert
    assert result.enforced is False


def test_the_probe_leaves_an_unguarded_store_unchanged(workspace):
    # The dangerous branch is the one where the statement worked. If the
    # rollback were on the happy path instead of in a `finally`, this is the
    # case that would mutate the store being inspected.
    # Arrange
    conn = _store(workspace, guarded=False)
    # Act
    probe_enforcement(conn, FORBIDDEN)
    # Assert
    assert conn.execute(
        "SELECT value FROM meta WHERE key = 'store_status'"
    ).fetchone()[0] == "retired"


# ----------------------------------------------------------------------------
# The vacuous passes -- something OTHER than the guard refuses
# ----------------------------------------------------------------------------


def test_a_readonly_connection_does_not_count_as_enforcement(workspace):
    # "attempt to write a readonly database" is an exception, and a probe that
    # counted exceptions would call this enforced. It is the worst vacuous pass
    # available, because a read-only connection is a plausible mistake.
    # Arrange
    path = _store(workspace, guarded=True).execute(
        "PRAGMA database_list"
    ).fetchone()[2]
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    # Act
    result = probe_enforcement(ro, FORBIDDEN)
    # Assert
    assert result.enforced is False


def test_a_missing_table_does_not_count_as_enforcement(workspace):
    # A typo raises "no such table". Same shape: an exception that proves
    # nothing about the guarantee.
    # Arrange
    conn = _store(workspace, guarded=True)
    typo = EnforcementProbe(
        description="typo'd probe",
        statement="UPDATE nonexistent SET value = 'current'",
        expect_message=GUARD_MESSAGE,
    )
    # Act
    result = probe_enforcement(conn, typo)
    # Assert
    assert result.enforced is False


def test_a_wrong_refusal_says_the_guard_was_not_what_refused(workspace):
    # The report has to name WHY nothing was proven, or the operator debugs the
    # wrong thing.
    # Arrange
    conn = _store(workspace, guarded=True)
    typo = EnforcementProbe(
        description="typo'd probe",
        statement="UPDATE nonexistent SET value = 'current'",
        expect_message=GUARD_MESSAGE,
    )
    # Act
    result = probe_enforcement(conn, typo)
    # Assert
    assert "NOT with the guard's message" in result.detail


# ----------------------------------------------------------------------------
# A probe that cannot fail is refused rather than run
# ----------------------------------------------------------------------------


def test_a_probe_without_an_expected_message_is_refused():
    # Without one, every environmental failure reads as enforcement.
    # Arrange
    build = EnforcementProbe
    # Act
    kwargs = dict(description="d", statement="UPDATE t SET a = 1", expect_message="  ")
    # Assert
    with pytest.raises(EnforcementNotProven, match="no expected refusal message"):
        build(**kwargs)


def test_a_probe_without_a_statement_is_refused():
    # Arrange
    build = EnforcementProbe
    # Act
    kwargs = dict(description="d", statement="", expect_message="m")
    # Assert
    with pytest.raises(EnforcementNotProven, match="nothing to attempt"):
        build(**kwargs)


# ----------------------------------------------------------------------------
# require_enforcement -- the gate a cutover actually calls
# ----------------------------------------------------------------------------


def test_require_enforcement_passes_on_a_guarded_store(workspace):
    # Arrange
    conn = _store(workspace, guarded=True)
    # Act
    results = require_enforcement(conn, [FORBIDDEN])
    # Assert
    assert results[0].enforced is True


def test_require_enforcement_stops_a_cutover_on_an_unguarded_store(workspace):
    # Arrange
    conn = _store(workspace, guarded=False)
    # Act
    gate = require_enforcement
    # Assert
    with pytest.raises(EnforcementNotProven, match="could not be shown"):
        gate(conn, [FORBIDDEN])


def test_require_enforcement_refuses_an_empty_probe_list(workspace):
    # Proving nothing is not the same as proving everything, and an empty list
    # would otherwise return success having checked nothing.
    # Arrange
    conn = _store(workspace, guarded=True)
    # Act
    gate = require_enforcement
    # Assert
    with pytest.raises(EnforcementNotProven, match="An empty check proves nothing"):
        gate(conn, [])


# EOF
