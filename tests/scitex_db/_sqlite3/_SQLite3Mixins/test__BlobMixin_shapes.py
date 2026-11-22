"""Real SQLite NumPy-BLOB shape metadata controls; no object-format changes."""

from __future__ import annotations

import numpy as np
import pytest

from scitex_db import SQLite3


def _seed(path, array, compress=False, shape=None):
    with SQLite3(str(path)) as db:
        db.save_blob("blobs", array, key="array", compress=compress)
        if shape is not None:
            db.execute("UPDATE blobs SET data_type = ? WHERE key = ?",
                       (f"ndarray:{array.dtype}:{shape}", "array"))
            db.commit()


def _load(path, keyed):
    with SQLite3(str(path), mode="ro") as db:
        result = db.load_blob("blobs", key="array" if keyed else None)
    return result if keyed else result["array"]


@pytest.mark.parametrize("keyed", [False, True])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("shape", [(), (0,), (4,), (2, 3), (1200,)])
def test_numpy_blob_shape_round_trip_preserves_values(tmp_path, keyed, compress, shape):
    # Arrange
    expected = np.arange(np.prod(shape, dtype=int), dtype=np.int16).reshape(shape)
    path = tmp_path / "blob.db"
    _seed(path, expected, compress=compress)
    # Act
    actual = _load(path, keyed)
    # Assert
    assert (actual.dtype, actual.shape, actual.tobytes()) == (
        expected.dtype, expected.shape, expected.tobytes()
    )


def _expression(marker):
    return f"(__import__('pathlib').Path({str(marker)!r}).write_text('executed'), (4,))[1]"


@pytest.mark.parametrize("keyed", [False, True])
def test_numpy_blob_shape_expression_is_rejected(tmp_path, keyed):
    # Arrange
    path = tmp_path / "blob.db"
    _seed(path, np.arange(4, dtype=np.int16), shape=_expression(tmp_path / "marker"))
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        _load(path, keyed)


@pytest.mark.parametrize("keyed", [False, True])
def test_numpy_blob_shape_metadata_does_not_execute_python(tmp_path, keyed):
    # Arrange
    path = tmp_path / "blob.db"
    marker = tmp_path / "marker"
    _seed(path, np.arange(4, dtype=np.int16), shape=_expression(marker))
    # Act
    try:
        _load(path, keyed)
    except ValueError:
        pass
    # Assert
    assert not marker.exists()
