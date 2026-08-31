#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db.store._tx.

Exclusion is verified from the OTHER writer. Two real SQLite
connections open the same file; one calls ``begin_write`` and the
second then tries to write. Whether the second is refused is the whole
contract, and it is invisible from the first connection's return value
— ``BEGIN`` and ``BEGIN IMMEDIATE`` both return ``None``.

PostgreSQL is exercised by a hand-rolled fake that records the SQL and
parameters it was given, because psycopg is not installable here. That
records WHICH statement was issued, which is weaker than observing a
real block; the limit is stated in the module's PR rather than papered
over.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

import pytest

from scitex_db.store._tx import POSTGRESQL_LOCK, begin_write
from scitex_db.store._url import POSTGRESQL, SQLITE

_KEY = 4815162342


class _RecordingCursor:
    def __init__(self, conn: "_FakePostgres") -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self._conn.statements.append((sql, params))

    def close(self) -> None:
        return None


class _FakePostgres:
    """Records the statements it is asked to run."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple | None]] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self)


@pytest.fixture
def shared_db(tmp_path: Path) -> Iterator[Path]:
    """A real SQLite file with a table, usable by two connections."""
    path = tmp_path / "store.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    yield path


@pytest.fixture
def two_writers(shared_db: Path) -> Iterator[tuple]:
    """Two independent connections to the same database file."""
    first = sqlite3.connect(shared_db, timeout=0.2, isolation_level=None)
    second = sqlite3.connect(shared_db, timeout=0.2, isolation_level=None)
    try:
        yield first, second
    finally:
        for conn in (first, second):
            try:
                conn.close()
            except Exception:
                pass


def test_a_second_writer_is_refused_while_the_first_holds_the_lock(
    two_writers: tuple,
) -> None:
    # Arrange
    first, second = two_writers
    begin_write(first, lock_key=_KEY, dialect=SQLITE)
    # Act
    # Assert — observed from the OTHER connection; the first one's return
    # value cannot tell you this
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        second.execute("INSERT INTO t (id) VALUES (1)")


def test_a_second_writer_succeeds_once_the_first_commits(
    two_writers: tuple,
) -> None:
    # Arrange
    first, second = two_writers
    begin_write(first, lock_key=_KEY, dialect=SQLITE)
    first.execute("COMMIT")
    # Act
    second.execute("INSERT INTO t (id) VALUES (1)")
    rows = second.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    # Assert
    assert rows == 1, "the lock must be released, not merely taken"


def test_the_first_writer_can_write_inside_its_own_transaction(
    two_writers: tuple,
) -> None:
    # Arrange
    first, _second = two_writers
    begin_write(first, lock_key=_KEY, dialect=SQLITE)
    # Act
    first.execute("INSERT INTO t (id) VALUES (7)")
    rows = first.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    # Assert
    assert rows == 1


def test_postgresql_takes_the_advisory_lock() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    begin_write(conn, lock_key=_KEY, dialect=POSTGRESQL)
    # Assert
    assert conn.statements == [(POSTGRESQL_LOCK, (_KEY,))]


def test_postgresql_passes_the_key_the_caller_chose() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    begin_write(conn, lock_key=99, dialect=POSTGRESQL)
    # Assert
    assert conn.statements[0][1] == (99,), (
        "a library-chosen key would silently serialise unrelated "
        "subsystems against each other"
    )


def test_the_lock_key_cannot_be_passed_positionally() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    # Assert
    with pytest.raises(TypeError):
        begin_write(conn, _KEY, POSTGRESQL)  # type: ignore[misc]


def test_a_missing_lock_key_is_refused() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    # Assert — no default: the caller must have decided what it serialises
    with pytest.raises(TypeError):
        begin_write(conn, dialect=POSTGRESQL)  # type: ignore[call-arg]


def test_a_non_integer_lock_key_is_refused() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    # Assert
    with pytest.raises(TypeError, match="must be an int"):
        begin_write(conn, lock_key="cards", dialect=POSTGRESQL)


def test_a_bool_lock_key_is_refused() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    # Assert — bool is an int subclass; True would silently mean key 1
    with pytest.raises(TypeError, match="must be an int"):
        begin_write(conn, lock_key=True, dialect=POSTGRESQL)


def test_an_unknown_dialect_is_refused() -> None:
    # Arrange
    conn = _FakePostgres()
    # Act
    # Assert
    with pytest.raises(ValueError, match="Refusing to guess"):
        begin_write(conn, lock_key=_KEY, dialect="mysql")


def test_sqlite_requires_a_lock_key_it_does_not_use(
    two_writers: tuple,
) -> None:
    # Arrange
    first, _second = two_writers
    # Act
    # Assert — the signature must not let a caller skip the decision on
    # the backend where it happens not to matter
    with pytest.raises(TypeError):
        begin_write(first, dialect=SQLITE)  # type: ignore[call-arg]


# EOF
