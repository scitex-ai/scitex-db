"""Real SQLite checks for file identity and reconnect access policy."""

import sqlite3

import pytest

from scitex_db import SQLite3


_FILENAMES = ["recording?.db", "recording#.db", "recording%3f.db", "日本語 signal.db"]


def _seed(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE signal (sample INTEGER)")
        conn.execute("INSERT INTO signal VALUES (42)")


@pytest.fixture
def reopened_ro_db(tmp_path):
    path = tmp_path / "signal.db"
    _seed(path)
    with SQLite3(str(path), mode="ro", timeout=0.137) as db:
        db.close()
        db.reconnect()
        yield db


@pytest.mark.parametrize("filename", _FILENAMES)
@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
def test_reserved_filename_reads_existing_rows(tmp_path, filename, mode):
    # Arrange
    path = tmp_path / filename
    _seed(path)
    # Act
    with SQLite3(str(path), mode=mode) as db:
        result = db.execute("SELECT sample FROM signal").fetchall()
    # Assert
    assert result == [(42,)]


@pytest.mark.parametrize("filename", _FILENAMES)
@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
def test_reserved_filename_preserves_native_file_identity(tmp_path, filename, mode):
    # Arrange
    path = tmp_path / filename
    _seed(path)
    # Act
    with SQLite3(str(path), mode=mode) as db:
        actual = db.conn.execute("PRAGMA database_list").fetchone()[2]
    # Assert
    assert actual == str(path)


@pytest.mark.parametrize("filename", _FILENAMES)
@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
def test_reserved_filename_does_not_create_other_files(tmp_path, filename, mode):
    # Arrange
    path = tmp_path / filename
    _seed(path)
    # Act
    with SQLite3(str(path), mode=mode):
        pass
    # Assert
    assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize(("pragma", "expected"), [("query_only", 1), ("busy_timeout", 137)])
def test_reconnect_preserves_native_settings(reopened_ro_db, pragma, expected):
    # Arrange
    conn = reopened_ro_db.conn
    # Act
    actual = conn.execute(f"PRAGMA {pragma}").fetchone()[0]
    # Assert
    assert actual == expected


def test_reconnect_rejects_native_writes(reopened_ro_db):
    # Arrange
    conn = reopened_ro_db.conn
    # Act
    ctx = pytest.raises(sqlite3.OperationalError)
    # Assert
    with ctx:
        conn.execute("INSERT INTO signal VALUES (7)")


def test_reconnect_preserves_read_access(reopened_ro_db):
    # Arrange
    db = reopened_ro_db
    # Act
    rows = db.execute("SELECT sample FROM signal").fetchall()
    # Assert
    assert rows == [(42,)]


@pytest.mark.parametrize(("check", "expected"), [("rows", [(42,)]), ("query_only", 1)])
def test_automatic_reconnect_preserves_readonly_policy(tmp_path, check, expected):
    # Arrange
    path = tmp_path / "signal.db"
    _seed(path)
    with SQLite3(str(path), mode="ro") as db:
        db.close()
        # Act: execute calls ensure_connection/reconnect.
        rows = db.execute("SELECT sample FROM signal").fetchall()
        actual = {"rows": rows, "query_only": db.conn.execute("PRAGMA query_only").fetchone()[0]}
        # Assert
        assert actual[check] == expected


@pytest.mark.parametrize("mode", ["ro", "rw"])
def test_reconnect_rejects_missing_database(tmp_path, mode):
    # Arrange
    path = tmp_path / "signal.db"
    _seed(path)
    with SQLite3(str(path), mode=mode) as db:
        db.close()
        path.unlink()
        # Act
        ctx = pytest.raises(sqlite3.OperationalError)
        # Assert
        with ctx:
            db.reconnect()


@pytest.mark.parametrize("mode", ["ro", "rw"])
def test_reconnect_does_not_create_missing_database(tmp_path, mode):
    # Arrange
    path = tmp_path / "signal.db"
    _seed(path)
    with SQLite3(str(path), mode=mode) as db:
        db.close()
        path.unlink()
        # Act
        try:
            db.reconnect()
        except sqlite3.OperationalError:
            pass
        # Assert
        assert not path.exists()


def test_memory_database_keeps_special_semantics():
    # Arrange
    db = SQLite3(":memory:")
    # Act
    with db:
        db.execute("CREATE TABLE signal (sample INTEGER)")
        actual_path = db.conn.execute("PRAGMA database_list").fetchone()[2]
    # Assert
    assert actual_path == ""


@pytest.mark.parametrize("setting", ["file", "query_only", "busy_timeout"])
def test_explicit_connect_updates_reconnect_configuration(tmp_path, setting):
    # Arrange
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    _seed(first)
    _seed(second)
    expected = {"file": str(second), "query_only": 1, "busy_timeout": 137}
    with SQLite3(str(first)) as db:
        db.connect(str(second), mode="ro", timeout=0.137)
        db.close()
        # Act
        db.reconnect()
        actual = {
            "file": db.conn.execute("PRAGMA database_list").fetchone()[2],
            "query_only": db.conn.execute("PRAGMA query_only").fetchone()[0],
            "busy_timeout": db.conn.execute("PRAGMA busy_timeout").fetchone()[0],
        }
        # Assert
        assert actual[setting] == expected[setting]
