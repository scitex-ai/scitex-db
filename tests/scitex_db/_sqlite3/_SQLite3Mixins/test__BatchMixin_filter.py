"""Native conditional batches can legitimately select no input rows."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db import SQLite3


_ROWS = [{"id": 2, "score": 1, "label": "low"}, {"id": 3, "score": 20, "label": "high"}]


def _seed(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY,score INTEGER,label TEXT);"
            "CREATE INDEX preserve_score ON records(score);"
            "INSERT INTO records VALUES(1,50,'seed');"
        )


def _schema(db):
    return db.conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()


def _call(db, method, predicate):
    try:
        result = getattr(db, method)("records", [dict(row) for row in _ROWS], where=predicate)
    except Exception as error:
        return type(error).__name__, None
    return None, result


@pytest.fixture(params=["ro", "rwc"])
def batch_db(tmp_path, request):
    path = tmp_path / "batch.db"
    _seed(path)
    with SQLite3(str(path), mode=request.param) as db:
        yield db


@pytest.mark.parametrize("method", ["insert_many", "replace_many"])
@pytest.mark.parametrize("predicate", ["score > 1000", "id < 0", "label = 'not present'"])
def test_batch_with_no_matching_input_returns_without_data_writes(batch_db, method, predicate):
    # Arrange
    schema = _schema(batch_db)
    statements = []
    batch_db.conn.set_trace_callback(statements.append)
    # Act
    try:
        outcome = _call(batch_db, method, predicate)
    finally:
        batch_db.conn.set_trace_callback(None)
    writes = [sql for sql in statements if sql.lstrip().upper().startswith(("INSERT", "REPLACE", "UPDATE", "DELETE", "DROP", "CREATE"))]
    rows = batch_db.conn.execute("SELECT * FROM records").fetchall()
    # Assert
    assert (outcome, rows, _schema(batch_db), writes) == ((None, None), [(1, 50, "seed")], schema, [])


@pytest.mark.parametrize("method", ["insert_many", "replace_many"])
def test_matching_input_still_writes_only_selected_rows(tmp_path, method):
    # Arrange
    path = tmp_path / "positive.db"
    _seed(path)
    # Act
    with SQLite3(str(path)) as db:
        schema = _schema(db)
        outcome = _call(db, method, "score > 10")
        rows = db.conn.execute("SELECT * FROM records ORDER BY id").fetchall()
        observed_schema = _schema(db)
    # Assert
    assert (outcome, rows, observed_schema) == ((None, None), [(1, 50, "seed"), (3, 20, "high")], schema)


@pytest.mark.parametrize("method", ["insert_many", "replace_many"])
def test_matching_input_keeps_native_readonly_refusal(tmp_path, method):
    # Arrange
    path = tmp_path / "readonly.db"
    _seed(path)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        schema = _schema(db)
        outcome = _call(db, method, "score > 10")
        rows = db.conn.execute("SELECT * FROM records").fetchall()
        observed_schema = _schema(db)
    # Assert
    assert (outcome, rows, observed_schema) == (("ValueError", None), [(1, 50, "seed")], schema)
