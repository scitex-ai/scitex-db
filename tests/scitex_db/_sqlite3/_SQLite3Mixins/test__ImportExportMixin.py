"""Native CSV exports reject invalid bounds before SQL or output changes."""

import csv

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


@pytest.mark.parametrize("batch_size,row_count", [(1, 5), (2, 5), (10, 5), (2, 0)])
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
