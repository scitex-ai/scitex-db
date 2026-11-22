"""Native CSV source failures preserve caller transaction ownership."""

from scitex_db import SQLite3


def _failed_import_observation(tmp_path, csv_path):
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
                db.load_from_csv(
                    "records", str(csv_path), if_exists="replace", batch_size=1, chunk_size=1
                )
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
            "sql_statements": len(queries), "pending_preserved": pending,
            "rows_after_rollback": db.conn.execute("SELECT * FROM records").fetchall(),
            "schema": [(r[1], r[2], r[5]) for r in db.conn.execute("PRAGMA table_info(records)")],
            "indexes": db.conn.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name=?", ("records",)
            ).fetchall(),
        }
    return observed


def test_missing_import_source_preserves_pending_work(tmp_path):
    # Arrange
    source = tmp_path / "missing.csv"
    # Act
    observed = _failed_import_observation(tmp_path, source)
    # Assert
    assert observed == {
        "error": "FileNotFoundError", "prefix": "CSV file not found",
        "sql_statements": 0, "pending_preserved": True,
        "rows_after_rollback": [(7, "seed")],
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)],
    }


def test_empty_import_source_preserves_pending_work(tmp_path):
    # Arrange
    source = tmp_path / "empty.csv"
    source.write_bytes(b"")
    # Act
    observed = _failed_import_observation(tmp_path, source)
    # Assert
    assert observed == {
        "error": "ValueError", "prefix": "Failed to import from CSV",
        "sql_statements": 0, "pending_preserved": True,
        "rows_after_rollback": [(7, "seed")],
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)],
    }


def test_directory_import_source_preserves_pending_work(tmp_path):
    # Arrange
    source = tmp_path / "input-directory"
    source.mkdir()
    # Act
    observed = _failed_import_observation(tmp_path, source)
    # Assert
    assert observed == {
        "error": "ValueError", "prefix": "Failed to import from CSV",
        "sql_statements": 0, "pending_preserved": True,
        "rows_after_rollback": [(7, "seed")],
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)],
    }
