"""Inspect native table names literally without changing the database."""
from contextlib import closing
import sqlite3

import pytest

from scitex_db import inspect
from scitex_db._inspect import OptimizedInspector


TABLE_NAMES = [
    "ordinary", "日本語", "order", "with space", 'double"quote',
    "single'quote", "semi;-- comment", "main.ordinary", "samples WHERE 0 --",
]


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


@pytest.fixture(params=["tables.db", "tables?#%3f 日本語.db"])
def named_database(request, tmp_path):
    path = tmp_path / request.param
    with closing(sqlite3.connect(path)) as connection, connection:
        for name in TABLE_NAMES:
            table = _identifier(name)
            connection.execute(
                f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, payload BLOB, '
                '"label""text" TEXT NOT NULL DEFAULT \'untitled\')'
            )
            connection.executemany(
                f'INSERT INTO {table} VALUES (?, ?, ?)',
                [(1, b"AB", name), (2, b"", "second")],
            )
    yield path


@pytest.mark.parametrize("name", TABLE_NAMES)
def test_metadata_preserves_literal_table_and_column_names(named_database, name):
    # Arrange
    before = named_database.read_bytes()
    # Act
    with OptimizedInspector(str(named_database)) as inspector:
        info = inspector.get_table_info_batch([name])[name]
    # Assert
    assert (info, named_database.read_bytes()) == ([
        {"cid": 0, "name": "id", "type": "INTEGER", "notnull": 0, "default": None, "pk": True},
        {"cid": 1, "name": "payload", "type": "BLOB", "notnull": 0, "default": None, "pk": False},
        {"cid": 2, "name": 'label"text', "type": "TEXT", "notnull": 1, "default": "'untitled'", "pk": False},
    ], before)


@pytest.mark.parametrize("name", TABLE_NAMES)
@pytest.mark.parametrize("skip_blob", [False, True])
def test_batch_samples_and_exact_counts_use_literal_tables(named_database, name, skip_blob):
    # Arrange
    before = named_database.read_bytes()
    # Act
    with OptimizedInspector(str(named_database)) as inspector:
        stats = inspector.get_table_stats_batch(
            [name], sample_size=1, skip_blob_content=skip_blob
        )[name]
    # Assert
    assert (stats["row_count"], stats["is_approximate"], stats["columns"],
            tuple(stats["sample_data"][0]), named_database.read_bytes()) == (
        2, False, ["id", "payload", 'label"text'],
        (1, "<BLOB 2 bytes>" if skip_blob else b"AB", name), before
    )


def test_default_discovery_inspects_every_native_table(named_database):
    # Arrange
    before = named_database.read_bytes()
    # Act
    result = inspect(str(named_database), sample_size=1, verbose=False)
    # Assert
    assert ({table["table_name"] for table in result},
            all(table["row_count"] == 2 for table in result),
            all(table["sample_data"] == [
                {"id": 1, "payload": "<BLOB 2 bytes>", 'label"text': table["table_name"]}
            ] for table in result), named_database.read_bytes()) == (
        set(TABLE_NAMES), True, True, before
    )


def test_selected_table_order_and_skip_count_are_preserved(named_database):
    names = ["single'quote", 'double"quote', "order"]
    # Arrange
    before = named_database.read_bytes()
    # Act
    result = inspect(str(named_database), table_names=names, sample_size=0,
                     skip_count=True, verbose=False)
    # Assert
    assert ([table["table_name"] for table in result],
            all((table["row_count"], table["is_approximate"], table["sample_data"])
                == ("Not counted", None, []) for table in result),
            named_database.read_bytes()) == (names, True, before)


@pytest.mark.parametrize("name", ["ordinary WHERE 0 --", "ordinary; DROP TABLE ordinary;--"])
def test_missing_sql_looking_name_cannot_select_existing_table(named_database, name):
    # Arrange
    before = named_database.read_bytes()
    # Act
    with OptimizedInspector(str(named_database)) as inspector:
        try:
            inspector.get_table_stats_batch([name])
        except sqlite3.OperationalError as exception:
            error = str(exception)
        else:
            error = None
        remaining = set(inspector.get_table_names())
    # Assert
    assert (error is not None and "no such table" in error,
            remaining, named_database.read_bytes()) == (True, set(TABLE_NAMES), before)
