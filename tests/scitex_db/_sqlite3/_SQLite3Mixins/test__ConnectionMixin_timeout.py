"""Native SQLite lock-wait policy follows the configured connection timeout."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db import SQLite3


def _seed(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE signal(value INTEGER)")
        conn.execute("INSERT INTO signal VALUES (42)")


@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
@pytest.mark.parametrize(("timeout", "expected_ms"), [
    (0.0, 0), (0.137, 137), (1.25, 1250), (300.0, 300000),
])
def test_open_timeout_matches_native_busy_policy(tmp_path, mode, timeout, expected_ms):
    # Arrange
    path = tmp_path / "signal.db"
    _seed(path)
    # Act
    with SQLite3(str(path), mode=mode, timeout=timeout) as db:
        observed = (db.conn.execute("PRAGMA busy_timeout").fetchone()[0],
                    db.timeout, db.conn.execute("SELECT * FROM signal").fetchall())
    # Assert
    assert observed == (expected_ms, timeout, [(42,)])


@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
def test_default_timeout_matches_native_busy_policy(tmp_path, mode):
    # Arrange
    path = tmp_path / "signal.db"
    _seed(path)
    # Act
    with SQLite3(str(path), mode=mode) as db:
        observed = (db.conn.execute("PRAGMA busy_timeout").fetchone()[0],
                    db.timeout, db.conn.execute("SELECT * FROM signal").fetchall())
    # Assert
    assert observed == (60000, 60.0, [(42,)])


@pytest.mark.parametrize("mode", ["ro", "rw", "rwc"])
def test_explicit_connect_timeout_survives_reconnect(tmp_path, mode):
    # Arrange
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    _seed(first)
    _seed(second)
    # Act
    with SQLite3(str(first), mode="ro", timeout=0.01) as db:
        db.connect(str(second), mode=mode, timeout=0.137)
        first_busy = db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        db.close()
        db.reconnect()
        observed = {
            "before_reconnect": first_busy,
            "after_reconnect": db.conn.execute("PRAGMA busy_timeout").fetchone()[0],
            "timeout": db.timeout, "mode": db.mode,
            "path": db.conn.execute("PRAGMA database_list").fetchone()[2],
            "rows": db.conn.execute("SELECT * FROM signal").fetchall(),
        }
    # Assert
    assert observed == {
        "before_reconnect": 137, "after_reconnect": 137,
        "timeout": 0.137, "mode": mode, "path": str(second), "rows": [(42,)],
    }
