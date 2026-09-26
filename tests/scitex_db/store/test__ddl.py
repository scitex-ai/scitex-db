#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db.store._ddl.

The statement counts are checked against a REAL sqlite3 database by
asking the database what exists afterwards, not by trusting the return
value. A function that reports ``executed=3`` without running anything
passes every test written against its return value alone.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

import pytest

from scitex_db.store._ddl import DDLResult, execute_ddl, should_run_ddl

_SCHEMA = [
    "CREATE TABLE a (id INTEGER PRIMARY KEY)",
    "CREATE TABLE b (id INTEGER PRIMARY KEY)",
    "CREATE TABLE c (id INTEGER PRIMARY KEY)",
]


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    """A real in-memory SQLite connection, closed on teardown."""
    conn = sqlite3.connect(":memory:")
    try:
        yield conn
    finally:
        conn.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def test_every_statement_is_reported_as_executed(
    db: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    result = execute_ddl(db, _SCHEMA)
    # Assert
    assert result.executed == 3


def test_the_tables_actually_exist_afterwards(
    db: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    execute_ddl(db, _SCHEMA)
    # Assert — the ARTIFACT, not the return value
    assert _table_names(db) == {"a", "b", "c"}


def test_a_batch_that_produces_no_statements_reports_zero_submitted(
    db: sqlite3.Connection,
) -> None:
    # Arrange — what a broken splitter hands you
    statements = ["", "   ", "\n"]
    # Act
    result = execute_ddl(db, statements)
    # Assert
    assert result.submitted == 0, (
        "a batch that runs nothing must not look like a batch that worked"
    )


def test_a_batch_that_produces_no_statements_creates_nothing(
    db: sqlite3.Connection,
) -> None:
    # Arrange
    statements = ["", "   ", "\n"]
    # Act
    execute_ddl(db, statements)
    # Assert
    assert _table_names(db) == set()


def test_skipping_reports_every_statement_as_skipped(
    db: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    result = execute_ddl(db, _SCHEMA, run=False)
    # Assert
    assert result.skipped == 3, (
        "skipped is the observable that makes the precondition checkable; "
        "a run reporting skipped=0 against an already-current store IS the "
        "pg_proc outage"
    )


def test_skipping_executes_nothing(
    db: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    execute_ddl(db, _SCHEMA, run=False)
    # Assert
    assert _table_names(db) == set()


def test_skipping_still_reports_what_was_submitted(
    db: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    result = execute_ddl(db, _SCHEMA, run=False)
    # Assert
    assert result.submitted == 3, (
        "a skipped run is a real result, not an early return None; the "
        "caller's assertions still need something to read"
    )


def test_a_client_behind_the_store_does_not_run_ddl() -> None:
    # Arrange — the exact case that took the fleet store down
    # Act
    verdict = should_run_ddl(observed=9, required=7)
    # Assert
    assert verdict is False, (
        "a client BEHIND the store is structurally incapable of adding "
        "anything it lacks; re-running only serialises every connection "
        "behind ShareRowExclusiveLock on pg_proc"
    )


def test_a_client_ahead_of_the_store_runs_ddl() -> None:
    # Arrange
    # Act
    verdict = should_run_ddl(observed=7, required=9)
    # Assert
    assert verdict is True, "this is what migrates the store up"


def test_a_client_level_with_the_store_does_not_run_ddl() -> None:
    # Arrange
    # Act
    verdict = should_run_ddl(observed=7, required=7)
    # Assert
    assert verdict is False


def test_an_unknown_store_version_runs_ddl_conservatively() -> None:
    # Arrange — the store cannot be placed on the ladder at all
    # Act
    verdict = should_run_ddl(observed=None, required=7)
    # Assert
    assert verdict is True, (
        "unknown falls through to the DDL, the conservative branch"
    )


def test_an_unknown_store_version_is_never_compared() -> None:
    # Arrange
    # Act
    verdict = should_run_ddl(observed=None, required=7)
    # Assert — a naive `<` would raise here rather than decide; reaching a
    # bool at all proves None was refused before any comparison
    assert isinstance(verdict, bool)


def test_the_result_refuses_arithmetic_that_loses_a_statement() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="must equal submitted"):
        DDLResult(submitted=3, executed=1, skipped=1)


def test_the_result_refuses_a_negative_count() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="cannot be negative"):
        DDLResult(submitted=1, executed=-1, skipped=2)


def test_the_result_refuses_a_bool_masquerading_as_a_count() -> None:
    # Arrange — bool is an int subclass; True would silently mean 1
    # Act
    # Assert
    with pytest.raises(TypeError, match="must be an int"):
        DDLResult(submitted=True, executed=True, skipped=0)


def test_an_empty_result_is_constructible() -> None:
    # Arrange
    # Act
    result = DDLResult()
    # Assert
    assert result.submitted == 0


# EOF
