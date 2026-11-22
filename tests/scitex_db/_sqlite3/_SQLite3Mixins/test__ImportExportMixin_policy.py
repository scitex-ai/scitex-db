"""Native CSV import policy preconditions and supported-policy controls."""

import pytest

from scitex_db import SQLite3


def _policy_refusal(tmp_path, source, policy):
    queries = []
    with SQLite3(str(tmp_path / "source.db")) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("CREATE INDEX record_value_idx ON records(value)")
        db.execute("INSERT INTO records VALUES (7, 'seed')")
        db.conn.commit()
        db.execute("INSERT INTO records VALUES (8, 'pending')")
        db.conn.set_trace_callback(queries.append)
        try:
            try:
                db.load_from_csv("records", str(source), if_exists=policy,
                                 batch_size=1, chunk_size=1)
            except (FileNotFoundError, ValueError) as error:
                error_kind = type(error).__name__
                error_prefix = str(error).split(": ", 1)[0]
            else:
                error_kind = None
                error_prefix = None
        finally:
            db.conn.set_trace_callback(None)
        pending = db.conn.in_transaction
        db.conn.rollback()
        observed = {
            "error": error_kind, "prefix": error_prefix,
            "SQL": len(queries), "pending": pending,
            "rows": db.conn.execute("SELECT * FROM records").fetchall(),
            "schema": [(r[1], r[2], r[5]) for r in db.conn.execute("PRAGMA table_info(records)")],
            "indexes": db.conn.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name=?", ("records",)
            ).fetchall(),
        }
    return observed


@pytest.mark.parametrize("policy", [
    pytest.param(None, id="none"), pytest.param(False, id="bool"),
    pytest.param(0, id="zero"), pytest.param("", id="empty"),
    pytest.param("Append", id="case"), pytest.param("invalid", id="unknown"),
    pytest.param(["append"], id="list"), pytest.param({"append"}, id="set"),
])
def test_invalid_import_policy_preserves_pending_work(tmp_path, policy):
    # Arrange
    source = tmp_path / "input.csv"
    content = b'value,extra\n"alpha,one",ignored\nbeta,ignored\n'
    source.write_bytes(content)
    # Act
    observed = _policy_refusal(tmp_path, source, policy)
    # Assert
    assert (observed, source.read_bytes()) == ({
        "error": "ValueError", "prefix": "Failed to import from CSV",
        "SQL": 0, "pending": True, "rows": [(7, "seed")],
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)],
    }, content)


def test_invalid_import_policy_precedes_missing_source(tmp_path):
    # Arrange
    source = tmp_path / "missing.csv"
    # Act
    observed = _policy_refusal(tmp_path, source, "invalid")
    # Assert
    assert observed == {
        "error": "ValueError", "prefix": "Failed to import from CSV",
        "SQL": 0, "pending": True, "rows": [(7, "seed")],
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)],
    }


def _supported_policy(tmp_path, policy):
    source = tmp_path / "input.csv"
    content = b'value,extra\n"alpha,one",ignored\nbeta,ignored\n'
    source.write_bytes(content)
    with SQLite3(str(tmp_path / "source.db")) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO records VALUES (7, 'seed')")
        db.conn.commit()
        try:
            db.load_from_csv("records", str(source), if_exists=policy,
                             batch_size=1, chunk_size=1)
        except ValueError as error:
            existing_table_refusal = "already exists" in str(error)
        else:
            existing_table_refusal = False
        rows = db.conn.execute("SELECT value FROM records").fetchall()
    return rows, existing_table_refusal, source.read_bytes() == content


def test_append_import_policy_retains_seed_and_all_chunks(tmp_path):
    # Arrange
    policy = "append"
    # Act
    observed = _supported_policy(tmp_path, policy)
    # Assert
    assert observed == ([("seed",), ("alpha,one",), ("beta",)], False, True)


def test_replace_import_policy_retains_all_chunks(tmp_path):
    # Arrange
    policy = "replace"
    # Act
    observed = _supported_policy(tmp_path, policy)
    # Assert
    assert observed == ([("alpha,one",), ("beta",)], False, True)


def test_fail_import_policy_refuses_existing_table(tmp_path):
    # Arrange
    policy = "fail"
    # Act
    observed = _supported_policy(tmp_path, policy)
    # Assert
    assert observed == ([("seed",)], True, True)
