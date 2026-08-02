#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._ddl.

The content-vs-declaration check cannot be exercised against the live
scitex-cards store, because that store has zero declared/stored type
mismatches (measured 2026-07-30). So those tests build a real SQLite table that
deliberately stores the wrong type -- which SQLite permits with a plain INSERT --
rather than asserting against a store that happens to be clean today.

Real values and real SQLite databases, no mocks. One assertion per test.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._ddl import (
    Column,
    DDLTranslationError,
    create_table_ddl,
    postgres_type_for,
    quote_identifier,
    sqlite_affinity,
    unstorable_columns,
)


@pytest.fixture
def mixed_type_db():
    """A real SQLite table whose INTEGER column also holds text and a blob."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "mixed.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, n INTEGER, s TEXT)")
    # SQLite accepts every one of these despite the declarations.
    conn.execute("INSERT INTO t (id, n, s) VALUES (1, 42, 'ok')")
    conn.execute("INSERT INTO t (id, n, s) VALUES (2, 'banana', 'ok')")
    conn.execute("INSERT INTO t (id, n, s) VALUES (3, X'00ff', 'ok')")
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


def _stored_types(path, table, column):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [
            r[0]
            for r in conn.execute(f'SELECT DISTINCT typeof("{column}") FROM "{table}"')
        ]
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# sqlite_affinity -- the documented five rules, in their load-bearing order
# ----------------------------------------------------------------------------


def test_affinity_of_integer_is_integer():
    # Arrange
    declared = "INTEGER"
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "INTEGER"


def test_affinity_of_varchar_is_text():
    # Arrange
    declared = "VARCHAR(255)"
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "TEXT"


def test_affinity_of_empty_declaration_is_blob():
    # Arrange -- a column declared with no type at all
    declared = ""
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "BLOB"


def test_affinity_of_double_is_real():
    # Arrange
    declared = "DOUBLE"
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "REAL"


def test_affinity_of_decimal_is_numeric():
    # Arrange -- matches none of the earlier rules
    declared = "DECIMAL(10,2)"
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "NUMERIC"


def test_affinity_rule_order_puts_int_before_the_text_rule():
    # Arrange -- "INT" must win even though the word also has no CHAR/TEXT
    declared = "UNSIGNED BIG INT"
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "INTEGER"


def test_affinity_of_point_is_integer_by_the_substring_rule():
    # Arrange -- "POINT" contains "INT" only incidentally, yet SQLite's
    # documented first-match-wins rules genuinely give it INTEGER affinity.
    # Asserted deliberately: this is a surprising-but-correct consequence of
    # the rule order, so a future reader who "fixes" it would diverge from
    # SQLite rather than from a bug here.
    declared = "POINT"
    # Act
    result = sqlite_affinity(declared)
    # Assert
    assert result == "INTEGER"


# ----------------------------------------------------------------------------
# postgres_type_for -- width choices that avoid late, misleading failures
# ----------------------------------------------------------------------------


def test_integer_maps_to_bigint_not_integer():
    # Arrange -- SQLite integers are 8-byte; PostgreSQL INTEGER is 4-byte
    declared = "INTEGER"
    # Act
    result = postgres_type_for(declared)
    # Assert
    assert result == "BIGINT"


def test_real_maps_to_double_precision_not_real():
    # Arrange -- PostgreSQL REAL is 4-byte and would round every value
    declared = "REAL"
    # Act
    result = postgres_type_for(declared)
    # Assert
    assert result == "DOUBLE PRECISION"


def test_text_maps_to_text():
    # Arrange
    declared = "TEXT"
    # Act
    result = postgres_type_for(declared)
    # Assert
    assert result == "TEXT"


def test_blob_maps_to_bytea():
    # Arrange
    declared = "BLOB"
    # Act
    result = postgres_type_for(declared)
    # Assert
    assert result == "BYTEA"


def test_numeric_is_left_unconstrained():
    # Arrange -- pinning precision would invent a constraint the source lacked
    declared = "DECIMAL(10,2)"
    # Act
    result = postgres_type_for(declared)
    # Assert
    assert result == "NUMERIC"


# ----------------------------------------------------------------------------
# quote_identifier -- reserved words and case preservation
# ----------------------------------------------------------------------------


def test_quote_identifier_wraps_a_reserved_word():
    # Arrange -- this store already renamed one such column to `grp`
    name = "group"
    # Act
    result = quote_identifier(name)
    # Assert
    assert result == '"group"'


def test_quote_identifier_preserves_case():
    # Arrange -- unquoted identifiers fold to lower case in PostgreSQL
    name = "CamelCase"
    # Act
    result = quote_identifier(name)
    # Assert
    assert result == '"CamelCase"'


def test_quote_identifier_escapes_an_embedded_double_quote():
    # Arrange
    name = 'we"ird'
    # Act
    result = quote_identifier(name)
    # Assert
    assert result == '"we""ird"'


def test_quote_identifier_refuses_a_nul_byte():
    # Arrange
    name = "bad\x00name"
    # Act
    quoter = quote_identifier
    # Assert
    with pytest.raises(DDLTranslationError, match="NUL byte"):
        quoter(name)


# ----------------------------------------------------------------------------
# create_table_ddl
# ----------------------------------------------------------------------------


def test_create_table_ddl_quotes_the_table_name():
    # Arrange
    columns = [Column("id", "TEXT", primary_key=True)]
    # Act
    ddl = create_table_ddl("tasks", columns)
    # Assert
    assert ddl.startswith('CREATE TABLE "tasks" (')


def test_create_table_ddl_emits_the_primary_key_clause():
    # Arrange
    columns = [Column("id", "TEXT", primary_key=True), Column("title", "TEXT")]
    # Act
    ddl = create_table_ddl("tasks", columns)
    # Assert
    assert 'PRIMARY KEY ("id")' in ddl


def test_create_table_ddl_carries_not_null():
    # Arrange
    columns = [Column("title", "TEXT", not_null=True)]
    # Act
    ddl = create_table_ddl("tasks", columns)
    # Assert
    assert '"title" TEXT NOT NULL' in ddl


def test_create_table_ddl_preserves_source_column_order():
    # Arrange -- keeps the generated DDL diffable against the source by eye
    columns = [Column("id", "TEXT"), Column("title", "TEXT"), Column("status", "TEXT")]
    # Act
    ddl = create_table_ddl("tasks", columns)
    # Assert
    assert ddl.index('"id"') < ddl.index('"title"') < ddl.index('"status"')


def test_create_table_ddl_refuses_an_empty_column_list():
    # Arrange -- almost certainly failed introspection, not a column-free table
    columns = []
    # Act
    table = "tasks"
    # Assert
    with pytest.raises(DDLTranslationError, match="no columns"):
        create_table_ddl(table, columns)


# ----------------------------------------------------------------------------
# unstorable_columns -- asks the DATA, not the declaration
# ----------------------------------------------------------------------------


def test_unstorable_columns_flags_an_integer_column_holding_text(mixed_type_db):
    # Arrange -- real SQLite table where n INTEGER also holds 'banana'
    columns = [Column("id", "INTEGER", primary_key=True), Column("n", "INTEGER")]
    # Act
    stored = {"n": _stored_types(mixed_type_db, "t", "n")}
    # Assert
    assert unstorable_columns("t", columns, stored) == ("n",)


def test_unstorable_columns_passes_a_column_whose_content_matches(mixed_type_db):
    # Arrange -- s TEXT holds only text
    columns = [Column("s", "TEXT")]
    # Act
    stored = {"s": _stored_types(mixed_type_db, "t", "s")}
    # Assert
    assert unstorable_columns("t", columns, stored) == ()


def test_unstorable_columns_does_not_treat_null_as_a_mismatch():
    # Arrange -- NULL is storable in any nullable column
    columns = [Column("n", "INTEGER")]
    # Act
    stored = {"n": ["null", "integer"]}
    # Assert
    assert unstorable_columns("t", columns, stored) == ()


def test_unstorable_columns_passes_an_all_null_column():
    # Arrange -- nothing but NULLs establishes no type disagreement
    columns = [Column("n", "INTEGER")]
    # Act
    stored = {"n": ["null"]}
    # Assert
    assert unstorable_columns("t", columns, stored) == ()


def test_unstorable_columns_reports_every_offender_in_one_pass():
    # Arrange -- failing one at a time turns a review into N runs
    columns = [Column("a", "INTEGER"), Column("b", "INTEGER")]
    # Act
    stored = {"a": ["text"], "b": ["blob"]}
    # Assert
    assert unstorable_columns("t", columns, stored) == ("a", "b")


def test_unstorable_columns_accepts_integer_in_a_real_column():
    # Arrange -- PostgreSQL widens int to double without loss
    columns = [Column("x", "REAL")]
    # Act
    stored = {"x": ["integer", "real"]}
    # Assert
    assert unstorable_columns("t", columns, stored) == ()


def test_unstorable_columns_refuses_a_column_the_schema_does_not_have():
    # Arrange -- introspection and content query disagree about the shape
    columns = [Column("a", "TEXT")]
    # Act
    stored = {"ghost": ["text"]}
    # Assert
    with pytest.raises(DDLTranslationError, match="not in the column list"):
        unstorable_columns("t", columns, stored)


# EOF
