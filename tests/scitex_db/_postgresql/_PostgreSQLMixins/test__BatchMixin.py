#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._postgresql._PostgreSQLMixins._BatchMixin.

The mixin owns pure helpers that build PostgreSQL INSERT SQL strings,
flatten record dicts into positional parameter tuples, map pandas dtypes
to Postgres column types, and validate dataframe_to_sql's if_exists
choice. These exercise the mixin against real Python data — no live
database, no mocks (STX-NM* / TQ001/TQ002/TQ003/TQ007 clean).
"""

from __future__ import annotations

import pandas as pd
import pytest

# Skip the entire module if psycopg2 is not importable: the
# _PostgreSQLMixins package __init__ pulls in _BlobMixin which `import
# psycopg2` at module load.
pytest.importorskip("psycopg2")

from scitex_db._postgresql._PostgreSQLMixins._BatchMixin import _BatchMixin

# ----------------------------------------------------------------------------
# _prepare_insert_query — pure SQL string builder
# ----------------------------------------------------------------------------


def test_prepare_insert_query_uses_table_name_in_insert_clause():
    # Arrange
    mixin = _BatchMixin()
    record = {"a": 1}
    # Act
    query = mixin._prepare_insert_query("users", record)
    # Assert
    assert query == "INSERT INTO users (a) VALUES (%s)"


def test_prepare_insert_query_orders_columns_by_record_key_order():
    # Arrange
    mixin = _BatchMixin()
    record = {"col1": "v1", "col2": 2, "col3": True}
    # Act
    query = mixin._prepare_insert_query("t", record)
    # Assert
    assert query == "INSERT INTO t (col1, col2, col3) VALUES (%s, %s, %s)"


def test_prepare_insert_query_produces_one_placeholder_per_column():
    # Arrange
    mixin = _BatchMixin()
    record = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    # Act
    query = mixin._prepare_insert_query("t", record)
    # Assert
    assert query.count("%s") == 5


# ----------------------------------------------------------------------------
# _prepare_batch_parameters — record-dict → positional tuple flattening
# ----------------------------------------------------------------------------


def test_prepare_batch_parameters_returns_empty_list_for_no_records():
    # Arrange
    mixin = _BatchMixin()
    # Act
    params = mixin._prepare_batch_parameters([])
    # Assert
    assert params == []


def test_prepare_batch_parameters_returns_tuple_per_record():
    # Arrange
    mixin = _BatchMixin()
    records = [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5, "b": 6}]
    # Act
    params = mixin._prepare_batch_parameters(records)
    # Assert
    assert params == [(1, 2), (3, 4), (5, 6)]


def test_prepare_batch_parameters_orders_values_by_first_record_keys():
    # Arrange
    mixin = _BatchMixin()
    # Second record has keys in a different order; the helper must use
    # the first record's key order to keep column alignment with the
    # INSERT statement built from the same first record.
    records = [
        {"name": "Alice", "age": 25},
        {"age": 30, "name": "Bob"},
    ]
    # Act
    params = mixin._prepare_batch_parameters(records)
    # Assert
    assert params == [("Alice", 25), ("Bob", 30)]


# ----------------------------------------------------------------------------
# _map_dtype_to_postgres — pandas dtype → Postgres column type
# ----------------------------------------------------------------------------


def test_map_dtype_to_postgres_returns_integer_for_int_dtype():
    # Arrange
    mixin = _BatchMixin()
    dtype = pd.Series([1, 2, 3]).dtype
    # Act
    mapped = mixin._map_dtype_to_postgres(dtype)
    # Assert
    assert mapped == "INTEGER"


def test_map_dtype_to_postgres_returns_real_for_float_dtype():
    # Arrange
    mixin = _BatchMixin()
    dtype = pd.Series([1.0, 2.5]).dtype
    # Act
    mapped = mixin._map_dtype_to_postgres(dtype)
    # Assert
    assert mapped == "REAL"


def test_map_dtype_to_postgres_returns_timestamp_for_datetime_dtype():
    # Arrange
    mixin = _BatchMixin()
    dtype = pd.Series(pd.to_datetime(["2024-01-01", "2024-02-01"])).dtype
    # Act
    mapped = mixin._map_dtype_to_postgres(dtype)
    # Assert
    assert mapped == "TIMESTAMP"


def test_map_dtype_to_postgres_returns_boolean_for_bool_dtype():
    # Arrange
    mixin = _BatchMixin()
    dtype = pd.Series([True, False, True]).dtype
    # Act
    mapped = mixin._map_dtype_to_postgres(dtype)
    # Assert
    assert mapped == "BOOLEAN"


def test_map_dtype_to_postgres_returns_text_for_object_dtype():
    # Arrange
    mixin = _BatchMixin()
    dtype = pd.Series(["x", "y", "z"]).dtype
    # Act
    mapped = mixin._map_dtype_to_postgres(dtype)
    # Assert
    assert mapped == "TEXT"


# ----------------------------------------------------------------------------
# dataframe_to_sql — if_exists guard
# ----------------------------------------------------------------------------


def test_dataframe_to_sql_rejects_unknown_if_exists_value():
    # Arrange
    mixin = _BatchMixin()
    df = pd.DataFrame({"a": [1, 2]})
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        mixin.dataframe_to_sql(df, "t", if_exists="bogus")
