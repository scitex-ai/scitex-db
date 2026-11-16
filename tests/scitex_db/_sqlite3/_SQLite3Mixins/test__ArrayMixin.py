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
