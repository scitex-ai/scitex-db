#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db.store._portable_sql.

The null-safe spellings are verified against a REAL sqlite3 connection,
including the version boundary: this container runs a SQLite new enough
for ``IS NOT DISTINCT FROM``, and the test says so out loud rather than
skipping, because a container that can run both spellings is exactly the
environment that hid a 36-hour outage on a host that could only run one.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

import pytest

from scitex_db.store._portable_sql import (
    MIN_SQLITE_VERSION_FOR_IS_NOT_DISTINCT_FROM,
    POSTGRESQL_NULL_SAFE,
    SQLITE_NULL_SAFE,
    SQLITE_ONLY_UPSERT_FORMS,
    null_safe_eq,
    to_paramstyle,
)
from scitex_db.store._url import POSTGRESQL, SQLITE

_RUNNING_SQLITE = tuple(int(part) for part in sqlite3.sqlite_version.split("."))


@pytest.fixture
def memory_sqlite() -> Iterator[sqlite3.Connection]:
    """A real in-memory SQLite with one nullable column, closed on teardown."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE t (note TEXT)")
        conn.execute("INSERT INTO t (note) VALUES (NULL)")
        yield conn
    finally:
        conn.close()


def test_the_sqlite_null_safe_spelling_actually_parses_on_sqlite(
    memory_sqlite: sqlite3.Connection,
) -> None:
    # Arrange
    sql = f"SELECT COUNT(*) FROM t WHERE {null_safe_eq('note', dialect=SQLITE)}"
    # Act
    matched = memory_sqlite.execute(sql, (None,)).fetchone()[0]
    # Assert
    assert matched == 1, (
        "`col IS ?` is null-safe on SQLite and must match the NULL row"
    )


def test_the_postgresql_null_safe_spelling_parses_only_from_sqlite_3_39(
    memory_sqlite: sqlite3.Connection,
) -> None:
    # Arrange
    sql = (
        "SELECT COUNT(*) FROM t WHERE "
        f"{null_safe_eq('note', dialect=POSTGRESQL)}"
    )
    supported = _RUNNING_SQLITE >= MIN_SQLITE_VERSION_FOR_IS_NOT_DISTINCT_FROM
    # Act
    try:
        memory_sqlite.execute(sql, (None,)).fetchone()
        parsed = True
    except sqlite3.OperationalError:
        parsed = False
    # Assert
    assert parsed is supported, (
        f"running SQLite {sqlite3.sqlite_version}: the standard spelling "
        "must parse exactly when the engine is new enough. This container "
        "can run both spellings; the host that could only run one is what "
        "made the outage invisible here"
    )


def test_the_two_null_safe_spellings_are_different_strings() -> None:
    # Arrange
    # Act
    same = SQLITE_NULL_SAFE == POSTGRESQL_NULL_SAFE
    # Assert
    assert same is False, (
        "if these ever collapse to one string the module has no reason to "
        "exist; there is no single spelling that works on both"
    )


def test_null_safe_eq_uses_the_sqlite_operator_for_sqlite() -> None:
    # Arrange
    # Act
    fragment = null_safe_eq("note", dialect=SQLITE)
    # Assert
    assert fragment == "note IS ?"


def test_null_safe_eq_uses_the_standard_operator_for_postgresql() -> None:
    # Arrange
    # Act
    fragment = null_safe_eq("note", dialect=POSTGRESQL)
    # Assert
    assert fragment == "note IS NOT DISTINCT FROM ?"


def test_null_safe_eq_refuses_an_unknown_dialect() -> None:
    # Arrange
    # Act
    # Assert — no default: a default picks a spelling that is a syntax
    # error on the other engine
    with pytest.raises(ValueError, match="Refusing to guess"):
        null_safe_eq("note", dialect="mysql")


def test_sqlite_sql_is_returned_unchanged() -> None:
    # Arrange
    sql = "SELECT * FROM t WHERE note LIKE '%foo%' AND id = ?"
    # Act
    translated = to_paramstyle(sql, dialect=SQLITE)
    # Assert
    assert translated == sql, (
        "the common path must cost nothing and must not be able to corrupt"
    )


def test_a_placeholder_becomes_the_postgresql_paramstyle() -> None:
    # Arrange
    sql = "SELECT * FROM t WHERE id = ?"
    # Act
    translated = to_paramstyle(sql, dialect=POSTGRESQL)
    # Assert
    assert translated == "SELECT * FROM t WHERE id = %s"


def test_a_question_mark_inside_a_literal_survives_translation() -> None:
    # Arrange — a card body containing a question mark; this is routine
    sql = "INSERT INTO t (note) VALUES ('is it done?')"
    # Act
    translated = to_paramstyle(sql, dialect=POSTGRESQL)
    # Assert
    assert translated == sql, (
        "a `?` inside a string literal is NOT a placeholder. Rewriting it "
        "corrupts the stored text and raises nothing — wrong data, not an "
        "error"
    )


def test_a_placeholder_outside_a_literal_still_translates_alongside_one() -> (
    None
):
    # Arrange
    sql = "INSERT INTO t (note, id) VALUES ('is it done?', ?)"
    # Act
    translated = to_paramstyle(sql, dialect=POSTGRESQL)
    # Assert
    assert translated == "INSERT INTO t (note, id) VALUES ('is it done?', %s)"


def test_a_literal_percent_is_doubled_for_the_postgresql_paramstyle() -> None:
    # Arrange
    sql = "SELECT * FROM t WHERE note LIKE '%foo%'"
    # Act
    translated = to_paramstyle(sql, dialect=POSTGRESQL)
    # Assert
    assert translated == "SELECT * FROM t WHERE note LIKE '%%foo%%'", (
        "an undoubled % makes the LIKE pattern a format specifier, which "
        "raises at execution time"
    )


def test_a_doubled_quote_escape_keeps_the_literal_intact() -> None:
    # Arrange — SQL's escape for an apostrophe inside a literal
    sql = "INSERT INTO t (note) VALUES ('it''s done?')"
    # Act
    translated = to_paramstyle(sql, dialect=POSTGRESQL)
    # Assert
    assert translated == sql, (
        "mis-tracking the doubled-quote escape ends the literal early and "
        "the rest of the statement is then rewritten as if it were code"
    )


def test_to_paramstyle_refuses_an_unknown_dialect() -> None:
    # Arrange
    # Act
    # Assert
    with pytest.raises(ValueError, match="unknown dialect"):
        to_paramstyle("SELECT 1", dialect="mysql")


def test_the_naive_rewrite_is_recorded_as_corrupting() -> None:
    # Arrange — what a one-line shortcut would do to the same statement
    sql = "INSERT INTO t (note) VALUES ('is it done?')"
    # Act
    naive = sql.replace("?", "%s")
    # Assert
    assert naive != to_paramstyle(sql, dialect=POSTGRESQL), (
        "evidence, not a gate: this pins WHY the scanner exists. The naive "
        "form stores 'is it done%s' and raises nothing"
    )


def test_the_sqlite_only_upsert_forms_are_recorded() -> None:
    # Arrange
    # Act
    forms = set(SQLITE_ONLY_UPSERT_FORMS)
    # Assert
    assert forms == {"INSERT OR IGNORE", "INSERT OR REPLACE"}, (
        "the portable spelling is ON CONFLICT (...) DO NOTHING / DO UPDATE "
        "SET x = excluded.x, which parses on both"
    )


# EOF
