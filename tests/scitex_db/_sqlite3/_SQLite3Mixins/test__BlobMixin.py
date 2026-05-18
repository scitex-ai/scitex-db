#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._sqlite3._SQLite3Mixins._BlobMixin.save_blob/load_blob.

Real SQLite collaborator under tmp_path — no mocks. Each test is
single-assert, AAA-marked, and named after the behaviour it verifies
(STX-TQ001/TQ002/TQ003/TQ007 clean).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scitex_db import SQLite3


# ----------------------------------------------------------------------------
# Round-trip fundamentals
# ----------------------------------------------------------------------------


def test_save_blob_dict_roundtrip_returns_original_payload(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_dict.db"
    payload = {"a": 1, "b": [1, 2, 3], "c": "hello"}
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", payload, key="k1")
    # Act
    with SQLite3(str(db_path)) as db:
        loaded = db.load_blob("t", key="k1")
    # Assert
    assert loaded == payload


def test_save_blob_list_roundtrip_returns_original_payload(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_list.db"
    payload = [1, 2.5, "x", None, True]
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", payload, key="k1")
        loaded = db.load_blob("t", key="k1")
    # Assert
    assert loaded == payload


def test_save_blob_string_roundtrip_returns_original_value(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_str.db"
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", "hello world", key="k1")
        loaded = db.load_blob("t", key="k1")
    # Assert
    assert loaded == "hello world"


def test_save_blob_int_roundtrip_returns_original_value(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_int.db"
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", 42, key="k1")
        loaded = db.load_blob("t", key="k1")
    # Assert
    assert loaded == 42


# ----------------------------------------------------------------------------
# Numpy array handling
# ----------------------------------------------------------------------------


def test_save_blob_ndarray_returns_ndarray_instance(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_nd.db"
    arr = np.arange(12, dtype=np.float64).reshape(3, 4)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", arr, key="arr1")
        loaded = db.load_blob("t", key="arr1")
    # Assert
    assert isinstance(loaded, np.ndarray)


def test_save_blob_ndarray_preserves_dtype_attribute(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_nd.db"
    arr = np.arange(12, dtype=np.float64).reshape(3, 4)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", arr, key="arr1")
        loaded = db.load_blob("t", key="arr1")
    # Assert
    assert loaded.dtype == arr.dtype


def test_save_blob_ndarray_preserves_shape_attribute(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_nd.db"
    arr = np.arange(12, dtype=np.float64).reshape(3, 4)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", arr, key="arr1")
        loaded = db.load_blob("t", key="arr1")
    # Assert
    assert loaded.shape == arr.shape


def test_save_blob_ndarray_preserves_element_values(tmp_path):
    # Arrange
    db_path = tmp_path / "blob_nd.db"
    arr = np.arange(12, dtype=np.float64).reshape(3, 4)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", arr, key="arr1")
        loaded = db.load_blob("t", key="arr1")
    # Assert
    assert np.array_equal(loaded, arr)


@pytest.mark.parametrize(
    "key,arr",
    [
        ("f32", np.arange(6, dtype=np.float32).reshape(2, 3)),
        ("i64", np.array([1, 2, 3], dtype=np.int64)),
        ("u8", np.zeros((4,), dtype=np.uint8)),
        ("bool_", np.array([True, False, True])),
    ],
)
def test_save_blob_ndarray_dtype_roundtrip_per_kind(tmp_path, key, arr):
    # Arrange
    db_path = tmp_path / "blob_dtypes.db"
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", arr, key=key)
        loaded = db.load_blob("t", key=key)
    # Assert
    assert loaded.dtype == arr.dtype


@pytest.mark.parametrize(
    "key,arr",
    [
        ("f32", np.arange(6, dtype=np.float32).reshape(2, 3)),
        ("i64", np.array([1, 2, 3], dtype=np.int64)),
        ("u8", np.zeros((4,), dtype=np.uint8)),
        ("bool_", np.array([True, False, True])),
    ],
)
def test_save_blob_ndarray_value_roundtrip_per_kind(tmp_path, key, arr):
    # Arrange
    db_path = tmp_path / "blob_dtypes_val.db"
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", arr, key=key)
        loaded = db.load_blob("t", key=key)
    # Assert
    assert np.array_equal(loaded, arr)


# ----------------------------------------------------------------------------
# Real-world GMM cache shape (NeuroVista pipeline)
# ----------------------------------------------------------------------------


@pytest.fixture
def gmm_payload():
    return {
        "means": np.array([0.1, 0.9], dtype=np.float64),
        "sigmas": np.array([0.05, 0.05], dtype=np.float64),
        "weights": np.array([0.7, 0.3], dtype=np.float64),
        "ashmans_d": 0.8473006672540366,
        "weight_ratio": 3.363115657538119,
        "bhattacharyya_coeff": 0.6387041636281181,
        "bimodality_coeff": 0.1479683821112239,
    }


def test_save_blob_gmm_cache_means_roundtrip(tmp_path, gmm_payload):
    # Arrange
    db_path = tmp_path / "gmm_cache.db"
    content_hash = "0000015cbd494f1ec22e8e465cb42544"
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("gmm_cache", gmm_payload, key=content_hash)
        loaded = db.load_blob("gmm_cache", key=content_hash)
    # Assert
    assert np.array_equal(loaded["means"], gmm_payload["means"])


def test_save_blob_gmm_cache_scalar_ashmans_d_roundtrip(tmp_path, gmm_payload):
    # Arrange
    db_path = tmp_path / "gmm_cache.db"
    content_hash = "0000015cbd494f1ec22e8e465cb42544"
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("gmm_cache", gmm_payload, key=content_hash)
        loaded = db.load_blob("gmm_cache", key=content_hash)
    # Assert
    assert loaded["ashmans_d"] == gmm_payload["ashmans_d"]


# ----------------------------------------------------------------------------
# Compression semantics
# ----------------------------------------------------------------------------


def test_compression_threshold_small_payload_records_uncompressed(tmp_path):
    # Arrange
    db_path = tmp_path / "small.db"
    small = {"x": 1}
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("t", small, key="k1")
        row = db.execute(
            "SELECT compressed FROM t WHERE key = ?", ("k1",)
        ).fetchone()
    # Assert
    assert row[0] == 0


def test_compression_large_payload_records_compressed_flag(tmp_path):
    # Arrange
    db_path = tmp_path / "large.db"
    large_arr = np.arange(2000, dtype=np.float64)
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("t", large_arr, key="k1")
        row = db.execute(
            "SELECT compressed FROM t WHERE key = ?", ("k1",)
        ).fetchone()
    # Assert
    assert row[0] == 1


def test_compression_default_off_leaves_payload_uncompressed(tmp_path):
    # Arrange
    db_path = tmp_path / "nocompr.db"
    large_arr = np.arange(2000, dtype=np.float64)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", large_arr, key="k1")
        row = db.execute(
            "SELECT compressed FROM t WHERE key = ?", ("k1",)
        ).fetchone()
    # Assert
    assert row[0] == 0


def test_compression_explicit_on_overrides_db_default(tmp_path):
    # Arrange
    db_path = tmp_path / "override.db"
    large_arr = np.arange(2000, dtype=np.float64)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", large_arr, key="explicit_on", compress=True)
        row = db.execute(
            "SELECT compressed FROM t WHERE key = ?", ("explicit_on",)
        ).fetchone()
    # Assert
    assert row[0] == 1


def test_compression_explicit_off_overrides_db_default(tmp_path):
    # Arrange
    db_path = tmp_path / "override.db"
    large_arr = np.arange(2000, dtype=np.float64)
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", large_arr, key="explicit_off", compress=False)
        row = db.execute(
            "SELECT compressed FROM t WHERE key = ?", ("explicit_off",)
        ).fetchone()
    # Assert
    assert row[0] == 0


def test_compression_roundtrip_returns_identical_array(tmp_path):
    # Arrange
    db_path = tmp_path / "cr.db"
    arr = np.random.default_rng(42).standard_normal(2000)
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("t", arr, key="k")
        loaded = db.load_blob("t", key="k")
    # Assert
    assert np.array_equal(loaded, arr)


# ----------------------------------------------------------------------------
# INSERT OR REPLACE semantics
# ----------------------------------------------------------------------------


def test_save_blob_replace_keeps_single_row_per_key(tmp_path):
    # Arrange
    db_path = tmp_path / "replace.db"
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", {"v": 1}, key="k")
        db.save_blob("t", {"v": 2}, key="k")
        count = db.execute(
            "SELECT COUNT(*) FROM t WHERE key = ?", ("k",)
        ).fetchone()[0]
    # Assert
    assert count == 1


def test_save_blob_replace_returns_latest_value_on_load(tmp_path):
    # Arrange
    db_path = tmp_path / "replace.db"
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", {"v": 1}, key="k")
        db.save_blob("t", {"v": 2}, key="k")
        loaded = db.load_blob("t", key="k")
    # Assert
    assert loaded == {"v": 2}


def test_save_blob_resume_safe_count_matches_unique_keys(tmp_path):
    # Arrange
    db_path = tmp_path / "resume.db"
    items = [("a", {"x": 1}), ("b", {"x": 2}), ("c", {"x": 3})]
    # Act
    with SQLite3(str(db_path)) as db:
        for k, v in items:
            db.save_blob("t", v, key=k)
        for k, v in items:
            db.save_blob("t", v, key=k)
        total = db.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    # Assert
    assert total == len(items)


# ----------------------------------------------------------------------------
# load_blob semantics
# ----------------------------------------------------------------------------


def test_load_blob_missing_key_raises_keyerror(tmp_path):
    # Arrange
    db_path = tmp_path / "missing.db"
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", {"v": 1}, key="present")
        ctx = pytest.raises(KeyError)
        # Act
        action = lambda: db.load_blob("t", key="absent")
        # Assert
        with ctx:
            action()


def test_load_blob_without_key_returns_dict_instance(tmp_path):
    # Arrange
    db_path = tmp_path / "all.db"
    payload = {"a": {"v": 1}, "b": {"v": 2}, "c": {"v": 3}}
    # Act
    with SQLite3(str(db_path)) as db:
        for k, v in payload.items():
            db.save_blob("t", v, key=k)
        loaded = db.load_blob("t")
    # Assert
    assert isinstance(loaded, dict)


def test_load_blob_without_key_returns_all_stored_keys(tmp_path):
    # Arrange
    db_path = tmp_path / "all.db"
    payload = {"a": {"v": 1}, "b": {"v": 2}, "c": {"v": 3}}
    # Act
    with SQLite3(str(db_path)) as db:
        for k, v in payload.items():
            db.save_blob("t", v, key=k)
        loaded = db.load_blob("t")
    # Assert
    assert set(loaded.keys()) == set(payload.keys())


# ----------------------------------------------------------------------------
# Schema + metadata
# ----------------------------------------------------------------------------


def test_save_blob_auto_creates_canonical_columns(tmp_path):
    # Arrange
    db_path = tmp_path / "schema.db"
    expected = {
        "key",
        "timestamp",
        "pid",
        "hostname",
        "data",
        "compressed",
        "data_type",
        "metadata",
    }
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("fresh_table", {"x": 1}, key="k")
        cols = [
            row[1]
            for row in db.execute("PRAGMA table_info(fresh_table)").fetchall()
        ]
    # Assert
    assert expected.issubset(set(cols))


def test_save_blob_metadata_column_stores_source_field(tmp_path):
    # Arrange
    db_path = tmp_path / "meta.db"
    meta = {"source": "unit_test", "run": 7}
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", {"v": 1}, key="k", metadata=meta)
        row = db.execute(
            "SELECT metadata FROM t WHERE key = ?", ("k",)
        ).fetchone()
        stored = json.loads(row[0])
    # Assert
    assert stored["source"] == "unit_test"


def test_save_blob_metadata_column_stores_run_field(tmp_path):
    # Arrange
    db_path = tmp_path / "meta.db"
    meta = {"source": "unit_test", "run": 7}
    # Act
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", {"v": 1}, key="k", metadata=meta)
        row = db.execute(
            "SELECT metadata FROM t WHERE key = ?", ("k",)
        ).fetchone()
        stored = json.loads(row[0])
    # Assert
    assert stored["run"] == 7


def test_save_blob_compression_metadata_records_original_size(tmp_path):
    # Arrange
    db_path = tmp_path / "meta_sz.db"
    large_arr = np.arange(5000, dtype=np.float64)
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("t", large_arr, key="k")
        row = db.execute(
            "SELECT metadata FROM t WHERE key = ?", ("k",)
        ).fetchone()
        stored = json.loads(row[0])
    # Assert
    assert "original_size" in stored


def test_save_blob_compression_metadata_records_compressed_size(tmp_path):
    # Arrange
    db_path = tmp_path / "meta_sz.db"
    large_arr = np.arange(5000, dtype=np.float64)
    # Act
    with SQLite3(str(db_path), compress_by_default=True) as db:
        db.save_blob("t", large_arr, key="k")
        row = db.execute(
            "SELECT metadata FROM t WHERE key = ?", ("k",)
        ).fetchone()
        stored = json.loads(row[0])
    # Assert
    assert stored["compressed_size"] <= stored["original_size"]


# ----------------------------------------------------------------------------
# Context manager persistence
# ----------------------------------------------------------------------------


def test_context_manager_persists_payload_across_reopen(tmp_path):
    # Arrange
    db_path = tmp_path / "persist.db"
    with SQLite3(str(db_path)) as db:
        db.save_blob("t", {"v": 1}, key="k1")
    # Act
    with SQLite3(str(db_path)) as db2:
        loaded = db2.load_blob("t", key="k1")
    # Assert
    assert loaded == {"v": 1}


# ----------------------------------------------------------------------------
# Bulk-ingest smoke test
# ----------------------------------------------------------------------------


def test_bulk_ingest_thousand_records_count_matches(tmp_path):
    # Arrange
    db_path = tmp_path / "bulk.db"
    n = 1000
    with SQLite3(str(db_path), compress_by_default=True) as db:
        for i in range(n):
            db.save_blob("t", {"i": i, "v": float(i) * 0.5}, key=f"k{i:04d}")
    # Act
    with SQLite3(str(db_path)) as db:
        count = db.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    # Assert
    assert count == n


@pytest.mark.parametrize("i", [0, 500, 999])
def test_bulk_ingest_spot_check_roundtrip_per_index(tmp_path, i):
    # Arrange
    db_path = tmp_path / "bulk_spot.db"
    n = 1000
    with SQLite3(str(db_path), compress_by_default=True) as db:
        for j in range(n):
            db.save_blob("t", {"i": j, "v": float(j) * 0.5}, key=f"k{j:04d}")
    # Act
    with SQLite3(str(db_path)) as db:
        loaded = db.load_blob("t", key=f"k{i:04d}")
    # Assert
    assert loaded == {"i": i, "v": float(i) * 0.5}


if __name__ == "__main__":
    import os

    pytest.main([os.path.abspath(__file__), "-v"])
