#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db.store._backend.

psycopg is not installable in this environment, so the PostgreSQL path
is exercised by a hand-rolled fake — not a mock library — that models the
one PostgreSQL behaviour this module has to survive: **a failed
statement aborts the transaction**, and every later statement fails with
"current transaction is aborted" until rollback.

That fake is what makes the rollback guard testable by its EFFECT. It
counts rollbacks, so a test can assert the module actually rolled back
rather than asserting the return value happened to come out right. A
function that returns the right answer without doing the thing passes
every test written against its return value.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from scitex_db.store._backend import BackendReport, describe_backend
from scitex_db.store._url import POSTGRESQL, SQLITE, StoreLocation

_DSN = "postgresql://cards@db.internal:5432/cards"


class _FakePostgresCursor:
    """Answers like libpq: no sqlite_version(), and aborts on failure."""

    def __init__(self, conn: "_FakePostgres") -> None:
        self._conn = conn
        self._row: tuple | None = None

    def execute(self, sql: str) -> None:
        if self._conn.aborted:
            raise RuntimeError(
                "current transaction is aborted, commands ignored until "
                "end of transaction block"
            )
        if "sqlite_version" in sql:
            self._conn.aborted = True
            raise RuntimeError("function sqlite_version() does not exist")
        if "server_version" in sql:
            self._row = ("16.3",)
            return
        raise RuntimeError(f"unrecognised probe: {sql}")

    def fetchone(self) -> tuple | None:
        return self._row

    def close(self) -> None:
        return None


class _FakePostgres:
    """A PostgreSQL-shaped connection that records its rollbacks."""

    def __init__(self) -> None:
        self.aborted = False
        self.rollbacks = 0

    def cursor(self) -> _FakePostgresCursor:
        return _FakePostgresCursor(self)

    def rollback(self) -> None:
        self.rollbacks += 1
        self.aborted = False


class _Unidentifiable:
    """A connection-shaped object that refuses every probe."""

    def cursor(self) -> "_Unidentifiable":
        return self

    def execute(self, sql: str) -> None:
        raise RuntimeError("no")

    def fetchone(self) -> tuple | None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def live_sqlite(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A real SQLite connection, closed in teardown."""
    conn = sqlite3.connect(tmp_path / "cards.db")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def fake_postgres() -> _FakePostgres:
    return _FakePostgres()


def test_a_live_sqlite_connection_reports_the_sqlite_dialect(
    live_sqlite: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    report = describe_backend(live_sqlite)
    # Assert
    assert report.dialect == SQLITE


def test_a_live_sqlite_connection_reports_the_engines_own_version(
    live_sqlite: sqlite3.Connection,
) -> None:
    # Arrange
    expected = sqlite3.sqlite_version
    # Act
    report = describe_backend(live_sqlite)
    # Assert
    assert report.server_version == expected, (
        "the version must come from the running engine, not from a "
        "constant that happens to match on the developer's machine"
    )


def test_a_postgres_shaped_connection_reports_the_postgresql_dialect(
    fake_postgres: _FakePostgres,
) -> None:
    # Arrange
    # Act
    report = describe_backend(fake_postgres)
    # Assert
    assert report.dialect == POSTGRESQL


def test_a_postgres_shaped_connection_reports_its_server_version(
    fake_postgres: _FakePostgres,
) -> None:
    # Arrange
    # Act
    report = describe_backend(fake_postgres)
    # Assert
    assert report.server_version == "16.3"


def test_the_failed_sqlite_probe_is_rolled_back_on_postgres(
    fake_postgres: _FakePostgres,
) -> None:
    # Arrange
    # Act
    describe_backend(fake_postgres)
    # Assert — the EFFECT, not the return value: without this rollback the
    # caller's transaction stays aborted and every later statement fails
    assert fake_postgres.rollbacks == 1


def test_the_connection_is_left_usable_after_being_described(
    fake_postgres: _FakePostgres,
) -> None:
    # Arrange
    # Act
    describe_backend(fake_postgres)
    # Assert
    assert fake_postgres.aborted is False, (
        "a diagnostic that breaks the thing it is diagnosing is worse "
        "than no diagnostic"
    )


def test_an_unidentifiable_connection_reports_unknown_not_a_guess() -> None:
    # Arrange
    conn = _Unidentifiable()
    # Act
    report = describe_backend(conn)
    # Assert
    assert report.dialect is None, (
        "'probably SQLite' is exactly the assumption that survives a "
        "backend port and then quietly lies"
    )


def test_an_unidentifiable_connection_reports_no_version() -> None:
    # Arrange
    conn = _Unidentifiable()
    # Act
    report = describe_backend(conn)
    # Assert
    assert report.server_version is None


def test_a_store_location_reports_the_selected_dialect() -> None:
    # Arrange
    location = StoreLocation(dialect=POSTGRESQL, dsn=_DSN)
    # Act
    report = describe_backend(location)
    # Assert
    assert report.dialect == POSTGRESQL


def test_a_store_location_reports_no_server_version() -> None:
    # Arrange
    location = StoreLocation(dialect=POSTGRESQL, dsn=_DSN)
    # Act
    report = describe_backend(location)
    # Assert
    assert report.server_version is None, (
        "a location says which engine was SELECTED, never which is "
        "RUNNING; claiming a version here would be the original defect"
    )


def test_the_config_source_is_recorded_verbatim(
    live_sqlite: sqlite3.Connection,
) -> None:
    # Arrange
    source = "SCITEX_CARDS_DB"
    # Act
    report = describe_backend(live_sqlite, config_source=source)
    # Assert
    assert report.config_source == source


def test_the_config_source_is_unknown_when_the_caller_does_not_say(
    live_sqlite: sqlite3.Connection,
) -> None:
    # Arrange
    # Act
    report = describe_backend(live_sqlite)
    # Assert
    assert report.config_source is None


def test_the_validator_refuses_an_unknown_dialect() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="unknown dialect"):
        BackendReport(dialect="mysql")


def test_the_validator_refuses_a_version_without_a_dialect() -> None:
    # Arrange
    # Act
    # Assert — a version for an unidentified engine is a guess wearing a
    # number
    with pytest.raises(ValueError, match="cannot be known"):
        BackendReport(dialect=None, server_version="16.3")


def test_an_unknown_report_is_constructible() -> None:
    # Arrange
    # Act
    report = BackendReport()
    # Assert
    assert report.dialect is None


# EOF
