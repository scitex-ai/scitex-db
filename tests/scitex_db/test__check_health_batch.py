"""Batch summaries preserve actual early-return health reports."""

import os
import subprocess
import sys

import pytest

from scitex_db import batch_health_check, check_health


@pytest.mark.parametrize("name", ["missing.db", "missing?#%3f 日本語.db", "missing with spaces.db"])
def test_batch_returns_original_missing_file_report(tmp_path, name):
    # Arrange
    path = tmp_path / name
    expected = check_health(str(path), verbose=False, fix_issues=False)
    # Act
    actual = batch_health_check([str(path)], verbose=False, fix_issues=False)
    # Assert
    assert (actual, path.exists(), "status" in actual[str(path)]) == ({str(path): expected}, False, False)


@pytest.mark.parametrize("verbose", [False, True])
def test_batch_preserves_input_order_and_missing_reports(tmp_path, verbose):
    # Arrange
    paths = [str(tmp_path / name) for name in ["second.db", "first.db"]]
    expected = {path: check_health(path, verbose=False) for path in paths}
    # Act
    actual = batch_health_check(paths, verbose=verbose, fix_issues=False)
    # Assert
    assert (list(actual), actual, list(tmp_path.iterdir())) == (paths, expected, [])


def test_batch_repeated_missing_path_keeps_single_report(tmp_path):
    # Arrange
    path = str(tmp_path / "missing.db")
    expected = check_health(path, verbose=False)
    # Act
    actual = batch_health_check([path, path], verbose=False)
    # Assert
    assert (actual, list(tmp_path.iterdir())) == ({path: expected}, [])


@pytest.mark.parametrize("verbose", [False, True])
def test_batch_empty_paths_returns_empty_mapping(tmp_path, verbose):
    # Arrange
    paths = []
    # Act
    actual = batch_health_check(paths, verbose=verbose)
    # Assert
    assert (actual, list(tmp_path.iterdir())) == ({}, [])


@pytest.mark.parametrize("verbose", [False, True])
def test_batch_summary_identifies_incomplete_reports(tmp_path, verbose):
    # Arrange
    path = tmp_path / "missing.db"
    script = "import json,sys; from scitex_db import batch_health_check; print(json.dumps(batch_health_check([sys.argv[1]], verbose=sys.argv[2]=='True')))"
    environment = dict(os.environ, SCITEX_LOGGING_LEVEL="INFO")
    # Act
    result = subprocess.run([sys.executable, "-I", "-c", script, str(path), str(verbose)], env=environment, capture_output=True, text=True, timeout=60)
    # Assert
    assert (result.returncode, "Incomplete: 1" in result.stderr, "Healthy: 0" in result.stderr, "Issues: 0" in result.stderr, "Critical: 0" in result.stderr, "Traceback" in result.stderr, path.exists()) == (0, True, True, True, True, False, False)
