"""Read BLOB rows from real standard and legacy SQLite schemas."""

from __future__ import annotations

import pytest

from scitex_db import SQLite3


def _seed(path, id_column=None):
    with SQLite3(str(path)) as db:
        for key in ("a", "b", "c"):
            db.save_blob("blobs", "payload-" + key, key=key)
        if id_column:
            db.execute(f'ALTER TABLE blobs ADD COLUMN "{id_column}" INTEGER')
            db.execute(f'UPDATE blobs SET "{id_column}" = rowid + 100')
            db.commit()


def _read(path, **kwargs):
    with SQLite3(str(path), mode="ro") as db:
        return db.load_blob("blobs", **kwargs)


@pytest.mark.parametrize("ids,expected", [
    (1, {"a": "payload-a"}),
    ([1, 3], {"a": "payload-a", "c": "payload-c"}),
    ([], {}), (0, {}),
    ("all", {"a": "payload-a", "b": "payload-b", "c": "payload-c"}),
])
def test_standard_blob_rowids_filter_results(tmp_path, ids, expected):
    # Arrange
    path = tmp_path / "blobs.db"
    _seed(path)
    # Act
    actual = _read(path, ids=ids)
    # Assert
    assert actual == expected


def test_blob_key_and_rowid_match(tmp_path):
    # Arrange
    path = tmp_path / "blobs.db"
    _seed(path)
    # Act
    actual = _read(path, key="b", ids=2)
    # Assert
    assert actual == "payload-b"


@pytest.mark.parametrize("ids", [1, []])
def test_blob_key_outside_rowid_selection_is_missing(tmp_path, ids):
    # Arrange
    path = tmp_path / "blobs.db"
    _seed(path)
    # Act
    ctx = pytest.raises(KeyError)
    # Assert
    with ctx:
        _read(path, key="b", ids=ids)


def test_blob_rowids_combine_with_where(tmp_path):
    # Arrange
    path = tmp_path / "blobs.db"
    _seed(path)
    # Act
    actual = _read(path, ids=[1, 2, 3], where="key != 'a'")
    # Assert
    assert actual == {"b": "payload-b", "c": "payload-c"}


@pytest.mark.parametrize("id_column", ["id", "ID"])
@pytest.mark.parametrize("key", [None, "a"])
def test_legacy_explicit_id_keeps_precedence(tmp_path, id_column, key):
    # Arrange
    path = tmp_path / "blobs.db"
    _seed(path, id_column)
    expected = "payload-a" if key else {"a": "payload-a"}
    # Act
    actual = _read(path, key=key, ids=101)
    # Assert
    assert actual == expected


def test_blob_rowid_values_are_bound_as_data(tmp_path):
    # Arrange
    path = tmp_path / "blobs.db"
    _seed(path)
    # Act
    actual = _read(path, ids=["1) OR 1=1 --"])
    # Assert
    assert actual == {}
