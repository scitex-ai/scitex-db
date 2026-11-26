"""Native schema, constraint and rollback controls for explicit duplicate apply."""
import sqlite3
from contextlib import closing

import pytest

from scitex_db import delete_sqlite3_duplicates


@pytest.fixture(params=["apply.db", "apply?#%3f 日本語.db"])
def apply_database(request, tmp_path):
    path = tmp_path / request.param
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT COLLATE NOCASE, value REAL NOT NULL CHECK(value>0), payload BLOB, created_at TEXT);"
            "CREATE INDEX records_name_idx ON records(name);"
            "CREATE TABLE records_temp(marker TEXT NOT NULL); INSERT INTO records_temp VALUES('preserve this table');"
            "CREATE TABLE audit(value INTEGER);"
            "CREATE TRIGGER records_delete AFTER DELETE ON records BEGIN INSERT INTO audit VALUES(old.id); END;"
        )
        connection.executemany("INSERT INTO records VALUES(?,?,?,?,?)", [(1,"alpha",1,b"A","first"),(2,"ALPHA",1,b"B","second"),(3,"beta",2,b"C","third"),(4,None,3,b"D","fourth"),(5,None,3,b"D","fifth")])
    yield path


def _apply_snapshot(path):
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)) as connection:
        schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        names = {row[1] for row in schema if row[0] == "table"}
        rows = connection.execute("SELECT * FROM records ORDER BY id").fetchall()
        collateral = connection.execute("SELECT * FROM records_temp").fetchall() if "records_temp" in names else None
        audit = connection.execute("SELECT value FROM audit ORDER BY value").fetchall()
    return path.read_bytes(), schema, rows, collateral, audit


def _replace_records(path, definition, rows):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TABLE records")
        connection.execute("CREATE TABLE records("+definition+")"+ (" WITHOUT ROWID" if "WITHOUT_ROWID" in rows else ""))
        for statement in rows:
            if statement != "WITHOUT_ROWID":
                connection.execute(statement)


def _constraint_results(path):
    failures = []
    with closing(sqlite3.connect(path)) as connection, connection:
        for statement in ["INSERT INTO records(id,name,value) VALUES(1,'pk',8)","INSERT INTO records(name,value) VALUES('null',NULL)","INSERT INTO records(name,value) VALUES('check',-1)"]:
            try:
                connection.execute(statement)
            except sqlite3.IntegrityError:
                failures.append(True)
            else:
                failures.append(False)
    return failures


@pytest.mark.parametrize("options,expected", [({},(5,2)),({"columns":["name","value"]},(5,2)),({"columns":"name"},(5,2)),({"include_blob":True},(5,1)),({"columns":["id"]},(5,0))])
def test_apply_counts_match_selected_groups(apply_database, options, expected):
    # Arrange
    target = str(apply_database)
    # Act
    result = delete_sqlite3_duplicates(target, "records", dry_run=False, **options)
    # Assert
    assert result == expected


def test_apply_preserves_all_schema_definitions(apply_database):
    # Arrange
    before = _apply_snapshot(apply_database)[1]
    # Act
    delete_sqlite3_duplicates(str(apply_database), "records", dry_run=False)
    # Assert
    assert _apply_snapshot(apply_database)[1] == before


def test_apply_preserves_collateral_temp_table(apply_database):
    # Arrange
    before = _apply_snapshot(apply_database)[3]
    # Act
    delete_sqlite3_duplicates(str(apply_database), "records", dry_run=False)
    # Assert
    assert _apply_snapshot(apply_database)[3] == before


def test_apply_retains_native_pk_notnull_check_constraints(apply_database):
    # Arrange
    target = str(apply_database)
    # Act
    delete_sqlite3_duplicates(target, "records", dry_run=False)
    actual = _constraint_results(apply_database)
    # Assert
    assert actual == [True, True, True]


def test_apply_preserves_autoincrement_sequence(apply_database):
    # Arrange
    target = str(apply_database)
    # Act
    delete_sqlite3_duplicates(target, "records", dry_run=False)
    with closing(sqlite3.connect(apply_database)) as connection, connection:
        connection.execute("INSERT INTO records(name,value) VALUES('gamma',9)")
        identifier = connection.execute("SELECT id FROM records WHERE name='gamma'").fetchone()[0]
    # Assert
    assert identifier == 6


def test_apply_runs_existing_delete_triggers(apply_database):
    # Arrange
    target = str(apply_database)
    # Act
    delete_sqlite3_duplicates(target, "records", dry_run=False)
    # Assert
    assert _apply_snapshot(apply_database)[4] == [(2,), (5,)]


def test_apply_trigger_abort_rolls_back_entire_delete(apply_database):
    # Arrange
    with closing(sqlite3.connect(apply_database)) as connection, connection:
        connection.execute("CREATE TRIGGER refuse_delete BEFORE DELETE ON records WHEN old.id=5 BEGIN SELECT RAISE(ABORT,'refuse delete'); END")
    before = _apply_snapshot(apply_database)
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", dry_run=False)
    # Assert
    assert (result, _apply_snapshot(apply_database)) == ((None, None), before)


def test_apply_foreign_key_restrict_preserves_database(apply_database):
    # Arrange
    with closing(sqlite3.connect(apply_database)) as connection, connection:
        connection.executescript("CREATE TABLE child(record_id INTEGER REFERENCES records(id) ON DELETE RESTRICT); INSERT INTO child VALUES(2);")
    before = _apply_snapshot(apply_database)
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", dry_run=False)
    # Assert
    assert (result, _apply_snapshot(apply_database)) == ((None, None), before)


def test_apply_honors_native_foreign_key_cascade(apply_database):
    # Arrange
    with closing(sqlite3.connect(apply_database)) as connection, connection:
        connection.executescript("CREATE TABLE child(record_id INTEGER REFERENCES records(id) ON DELETE CASCADE); INSERT INTO child VALUES(1),(2),(5);")
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", dry_run=False)
    with closing(sqlite3.connect(apply_database)) as connection:
        children = connection.execute("SELECT record_id FROM child ORDER BY record_id").fetchall()
    # Assert
    assert (result, children) == ((5, 2), [(1,)])


@pytest.mark.parametrize("columns", [["missing_column"], []])
def test_apply_invalid_columns_preserve_database(apply_database, columns):
    # Arrange
    before = _apply_snapshot(apply_database)
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", columns=columns, dry_run=False)
    # Assert
    assert (result, _apply_snapshot(apply_database)) == ((None, None), before)


def test_apply_without_rowid_refuses_without_changes(apply_database):
    # Arrange
    _replace_records(apply_database, "id INTEGER PRIMARY KEY,name TEXT", ["WITHOUT_ROWID","INSERT INTO records VALUES(1,'same'),(2,'same')"])
    before = _apply_snapshot(apply_database)
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", columns="name", dry_run=False)
    # Assert
    assert (result, _apply_snapshot(apply_database)) == ((None, None), before)


def test_apply_shadowed_rowid_aliases_refuse_without_changes(apply_database):
    # Arrange
    _replace_records(apply_database, "id INTEGER PRIMARY KEY,rowid INTEGER,_rowid_ INTEGER,oid INTEGER,name TEXT", ["INSERT INTO records VALUES(1,10,10,10,'same'),(2,20,20,20,'same')"])
    before = _apply_snapshot(apply_database)
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", columns="name", dry_run=False)
    # Assert
    assert (result, _apply_snapshot(apply_database)) == ((None, None), before)


def test_apply_uses_unshadowed_native_rowid_alias(apply_database):
    # Arrange
    _replace_records(apply_database, "id INTEGER PRIMARY KEY,rowid INTEGER,name TEXT", ["INSERT INTO records VALUES(1,100,'same'),(2,-100,'same')"])
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", columns="name", dry_run=False)
    # Assert
    assert (result, _apply_snapshot(apply_database)[2]) == ((2, 1), [(1, 100, "same")])


def test_apply_preserves_negative_and_large_rowids(apply_database):
    # Arrange
    with closing(sqlite3.connect(apply_database)) as connection, connection:
        connection.executescript("UPDATE records SET id=-5 WHERE id=1; UPDATE records SET id=9223372036854775800 WHERE id=2;")
    before = _apply_snapshot(apply_database)[1]
    # Act
    result = delete_sqlite3_duplicates(str(apply_database), "records", dry_run=False)
    # Assert
    assert (result, [row[0] for row in _apply_snapshot(apply_database)[2]], _apply_snapshot(apply_database)[1]) == ((5, 2), [-5, 3, 4], before)


@pytest.mark.parametrize("name", ["absent.db", "absent?#%3f 日本語.db"])
def test_apply_missing_database_keeps_file_absent(tmp_path, name):
    # Arrange
    path = tmp_path / name
    # Act
    result = delete_sqlite3_duplicates(str(path), "records", dry_run=False)
    # Assert
    assert (result, path.exists()) == ((None, None), False)
