"""Native empty-input batches preserve existing table state and controls."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db import SQLite3


def _seed(path):
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY,score INTEGER,label TEXT);"
            "CREATE INDEX preserve_score ON records(score);"
            "INSERT INTO records VALUES(1,50,'seed');"
        )


def _schema(db):
    return db.conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()


def _call(db, method, rows, **kwargs):
    try:
        result = getattr(db, method)("records", rows, **kwargs)
    except Exception as error:
        return type(error).__name__, str(error)
    return None, result


@pytest.fixture(params=["ro", "rw", "rwc"])
def batch_db(tmp_path, request):
    path = tmp_path / "empty.db"
    _seed(path)
    with SQLite3(str(path), mode=request.param) as db:
        yield db


@pytest.mark.parametrize("method", ["insert_many", "replace_many", "update_many"])
def test_empty_input_returns_without_batch_mutation(batch_db, method):
    # Arrange
    schema = _schema(batch_db)
    statements = []
    rows = []
    batch_db.conn.set_trace_callback(statements.append)
    # Act
    try:
        outcome = _call(batch_db, method, rows)
    finally:
        batch_db.conn.set_trace_callback(None)
    observed = batch_db.conn.execute("SELECT * FROM records").fetchall()
    mutations = [sql for sql in statements if sql.lstrip().upper().startswith(("INSERT", "REPLACE", "UPDATE", "DELETE", "CREATE", "DROP"))]
    # Assert
    assert (outcome, observed, _schema(batch_db), mutations, rows) == ((None, None), [(1, 50, "seed")], schema, [], [])


def test_empty_update_with_explicit_columns_remains_a_noop(batch_db):
    # Arrange
    schema = _schema(batch_db)
    # Act
    outcome = _call(batch_db, "update_many", [], columns=["score"])
    observed = batch_db.conn.execute("SELECT * FROM records").fetchall()
    # Assert
    assert (outcome, observed, _schema(batch_db)) == ((None, None), [(1, 50, "seed")], schema)


def test_empty_update_keeps_explicit_invalid_column_refusal(batch_db):
    # Arrange
    schema = _schema(batch_db)
    # Act
    outcome = _call(batch_db, "update_many", [], columns=["missing"])
    observed = batch_db.conn.execute("SELECT * FROM records").fetchall()
    # Assert
    assert (outcome, observed, _schema(batch_db)) == (("ValueError", "No valid columns found"), [(1, 50, "seed")], schema)


@pytest.mark.parametrize("method", ["insert_many", "replace_many", "update_many"])
def test_empty_input_keeps_nonpositive_batch_size_refusal(tmp_path, method):
    # Arrange
    path = tmp_path / "invalid-size.db"
    _seed(path)
    # Act
    with SQLite3(str(path)) as db:
        schema = _schema(db)
        outcome = _call(db, method, [], batch_size=0)
        observed = db.conn.execute("SELECT * FROM records").fetchall()
        observed_schema = _schema(db)
    # Assert
    assert (outcome, observed, observed_schema) == (("ValueError", "Batch size must be positive"), [(1, 50, "seed")], schema)


@pytest.fixture(params=["rw", "rwc"])
def writable_batch(tmp_path, request):
    path = tmp_path / "nonempty.db"
    _seed(path)
    with SQLite3(str(path), mode=request.param) as db:
        yield path, db


def _persisted_rows(path):
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as reader:
        return reader.execute("SELECT * FROM records ORDER BY id").fetchall()


def test_nonempty_insert_keeps_native_write_behavior(writable_batch):
    # Arrange
    path, db = writable_batch
    schema = _schema(db)
    # Act
    outcome = _call(db, "insert_many", [{"id": 2, "score": 20, "label": "new"}])
    observed = _persisted_rows(path)
    # Assert
    assert (outcome, observed, _schema(db)) == ((None, None), [(1, 50, "seed"), (2, 20, "new")], schema)


def test_nonempty_replace_keeps_native_write_behavior(writable_batch):
    # Arrange
    path, db = writable_batch
    schema = _schema(db)
    # Act
    outcome = _call(db, "replace_many", [{"id": 1, "score": 20, "label": "replaced"}])
    observed = _persisted_rows(path)
    # Assert
    assert (outcome, observed, _schema(db)) == ((None, None), [(1, 20, "replaced")], schema)


def test_nonempty_update_keeps_native_write_behavior(writable_batch):
    # Arrange
    path, db = writable_batch
    schema = _schema(db)
    # Act
    outcome = _call(db, "update_many", [{"score": 20}], columns=["score"], where="id=1")
    observed = _persisted_rows(path)
    # Assert
    assert (outcome, observed, _schema(db)) == ((None, None), [(1, 20, "seed")], schema)
