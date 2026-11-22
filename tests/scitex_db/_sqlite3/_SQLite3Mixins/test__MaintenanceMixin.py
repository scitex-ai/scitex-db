"""Native VACUUM INTO copies treat caller filenames as data."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db import SQLite3


@pytest.mark.parametrize(
    "filename",
    ["copy.db", "two words.db", "O'Brien.db", "copy 'quote'.db", "semi';--.db"],
)
def test_vacuum_into_copies_to_the_literal_filename(tmp_path, filename):
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
        db.vacuum(into=str(destination))
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
