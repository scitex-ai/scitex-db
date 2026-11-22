"""Native VACUUM INTO copies treat caller filenames as data."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db import SQLite3


@pytest.mark.parametrize(
    "filename",
    ["copy.db", "two words.db", "O'Brien.db", "copy 'quote'.db", "semi';--.db"],
)
@pytest.mark.parametrize("as_path", [False, True])
def test_vacuum_into_copies_to_the_literal_filename(tmp_path, filename, as_path):
    # Arrange
    source = tmp_path / "source.db"
    destination = tmp_path / filename
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.executescript(
            "CREATE TABLE readings (id INTEGER PRIMARY KEY, value TEXT);"
            "CREATE INDEX reading_value ON readings(value);"
            "INSERT INTO readings VALUES (1, 'alpha'), (2, 'beta');"
            "PRAGMA user_version = 7;"
        )
    expected_rows = [(1, "alpha"), (2, "beta")]
    # Act
    with SQLite3(str(source), mode="rw") as db:
        db.vacuum(into=destination if as_path else str(destination))
        source_rows = db.execute("SELECT * FROM readings ORDER BY id").fetchall()
    with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)) as conn:
        observed = {
            "rows": conn.execute("SELECT * FROM readings ORDER BY id").fetchall(),
            "index": conn.execute(
                "SELECT name FROM sqlite_schema WHERE type='index'"
            ).fetchall(),
            "version": conn.execute("PRAGMA user_version").fetchone()[0],
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "source_rows": source_rows,
            "files": sorted(path.name for path in tmp_path.iterdir()),
        }
    # Assert
    assert observed == {
        "rows": expected_rows,
        "index": [("reading_value",)],
        "version": 7,
        "integrity": "ok",
        "source_rows": expected_rows,
        "files": sorted(["source.db", filename]),
    }


@pytest.mark.parametrize("error_type", [None, ValueError, RuntimeError])
def test_backup_closes_destination_after_callback(tmp_path, error_type):
    # Arrange
    import sys

    source = tmp_path / "source.db"
    target = tmp_path / "backup.db"
    destinations = []
    progress_calls = []
    observation = {"active": False, "target": False}

    def observe_connection(event, args):
        if not observation["active"]:
            return
        if event == "sqlite3.connect":
            observation["target"] = args[0] == str(target)
        elif event == "sqlite3.connect/handle" and observation["target"]:
            destinations.append(args[0])
            observation["target"] = False

    def progress(copied, total):
        progress_calls.append((copied, total))
        if error_type is not None:
            raise error_type("intentional callback failure")

    # Act
    with SQLite3(str(source)) as db:
        db.execute("CREATE TABLE readings (id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO readings VALUES (7)")
        db.conn.commit()
        sys.addaudithook(observe_connection)
        observation["active"] = True
        try:
            db.backup(str(target), pages=1, progress=progress)
        except ValueError as error:
            wrapped = str(error).startswith("Failed to create backup:")
        else:
            wrapped = False
        finally:
            observation["active"] = False
        try:
            destinations[0].execute("SELECT 1")
        except sqlite3.ProgrammingError:
            closed = True
        else:
            closed = False
        finally:
            for connection in destinations:
                connection.close()
        observed = {
            "destination_closed": closed,
            "native_connections": all(type(c) is sqlite3.Connection for c in destinations),
            "connections": len(destinations),
            "callback_seen": bool(progress_calls),
            "wrapped_error": wrapped,
            "source_rows": db.execute("SELECT id FROM readings").fetchall(),
        }
        destinations.clear()
    # Assert
    assert observed == {
        "destination_closed": True,
        "native_connections": True,
        "connections": 1,
        "callback_seen": True,
        "wrapped_error": error_type is not None,
        "source_rows": [(7,)],
    }
