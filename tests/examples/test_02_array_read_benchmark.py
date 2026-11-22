"""Exercise the benchmark's real processes, value checks and output admission."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "examples/02_array_read_benchmark.py"
SMALL = [
    "--samples",
    "512",
    "--channels",
    "2",
    "--windows",
    "4",
    "--window-samples",
    "64",
    "--sampling-rate",
    "128",
    "--seed",
    "7",
]


@pytest.fixture(scope="module")
def measured_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("array-read-benchmark")
    output = root / "result"
    process = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--output", str(output), *SMALL],
        cwd=root,
        capture_output=True,
        timeout=30,
    )
    (root / "stdout.log").write_bytes(process.stdout)
    (root / "stderr.log").write_bytes(process.stderr)
    process.check_returncode()
    yield json.loads((output / "report.json").read_text()), output


def test_report_covers_all_three_requested_backends(measured_run):
    # Arrange
    report, _ = measured_run
    # Act
    modes = [row["mode"] for row in report["results"]]
    # Assert
    assert modes == ["memory", "plain", "compressed"]


def test_backend_readbacks_match_direct_numpy_windows(measured_run):
    # Arrange
    report, output = measured_run
    data = np.load(output / "signal.npy", allow_pickle=False)
    starts = report["config"]["window_starts"]
    # Act
    expected = hashlib.sha256(
        np.stack([data[start : start + 64] for start in starts]).tobytes()
    ).hexdigest()
    actual = [row["window_digest"] for row in report["results"]]
    # Assert
    assert actual == [expected] * 3


def test_window_sequence_includes_both_recording_boundaries(measured_run):
    # Arrange
    report, _ = measured_run
    # Act
    boundaries = report["config"]["window_starts"][:2]
    # Assert
    assert boundaries == [0, 448]


def test_each_backend_runs_in_a_distinct_worker_process(measured_run):
    # Arrange
    report, _ = measured_run
    # Act
    pids = {row["pid"] for row in report["results"]}
    # Assert
    assert (len(pids), report["orchestrator_pid"] in pids) == (3, False)


def test_actual_database_compression_matches_backend_labels(measured_run):
    # Arrange
    _, output = measured_run
    flags = []
    # Act
    for mode in ["plain", "compressed"]:
        with closing(
            sqlite3.connect((output / (mode + ".db")).as_uri() + "?mode=ro", uri=True)
        ) as conn:
            flags.append(
                conn.execute("SELECT data_is_compressed FROM signal").fetchone()[0]
            )
    # Assert
    assert flags == [0, 1]


def test_rate_units_match_processed_window_duration(measured_run):
    # Arrange
    report, _ = measured_run
    # Act
    durations = [
        row["signal_seconds_per_second"] * row["elapsed_seconds"]
        for row in report["results"]
    ]
    # Assert
    assert durations == pytest.approx([2.0, 2.0, 2.0])


def test_report_identifies_whole_blob_access_and_rss_scope(measured_run):
    # Arrange
    report, _ = measured_run
    # Act
    patterns = [row["access_pattern"] for row in report["results"]]
    # Assert
    assert (patterns, "not an allocation delta" in report["scope"]["rss"]) == (
        ["resident_slice", "whole_blob_then_slice", "whole_blob_then_slice"],
        True,
    )


@pytest.mark.parametrize(
    "invalid",
    [
        ["--samples", "0"],
        ["--channels", "0"],
        ["--windows", "1"],
        ["--window-samples", "513"],
        ["--sampling-rate", "nan"],
        ["--seed", "-1"],
    ],
)
def test_invalid_dimensions_refuse_before_creating_output(tmp_path, invalid):
    # Arrange
    output = tmp_path / "absent"
    # Act
    process = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--output", str(output), *SMALL, *invalid],
        capture_output=True,
        timeout=30,
    )
    # Assert
    assert (process.returncode, output.exists()) == (2, False)


def test_existing_output_refusal_preserves_owned_sentinel(tmp_path):
    # Arrange
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_bytes(b"keep")
    # Act
    process = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--output", str(output), *SMALL],
        capture_output=True,
        timeout=30,
    )
    # Assert
    assert (
        process.returncode,
        sentinel.read_bytes(),
        sorted(p.name for p in output.iterdir()),
    ) == (2, b"keep", ["sentinel"])
