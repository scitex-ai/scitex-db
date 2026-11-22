"""Non-mutating duplicate previews on owned SQLite fixtures."""

import hashlib
import sqlite3
import warnings
from contextlib import closing

import pytest

from scitex_db import delete_duplicates, delete_sqlite3_duplicates


@pytest.fixture(params=["preview.db", "preview?#%3f 日本語.db"])
def preview_database(request, tmp_path):
    path = tmp_path / request.param
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY,name TEXT,value REAL NOT NULL,payload BLOB,created_at TEXT);"
            "CREATE INDEX records_name_idx ON records(name);"
            "CREATE TABLE records_temp(marker TEXT NOT NULL);"
            "INSERT INTO records_temp VALUES('preserve this unrelated table');"
            "CREATE TABLE audit(value INTEGER);"
            "CREATE TRIGGER records_update AFTER UPDATE ON records BEGIN INSERT INTO audit VALUES(new.id); END;"
        )
        connection.executemany(
            "INSERT INTO records VALUES(?,?,?,?,?)",
            [(1,"alpha",1.0,b"A","first"),(2,"alpha",1.0,b"B","second"),
             (3,"beta",2.0,b"C","third"),(4,None,3.0,b"D","fourth"),
             (5,None,3.0,b"D","fifth")],
        )
        connection.commit()
    yield path


def _preview_snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        names = {row[1] for row in schema if row[0] == "table"}
        records = connection.execute("SELECT * FROM records ORDER BY id").fetchall()
        collateral = connection.execute("SELECT * FROM records_temp").fetchall() if "records_temp" in names else None
        audit = connection.execute("SELECT * FROM audit").fetchall()
    return hashlib.sha256(path.read_bytes()).hexdigest(), schema, records, collateral, audit


@pytest.mark.parametrize(
    "options,expected",
    [({},(5,2)),({"columns":["name","value"]},(5,2)),({"columns":"name"},(5,2)),
     ({"include_blob":True},(5,1)),({"columns":["id"]},(5,0))],
)
def test_preview_counts_match_sql_grouping(preview_database, options, expected):
    # Arrange
    target = str(preview_database)
    # Act
    actual = delete_sqlite3_duplicates(target, "records", **options)
    # Assert
    assert actual == expected


def test_preview_preserves_database_and_collateral_table(preview_database):
    # Arrange
    before = _preview_snapshot(preview_database)
    # Act
    delete_sqlite3_duplicates(str(preview_database), "records")
    # Assert
    assert _preview_snapshot(preview_database) == before


def test_preview_empty_table_reports_zero_counts(preview_database):
    # Arrange
    with closing(sqlite3.connect(preview_database)) as connection:
        connection.execute("DELETE FROM records")
        connection.commit()
    # Act
    result = delete_sqlite3_duplicates(str(preview_database), "records")
    # Assert
    assert result == (0, 0)


def _legacy_preview(path):
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        result = delete_duplicates(str(path), "records")
    return result, [w.category.__name__ for w in seen]


def test_preview_legacy_alias_retains_warning_and_safety(preview_database):
    # Arrange
    before = _preview_snapshot(preview_database)
    # Act
    result, categories = _legacy_preview(preview_database)
    # Assert
    assert (result, "DeprecationWarning" in categories, _preview_snapshot(preview_database) == before) == ((5, 2), True, True)


@pytest.mark.parametrize("name", ["absent.db", "absent?#%3f 日本語.db"])
def test_preview_missing_database_does_not_create_file(tmp_path, name):
    # Arrange
    path = tmp_path / name
    # Act
    result = delete_sqlite3_duplicates(str(path), "records")
    # Assert
    assert (result, path.exists()) == ((None, None), False)


def test_preview_missing_table_preserves_database(preview_database):
    # Arrange
    before = _preview_snapshot(preview_database)
    # Act
    result = delete_sqlite3_duplicates(str(preview_database), "absent")
    # Assert
    assert (result, _preview_snapshot(preview_database) == before) == ((None, None), True)


def test_preview_invalid_columns_preserve_database(preview_database):
    # Arrange
    before = _preview_snapshot(preview_database)
    # Act
    result = delete_sqlite3_duplicates(str(preview_database), "records", columns=["absent_column"])
    # Assert
    assert (result, _preview_snapshot(preview_database) == before) == ((None, None), True)


def test_preview_malformed_database_preserves_file(preview_database):
    # Arrange
    preview_database.write_bytes(b"This is not a SQLite database.\n")
    before = preview_database.read_bytes()
    # Act
    result = delete_sqlite3_duplicates(str(preview_database), "records")
    # Assert
    assert (result, preview_database.read_bytes() == before) == ((None, None), True)
