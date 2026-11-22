"""Native read-only inspection and missing-file race controls."""

import sqlite3
from contextlib import closing

import pytest

from scitex_db import inspect
from scitex_db._inspect import OptimizedInspector


@pytest.fixture(params=["inspect.db", "inspect?#%3f 日本語.db"])
def inspection_database(request, tmp_path):
    path = tmp_path / request.param
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY, name TEXT, payload BLOB);"
            "CREATE INDEX records_name_idx ON records(name);"
            "CREATE TABLE audit(value INTEGER);"
            "CREATE TRIGGER records_update AFTER UPDATE ON records BEGIN INSERT INTO audit VALUES(new.id); END;"
        )
        connection.executemany("INSERT INTO records VALUES(?,?,?)", [(1, "alpha", b"A"), (2, "beta", b"BC")])
    yield path


def _inspector_error(inspector, statement=None):
    try:
        if statement is None:
            inspector.get_table_names()
        else:
            with inspector.connection() as cursor:
                cursor.execute(statement)
    except sqlite3.OperationalError as error:
        return error.sqlite_errorcode & 255
    return None


@pytest.mark.parametrize("statement", ["CREATE TABLE forbidden(value INTEGER)", "UPDATE records SET name='changed'"])
def test_inspector_connection_rejects_native_writes(inspection_database, statement):
    # Arrange
    before = inspection_database.read_bytes()
    # Act
    with OptimizedInspector(str(inspection_database)) as inspector:
        code = _inspector_error(inspector, statement)
    # Assert
    assert (code, inspection_database.read_bytes()) == (sqlite3.SQLITE_READONLY, before)


def test_inspector_does_not_recreate_removed_database(inspection_database):
    # Arrange
    inspector = OptimizedInspector(str(inspection_database))
    inspection_database.unlink()
    # Act
    with inspector:
        code = _inspector_error(inspector)
    # Assert
    assert (code, inspection_database.exists()) == (sqlite3.SQLITE_CANTOPEN, False)


def test_inspector_reopen_does_not_create_database(inspection_database):
    # Arrange
    inspector = OptimizedInspector(str(inspection_database))
    inspector.get_table_names()
    inspector.close()
    inspection_database.unlink()
    # Act
    with inspector:
        code = _inspector_error(inspector)
    # Assert
    assert (code, inspection_database.exists()) == (sqlite3.SQLITE_CANTOPEN, False)


def test_public_inspect_preserves_metadata_and_bytes(inspection_database):
    # Arrange
    before = inspection_database.read_bytes()
    # Act
    tables = inspect(str(inspection_database), table_names=["records"], sample_size=1, verbose=False)
    # Assert
    assert (len(tables), tables[0]["table_name"], tables[0]["row_count"], tables[0]["is_approximate"], tables[0]["sample_data"], tables[0]["columns"][0]["pk"], inspection_database.read_bytes()) == (1, "records", 2, False, [{"id": 1, "name": "alpha", "payload": "<BLOB 1 bytes>"}], True, before)


def test_inspector_reuses_connection_for_native_reads(inspection_database):
    # Arrange
    before = inspection_database.read_bytes()
    # Act
    with OptimizedInspector(str(inspection_database)) as inspector:
        with inspector.connection() as first:
            rows = first.execute("SELECT name FROM records ORDER BY id").fetchall()
        with inspector.connection() as second:
            same_cursor = first is second
    # Assert
    assert (same_cursor, [row[0] for row in rows], inspection_database.read_bytes()) == (True, ["alpha", "beta"], before)


def test_public_inspect_missing_path_keeps_file_absent(inspection_database):
    # Arrange
    inspection_database.unlink()
    # Act
    try:
        inspect(str(inspection_database), verbose=False)
    except FileNotFoundError as error:
        message = str(error)
    else:
        message = ""
    # Assert
    assert (str(inspection_database) in message, inspection_database.exists()) == (True, False)
