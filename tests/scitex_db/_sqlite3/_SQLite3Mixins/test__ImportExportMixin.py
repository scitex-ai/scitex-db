"""Native CSV exports reject invalid bounds before SQL or output changes."""

import csv

import numpy as np
import pytest

from scitex_db import SQLite3


def _refused_export_observation(tmp_path, target, batch_size):
    steps = {"count": 0}

    def vm_budget():
        steps["count"] += 1
        return steps["count"] >= 2000

    with SQLite3(str(tmp_path / "source.db")) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO records VALUES (7, 'alpha')")
        db.conn.commit()
        db.conn.set_progress_handler(vm_budget, 1)
        try:
            try:
                db.save_to_csv("records", str(target), batch_size=batch_size)
            except ValueError as error:
                clear_error = "batch_size must be a positive integer" in str(error)
            else:
                clear_error = False
        finally:
            db.conn.set_progress_handler(None, 0)
        observed = {
            "clear_error": clear_error,
            "output": target.read_bytes() if target.exists() else None,
            "source_rows": db.execute("SELECT * FROM records").fetchall(),
            "sql_steps": steps["count"],
        }
    return observed


@pytest.mark.parametrize("batch_size", [0, -1, False, True, 1.5, "2", None])
def test_invalid_export_batch_does_not_create_output(tmp_path, batch_size):
    # Arrange
    target = tmp_path / "export.csv"
    # Act
    observed = _refused_export_observation(tmp_path, target, batch_size)
    # Assert
    assert observed == {
        "clear_error": True, "output": None,
        "source_rows": [(7, "alpha")], "sql_steps": 0,
    }


@pytest.mark.parametrize("batch_size", [0, -1, False, True, 1.5, "2", None])
def test_invalid_export_batch_preserves_existing_output(tmp_path, batch_size):
    # Arrange
    target = tmp_path / "export.csv"
    before = b"preserve existing output\n"
    target.write_bytes(before)
    # Act
    observed = _refused_export_observation(tmp_path, target, batch_size)
    # Assert
    assert observed == {
        "clear_error": True, "output": before,
        "source_rows": [(7, "alpha")], "sql_steps": 0,
    }


@pytest.mark.parametrize("batch_size,row_count", [(1, 5), pytest.param(np.int64(2), 5, id="numpy-integer-batch"), (10, 5), (2, 0)])
def test_valid_export_batch_preserves_csv_rows(tmp_path, batch_size, row_count):
    # Arrange
    target = tmp_path / "export.csv"
    expected = [{"id": str(i), "value": f"value-{i},quoted"} for i in range(row_count)]
    # Act
    with SQLite3(str(tmp_path / "source.db")) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        for i in range(row_count):
            db.execute("INSERT INTO records VALUES (?, ?)", (i, f"value-{i},quoted"))
        db.conn.commit()
        returned = db.save_to_csv("records", str(target), batch_size=batch_size)
    with target.open(newline="") as stream:
        reader = csv.DictReader(stream)
        rows = sorted(reader, key=lambda row: int(row["id"]))
        fields = reader.fieldnames
    # Assert
    assert (returned, fields, rows) == (None, ["id", "value"], expected)


@pytest.mark.parametrize("size_name", ["batch_size", "chunk_size"])
@pytest.mark.parametrize("bad_size", [0, -1, False, True, 1.5, "2", None])
def test_invalid_import_size_preserves_pending_work(tmp_path, size_name, bad_size):
    # Arrange
    source = tmp_path / "input.csv"
    original_csv = b'value,extra\n"alpha,one",ignored\nbeta,ignored\n'
    source.write_bytes(original_csv)
    sizes = {"batch_size": 1, "chunk_size": 1}
    sizes[size_name] = bad_size
    queries = []
    # Act
    with SQLite3(str(tmp_path / "source.db")) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("CREATE INDEX record_value_idx ON records(value)")
        db.execute("INSERT INTO records VALUES (7, 'seed')")
        db.conn.commit()
        db.execute("INSERT INTO records VALUES (8, 'pending')")
        db.conn.set_trace_callback(queries.append)
        try:
            try:
                db.load_from_csv("records", str(source), if_exists="replace", **sizes)
            except ValueError as error:
                clear_error = f"{size_name} must be a positive integer" in str(error)
            else:
                clear_error = False
        finally:
            db.conn.set_trace_callback(None)
        pending = db.conn.in_transaction
        schema = [(r[1], r[2], r[5]) for r in db.conn.execute("PRAGMA table_info(records)")]
        indexes = db.conn.execute(
            "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name=?", ("records",)
        ).fetchall()
        db.conn.rollback()
        observed = {
            "clear_error": clear_error, "sql_statements": len(queries),
            "pending_preserved": pending, "schema": schema, "indexes": indexes,
            "rows_after_rollback": db.conn.execute("SELECT * FROM records").fetchall(),
            "csv_bytes": source.read_bytes(),
        }
    # Assert
    assert observed == {
        "clear_error": True, "sql_statements": 0, "pending_preserved": True,
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)], "rows_after_rollback": [(7, "seed")],
        "csv_bytes": original_csv,
    }


@pytest.mark.parametrize(
    "batch_size,chunk_size", [(1, 1), (np.int64(2), np.int64(1))]
)
def test_valid_import_sizes_preserve_rows_and_schema(tmp_path, batch_size, chunk_size):
    # Arrange
    source = tmp_path / "input.csv"
    original_csv = b'value,extra\n"alpha,one",ignored\nbeta,ignored\n'
    source.write_bytes(original_csv)
    # Act
    with SQLite3(str(tmp_path / "source.db")) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("CREATE INDEX record_value_idx ON records(value)")
        db.execute("INSERT INTO records VALUES (7, 'seed')")
        db.conn.commit()
        returned = db.load_from_csv(
            "records", str(source), batch_size=batch_size, chunk_size=chunk_size
        )
        observed = {
            "returned": returned,
            "rows": db.conn.execute("SELECT * FROM records ORDER BY id").fetchall(),
            "schema": [(r[1], r[2], r[5]) for r in db.conn.execute("PRAGMA table_info(records)")],
            "indexes": db.conn.execute(
                "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name=?", ("records",)
            ).fetchall(),
            "csv_bytes": source.read_bytes(),
        }
    # Assert
    assert observed == {
        "returned": None, "rows": [(7, "seed"), (8, "alpha,one"), (9, "beta")],
        "schema": [("id", "INTEGER", 1), ("value", "TEXT", 0)],
        "indexes": [("record_value_idx",)], "csv_bytes": original_csv,
    }
