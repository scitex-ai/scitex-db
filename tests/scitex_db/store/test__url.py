#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db.store._url.

The first four tests pin the HAZARD rather than the guard: with a real
sqlite3 connection and a real file, an unguarded ``Path(dsn)`` produces
a database that exists, answers queries, and passes an integrity check.
Those tests would still pass with this module deleted — they are
evidence, not gates — and they are here because every other assertion in
this file is only interesting if the failure it prevents is real and
silent.

No ``monkeypatch``: the environment fixture sets a real variable in
``os.environ`` and restores it on teardown, so the code under test reads
the same environment production reads.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable, Iterator

import pytest

from scitex_db.store._url import (
    POSTGRESQL,
    SQLITE,
    StoreLocation,
    UnknownStoreScheme,
    parse_store_url,
    resolve_store,
)

_DSN = "postgresql://cards:secret@db.internal:5432/cards"
_ENV = "SCITEX_TEST_STORE_URL"


@pytest.fixture
def unguarded_dsn_store(tmp_path: Path) -> Iterator[dict]:
    """Reproduce the incident: the raw config value straight into Path().

    ``yield``, not ``return``: the connection is an external resource, so
    it is closed in teardown even when the test body fails. Returning it
    (or anything derived from it) after closing would leave the cleanup
    on the happy path only.
    """
    mangled = tmp_path / Path(_DSN)
    mangled.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(mangled)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY)")
        yield {
            "path": mangled,
            "rows": conn.execute("SELECT * FROM tasks").fetchall(),
            "integrity": conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
        }
    finally:
        conn.close()


@pytest.fixture
def set_store_env() -> Iterator[Callable[[str | None], None]]:
    """Set a REAL environment variable, restoring whatever was there."""
    original = os.environ.get(_ENV)

    def _set(value: str | None) -> None:
        if value is None:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = value

    yield _set

    if original is None:
        os.environ.pop(_ENV, None)
    else:
        os.environ[_ENV] = original


def test_a_dsn_through_path_becomes_a_relative_path() -> None:
    # Arrange
    dsn = _DSN
    # Act
    coerced = Path(dsn)
    # Assert
    assert coerced.is_absolute() is False, (
        "urlsplit's second slash is eaten, so the DSN becomes RELATIVE — "
        "which is why it lands under the working directory unnoticed"
    )


def test_a_dsn_through_path_creates_a_real_file(
    unguarded_dsn_store: dict,
) -> None:
    # Arrange
    # Act
    exists = unguarded_dsn_store["path"].exists()
    # Assert
    assert exists is True, "SQLite created a database at the mangled path"


def test_the_database_created_from_a_dsn_serves_no_rows(
    unguarded_dsn_store: dict,
) -> None:
    # Arrange
    # Act
    rows = unguarded_dsn_store["rows"]
    # Assert
    assert rows == [], "and served it empty, without raising"


def test_the_database_created_from_a_dsn_reports_itself_healthy(
    unguarded_dsn_store: dict,
) -> None:
    # Arrange
    # Act
    integrity = unguarded_dsn_store["integrity"]
    # Assert
    assert integrity == "ok", (
        "and reported it healthy. Nothing raised, nothing logged, and the "
        "caller cannot tell this from a working store"
    )


def test_a_postgresql_dsn_is_classified_as_postgresql() -> None:
    # Arrange
    value = _DSN
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.dialect == POSTGRESQL


def test_a_postgresql_location_keeps_the_dsn_verbatim() -> None:
    # Arrange
    value = _DSN
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.dsn == value


def test_a_postgresql_location_carries_no_path() -> None:
    # Arrange
    value = _DSN
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.path is None, (
        "a caller that ignores dialect and reaches for .path must get None, "
        "so Path(None) raises at the call site rather than producing a file"
    )


def test_reaching_for_path_on_a_postgresql_location_raises_loudly() -> None:
    # Arrange
    location = parse_store_url(_DSN)
    # Act
    # Assert
    with pytest.raises(TypeError):
        Path(location.path)


def test_the_postgres_short_scheme_is_accepted_too() -> None:
    # Arrange
    value = "postgres://host/db"
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.dialect == POSTGRESQL, (
        "libpq accepts postgres:// and real config files carry it; a "
        "consumer must not have to care which spelling it was handed"
    )


def test_a_bare_filesystem_path_is_classified_as_sqlite() -> None:
    # Arrange
    value = "/var/lib/cards/cards.db"
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.dialect == SQLITE


def test_a_bare_filesystem_path_keeps_its_path() -> None:
    # Arrange
    value = "/var/lib/cards/cards.db"
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.path == Path(value)


def test_a_sqlite_location_carries_no_dsn() -> None:
    # Arrange
    value = "/var/lib/cards/cards.db"
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.dsn is None


def test_a_windows_drive_letter_is_a_path_not_a_scheme() -> None:
    # Arrange
    value = r"C:\ProgramData\cards.db"
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.dialect == SQLITE, (
        "urlsplit reports 'c' as the scheme here; treating a one-character "
        "scheme as a scheme would send a real path down the DSN branch"
    )


def test_a_sqlite_url_keeps_its_path() -> None:
    # Arrange
    value = "sqlite:///var/lib/cards/cards.db"
    # Act
    location = parse_store_url(value)
    # Assert
    assert location.path == Path("/var/lib/cards/cards.db")


def test_an_unrecognised_scheme_is_refused_not_coerced_to_a_path() -> None:
    # Arrange
    value = "mysql://host/db"
    # Act
    # Assert — refusing is the point; "probably a path" is the branch both
    # silent successes lived in
    with pytest.raises(UnknownStoreScheme, match="mysql"):
        parse_store_url(value)


def test_an_empty_value_is_refused() -> None:
    # Arrange
    value = "   "
    # Act
    # Assert
    with pytest.raises(ValueError):
        parse_store_url(value)


def test_a_non_string_value_is_refused() -> None:
    # Arrange
    value = Path("/var/lib/cards.db")
    # Act
    # Assert
    with pytest.raises(TypeError):
        parse_store_url(value)


def test_the_validator_refuses_a_sqlite_location_carrying_a_dsn() -> None:
    # Arrange
    path = Path("/var/lib/cards.db")
    # Act
    # Assert
    with pytest.raises(ValueError, match="must not carry a dsn"):
        StoreLocation(dialect=SQLITE, path=path, dsn=_DSN)


def test_the_validator_refuses_a_postgresql_location_carrying_a_path() -> None:
    # Arrange
    path = Path("/var/lib/cards.db")
    # Act
    # Assert
    with pytest.raises(ValueError, match="must not carry a path"):
        StoreLocation(dialect=POSTGRESQL, path=path, dsn=_DSN)


def test_the_validator_refuses_a_sqlite_location_without_a_path() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="requires a path"):
        StoreLocation(dialect=SQLITE)


def test_the_validator_refuses_a_postgresql_location_without_a_dsn() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="requires a dsn"):
        StoreLocation(dialect=POSTGRESQL)


def test_the_validator_refuses_an_unknown_dialect() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="unknown dialect"):
        StoreLocation(dialect="mysql", dsn=_DSN)


def test_resolve_store_reads_the_value_from_the_environment(
    set_store_env: Callable[[str | None], None],
) -> None:
    # Arrange
    set_store_env(_DSN)
    # Act
    location = resolve_store(env=_ENV)
    # Assert
    assert location.dialect == POSTGRESQL, (
        "the seam owns READING the value; both incidents happened before "
        "any parse, so a parser that is only handed values is not the guard"
    )


def test_resolve_store_refuses_when_unset_and_no_default(
    set_store_env: Callable[[str | None], None],
) -> None:
    # Arrange
    set_store_env(None)
    # Act
    # Assert — no silent fallback: an unset store variable quietly becoming
    # a local file is the same failure in a new costume
    with pytest.raises(ValueError, match=_ENV):
        resolve_store(env=_ENV)


def test_resolve_store_uses_the_default_when_unset(
    set_store_env: Callable[[str | None], None],
) -> None:
    # Arrange
    set_store_env(None)
    # Act
    location = resolve_store(env=_ENV, default="/var/lib/cards.db")
    # Assert
    assert location.path == Path("/var/lib/cards.db")


def test_resolve_store_refuses_an_empty_environment_value(
    set_store_env: Callable[[str | None], None],
) -> None:
    # Arrange
    set_store_env("")
    # Act
    # Assert
    with pytest.raises(ValueError):
        resolve_store(env=_ENV)


def test_resolve_store_still_refuses_an_unknown_scheme_from_the_environment(
    set_store_env: Callable[[str | None], None],
) -> None:
    # Arrange
    set_store_env("mysql://host/db")
    # Act
    # Assert
    with pytest.raises(UnknownStoreScheme):
        resolve_store(env=_ENV)


# EOF
