"""Exercise provided compression flags on raw dtype/shape fallback frames."""

import sqlite3
from contextlib import closing

import numpy as np
import pytest

from scitex_db import SQLite3


def _records(path, schema, dtype="float32", shape=(2048,), all_raw=False, nulls=None):
    if schema == "native":
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("CREATE TABLE arrays (id INTEGER PRIMARY KEY, data BLOB)")
    else:
        with SQLite3(str(path)) as db:
            db.create_table("arrays", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
    with SQLite3(str(path)) as db:
        for row_id in (1, 2):
            db.save_array("arrays", np.full(shape, row_id, dtype=np.dtype(dtype)), additional_columns={"id": row_id}, compress=row_id == 2 and not all_raw, verbose=False)
        if nulls == "mixed":
            db.execute("UPDATE arrays SET data=NULL WHERE id=2")
        elif nulls == "all":
            db.execute("UPDATE arrays SET data=NULL")
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", order_by="id")


def _call(db, frame, reader, dtype=None, shape=None, explicit=False):
    options = {"columns": ["data"]} if explicit else {}
    if reader == "get_array_dict":
        return db.get_array_dict(frame, dtype=dtype, shape=shape, **options)["data"]
    return db.decode_array_columns(frame, dtype=dtype, shape=shape, **options)["data"].tolist()


def _summary(result):
    if result is None:
        return None
    if isinstance(result, np.ndarray):
        return result.shape, result.dtype.str, result.tobytes()
    return [None if cell is None else (cell.shape, cell.dtype.str, cell.tobytes()) for cell in result]


def _compare(path, frame, reader, dtype, shape, explicit=False, include_flag=True):
    columns = ["data", "data_is_compressed"] if include_flag else ["data"]
    raw = frame[columns].copy()
    with SQLite3(str(path), mode="ro") as db:
        expected = _call(db, frame.copy(deep=True), reader)
        actual = _call(db, raw, reader, np.dtype(dtype), shape, explicit)
    return actual, expected, raw


@pytest.mark.parametrize("schema", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
@pytest.mark.parametrize("shape", [(), (0, 3), (128,), (2048,)])
@pytest.mark.parametrize("explicit", [False, True])
def test_fallback_flag_rows_match_metadata_values(tmp_path, schema, reader, dtype, shape, explicit):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _records(path, schema, dtype, shape)
    # Act
    actual, expected, _ = _compare(path, frame, reader, dtype, shape, explicit)
    # Assert
    assert _summary(actual) == _summary(expected)


@pytest.mark.parametrize("schema", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
def test_fallback_flag_preserves_flag_and_columns(tmp_path, schema, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _records(path, schema)
    expected = ["data", "data_is_compressed"], frame["data_is_compressed"].tolist()
    # Act
    _, _, raw = _compare(path, frame, reader, "float32", (2048,))
    # Assert
    assert (raw.columns.tolist(), raw["data_is_compressed"].tolist()) == expected


@pytest.mark.parametrize("schema", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
def test_fallback_flag_preserves_main_database_bytes(tmp_path, schema, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _records(path, schema)
    before = path.read_bytes()
    # Act
    _compare(path, frame, reader, "float32", (2048,))
    # Assert
    assert path.read_bytes() == before


@pytest.mark.parametrize("schema", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("shape", [(), (2048,)])
def test_fallback_flag_empty_frame_keeps_existing_result(tmp_path, schema, reader, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _records(path, schema, shape=shape).iloc[:0].copy()
    # Act
    actual, expected, _ = _compare(path, frame, reader, "float32", shape)
    # Assert
    assert _summary(actual) == _summary(expected)


@pytest.mark.parametrize("schema", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("shape", [(), (2048,)])
def test_fallback_flag_absent_uses_existing_raw_path(tmp_path, schema, reader, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _records(path, schema, shape=shape, all_raw=True)
    # Act
    actual, expected, _ = _compare(path, frame, reader, "float32", shape, include_flag=False)
    # Assert
    assert _summary(actual) == _summary(expected)


@pytest.mark.parametrize("schema", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("nulls", ["mixed", "all"])
def test_fallback_flag_null_payload_retains_existing_result(tmp_path, schema, reader, nulls):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _records(path, schema, nulls=nulls)
    # Act
    actual, expected, _ = _compare(path, frame, reader, "float32", (2048,))
    # Assert
    assert _summary(actual) == _summary(expected)
