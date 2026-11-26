"""Native row-query failures retain SQLite exception classes and metadata."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db import SQLite3


@pytest.fixture(params=["ro", "rwc"])
def row_db(tmp_path, request):
    path = tmp_path / "rows.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, label TEXT)")
        conn.execute("INSERT INTO records VALUES (42, 'alpha')")
        conn.commit()
    with SQLite3(str(path), mode=request.param) as db:
        yield db


def _error_signature(call):
    try:
        call()
    except sqlite3.Error as error:
        return {
            "type": type(error),
            "args": error.args,
            "sqlite_errorcode": getattr(error, "sqlite_errorcode", None),
            "sqlite_errorname": getattr(error, "sqlite_errorname", None),
        }
    return {"type": None}


@pytest.mark.parametrize("return_as", ["dataframe", "list", "dict"])
@pytest.mark.parametrize(
    ("table", "where", "native_sql"),
    [
        ("missing_table", None, "SELECT * FROM missing_table"),
        ("records", "label =", "SELECT * FROM records WHERE label ="),
    ],
)
def test_get_rows_retains_native_failure_and_keeps_connection_usable(row_db, return_as, table, where, native_sql):
    # Arrange
    native = _error_signature(lambda: row_db.conn.execute(native_sql))
    # Act
    observed = _error_signature(lambda: row_db.get_rows(table, where=where, return_as=return_as))
    remaining = row_db.execute("SELECT id, label FROM records").fetchall()
    # Assert
    assert (observed, native["type"], remaining) == (native, sqlite3.OperationalError, [(42, "alpha")])


@pytest.mark.parametrize(
    ("return_as", "expected"),
    [
        ("dataframe", ("DataFrame", [{"id": 42, "label": "alpha"}])),
        ("list", ("list", [(42, "alpha")])),
        ("dict", ("list", [{"id": 42, "label": "alpha"}])),
    ],
)
def test_get_rows_preserves_successful_result_formats(row_db, return_as, expected):
    # Arrange
    table = "records"
    # Act
    result = row_db.get_rows(table, return_as=return_as)
    normalized = result.to_dict("records") if hasattr(result, "to_dict") else result
    # Assert
    assert (type(result).__name__, normalized) == expected
