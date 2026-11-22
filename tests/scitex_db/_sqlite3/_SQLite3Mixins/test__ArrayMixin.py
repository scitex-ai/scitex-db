"""Exercise stored shape parsing against actual SQLite array records."""

import numpy as np
import pytest

from scitex_db import SQLite3


def _seed(db_path, array, compress=False, shape=None):
    with SQLite3(str(db_path)) as db:
        db.create_table("arrays", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
        db.save_array("arrays", array, additional_columns={"id": 1}, compress=compress, verbose=False)
        if shape is not None:
            db.execute("UPDATE arrays SET data_shape = ? WHERE id = 1", (shape,))


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("shape", [(), (0, 3), (2, 3), (2000,)])
def test_literal_shape_preserves_array_values(tmp_path, compress, shape):
    # Arrange
    expected = np.arange(np.prod(shape, dtype=int), dtype=np.float32).reshape(shape)
    path = tmp_path / "arrays.db"
    _seed(path, expected, compress=compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_array("arrays", "data", verbose=False)[0]
    # Assert
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("compress", [False, True])
def test_literal_shape_preserves_array_dtype(tmp_path, compress):
    # Arrange
    expected = np.arange(2000, dtype=np.int16)
    path = tmp_path / "arrays.db"
    _seed(path, expected, compress=compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_arrays("arrays", ["data"], verbose=False)["data"]
    # Assert
    assert actual.dtype == expected.dtype


@pytest.mark.parametrize("shape", ["(2, 3)", "[2, 3]"])
def test_literal_legacy_shape_forms_load(tmp_path, shape):
    # Arrange
    expected = np.arange(6).reshape(2, 3)
    path = tmp_path / "arrays.db"
    _seed(path, expected, shape=shape)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_array("arrays", "data", verbose=False)[0]
    # Assert
    assert np.array_equal(actual, expected)


def _expression(marker):
    return f"(__import__('pathlib').Path({str(marker)!r}).write_text('executed'), (4,))[1]"


def test_shape_expression_is_rejected(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    _seed(path, np.arange(4), shape=_expression(tmp_path / "marker"))
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        with SQLite3(str(path), mode="ro") as db:
            db.load_arrays("arrays", ["data"], verbose=False)


def test_shape_metadata_does_not_execute_python(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    marker = tmp_path / "marker"
    _seed(path, np.arange(4), shape=_expression(marker))
    # Act
    with SQLite3(str(path), mode="ro") as db:
        try:
            db.load_array("arrays", "data", verbose=False)
        except ValueError:
            pass
    # Assert
    assert not marker.exists()


def _helper_frame(path, array, shape=None, compress=False):
    _seed(path, array, compress=compress, shape=shape)
    columns = ["data", "data_dtype", "data_shape"]
    if compress:
        columns.append("data_is_compressed")
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", columns=columns, return_as="dataframe")


def _read_helper(path, frame, reader):
    with SQLite3(str(path), mode="ro") as db:
        if reader == "binary_to_array":
            row = frame.iloc[0]
            return db.binary_to_array(
                row["data"], row["data_dtype"], row["data_shape"],
                compressed=row.get("data_is_compressed") in [1, "1", True],
            )
        if reader == "get_array_dict":
            return db.get_array_dict(frame, columns=["data"])["data"][0]
        return db.decode_array_columns(frame, columns=["data"])["data"].iloc[0]


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("shape", ["(4,)", "[4]", "4"])
def test_helper_literal_shape_preserves_values(tmp_path, reader, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.arange(4, dtype=np.float32)
    frame = _helper_frame(path, expected, shape=shape)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
def test_helper_preserves_existing_dtype_conversion(tmp_path, reader, dtype):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _helper_frame(path, np.arange(4, dtype=dtype))
    expected_dtype = np.dtype(dtype).newbyteorder("=") if reader == "get_array_dict" else np.dtype(dtype)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert actual.dtype == expected_dtype


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
def test_helper_shape_expression_is_rejected(tmp_path, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _helper_frame(path, np.arange(4), shape=_expression(tmp_path / "marker"))
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        _read_helper(path, frame, reader)


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
def test_helper_shape_metadata_does_not_execute_python(tmp_path, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    marker = tmp_path / "marker"
    frame = _helper_frame(path, np.arange(4), shape=_expression(marker))
    # Act
    try:
        _read_helper(path, frame, reader)
    except ValueError:
        pass
    # Assert
    assert not marker.exists()


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("shape", [(), (0, 3), (2, 3), (2000,)])
def test_binary_helper_preserves_native_payload(tmp_path, compress, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.arange(np.prod(shape, dtype=int), dtype=np.float32).reshape(shape)
    frame = _helper_frame(path, expected, compress=compress)
    # Act
    actual = _read_helper(path, frame, "binary_to_array")
    # Assert
    assert np.array_equal(actual, expected)


def test_binary_helper_compressed_shape_expression_is_rejected(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    expression = _expression(tmp_path / "marker").replace("(4,)", "(2000,)")
    frame = _helper_frame(path, np.arange(2000), shape=expression, compress=True)
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        _read_helper(path, frame, "binary_to_array")


def test_binary_helper_compressed_metadata_does_not_execute_python(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    marker = tmp_path / "marker"
    expression = _expression(marker).replace("(4,)", "(2000,)")
    frame = _helper_frame(path, np.arange(2000), shape=expression, compress=True)
    # Act
    try:
        _read_helper(path, frame, "binary_to_array")
    except ValueError:
        pass
    # Assert
    assert not marker.exists()
