"""Invalid batch sizes must not start SQL or commit pending caller writes."""

from contextlib import closing
import sqlite3

import numpy as np
import pytest

from scitex_db import SQLite3


_INVALID = [0, -1, True, False, 1.5, "2", None, np.float64(2.0), np.bool_(True)]


def _seed(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY,score INTEGER,label TEXT);"
            "CREATE INDEX preserve_score ON records(score);"
            "INSERT INTO records VALUES(1,50,'seed');"
        )


def _schema(db):
    return db.conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()


def _persisted(path):
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as reader:
        return reader.execute("SELECT * FROM records ORDER BY id").fetchall()


def _refusal(db, method, rows, size):
    try:
        getattr(db, method)("records", rows, batch_size=size)
    except Exception as error:
        return type(error).__name__, "batch size" in str(error).replace("_", " ").lower()
    return None, False


@pytest.mark.parametrize("method", ["insert_many", "replace_many", "update_many"])
@pytest.mark.parametrize("size", _INVALID, ids=["zero", "negative", "true", "false", "float", "string", "none", "numpy-float", "numpy-bool"])
def test_invalid_size_preserves_pending_work_without_SQL(tmp_path, method, size):
    # Arrange
    path = tmp_path / "invalid.db"
    _seed(path)
    rows = [{"id": 2, "score": 20, "label": "new"}]
    with SQLite3(str(path), autocommit=False) as db:
        schema = _schema(db)
        db.execute("INSERT INTO records VALUES(9,90,'pending')")
        trace = []
        db.conn.set_trace_callback(trace.append)
        # Act
        try:
            outcome = _refusal(db, method, rows, size)
        finally:
            db.conn.set_trace_callback(None)
        still_pending = db.conn.in_transaction
        visible = db.conn.execute("SELECT * FROM records ORDER BY id").fetchall()
        durable = _persisted(path)
        observed_schema = _schema(db)
        db.rollback()
    after_rollback = _persisted(path)
    # Assert
    assert (outcome, trace, still_pending, visible, durable, after_rollback, observed_schema, rows) == (("ValueError", True), [], True, [(1, 50, "seed"), (9, 90, "pending")], [(1, 50, "seed")], [(1, 50, "seed")], schema, [{"id": 2, "score": 20, "label": "new"}])


@pytest.fixture
def batch_db(tmp_path):
    path = tmp_path / "positive.db"
    _seed(path)
    with SQLite3(str(path)) as db:
        yield path, db


@pytest.mark.parametrize("size", [2, np.int64(2)], ids=["python", "numpy"])
def test_positive_insert_size_preserves_rows_and_schema(batch_db, size):
    # Arrange
    path, db = batch_db
    schema = _schema(db)
    rows = [{"id": n, "score": n * 10, "label": "new"} for n in [2, 3, 4]]
    # Act
    result = db.insert_many("records", rows, batch_size=size)
    observed = _persisted(path)
    # Assert
    assert (result, observed, _schema(db)) == (None, [(1, 50, "seed"), (2, 20, "new"), (3, 30, "new"), (4, 40, "new")], schema)


@pytest.mark.parametrize("size", [2, np.int64(2)], ids=["python", "numpy"])
def test_positive_replace_size_preserves_rows_and_schema(batch_db, size):
    # Arrange
    path, db = batch_db
    schema = _schema(db)
    rows = [{"id": n, "score": n * 10, "label": "replaced"} for n in [1, 2, 3]]
    # Act
    result = db.replace_many("records", rows, batch_size=size)
    observed = _persisted(path)
    # Assert
    assert (result, observed, _schema(db)) == (None, [(1, 10, "replaced"), (2, 20, "replaced"), (3, 30, "replaced")], schema)


@pytest.mark.parametrize("size", [2, np.int64(2)], ids=["python", "numpy"])
def test_positive_update_size_preserves_rows_and_schema(batch_db, size):
    # Arrange
    path, db = batch_db
    schema = _schema(db)
    # Act
    result = db.update_many("records", [{"score": n} for n in [20, 30, 40]], columns=["score"], where="id=1", batch_size=size)
    observed = _persisted(path)
    # Assert
    assert (result, observed, _schema(db)) == (None, [(1, 40, "seed")], schema)
