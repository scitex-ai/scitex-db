"""Measure current whole-array BLOB reads against resident NumPy windows.

Creates synthetic fixtures only. See docs/array-read-benchmark.md for scope,
metric definitions and the distinction from chunked/out-of-core storage.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import time
import zlib

import numpy as np
import scitex_db
from scitex_db import SQLite3

try:
    import resource
except ImportError:
    resource = None

MODES = ("memory", "plain", "compressed")


def _write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _window_digest(reader, starts, width):
    digest = hashlib.sha256()
    for start in starts:
        digest.update(reader()[start : start + width].tobytes(order="C"))
    return digest.hexdigest()


def _peak_rss_bytes():
    if resource is None or sys.platform not in ("linux", "darwin"):
        return None
    scale = 1 if sys.platform == "darwin" else 1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale


def _prepare(output, config):
    rng = np.random.default_rng(config["seed"])
    data = rng.standard_normal((config["samples"], config["channels"])).astype(
        "float32"
    )
    maximum = config["samples"] - config["window_samples"]
    starts = [0, maximum] + rng.integers(0, maximum + 1, config["windows"] - 2).tolist()
    config.update(
        window_starts=starts,
        dtype=str(data.dtype),
        compression_level=6,
        data_sha256=hashlib.sha256(data.tobytes(order="C")).hexdigest(),
        expected_digest=_window_digest(lambda: data, starts, config["window_samples"]),
    )
    np.save(output / "signal.npy", data, allow_pickle=False)
    for mode in MODES[1:]:
        with SQLite3(str(output / (mode + ".db"))) as db:
            db.create_table("signal", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
            db.save_array(
                "signal",
                data,
                compress=mode == "compressed",
                compress_level=config["compression_level"],
                verbose=False,
            )
    _write_json(output / "config.json", config)


def _timed_read(reader, config):
    wall, cpu = time.perf_counter(), time.process_time()
    digest = _window_digest(reader, config["window_starts"], config["window_samples"])
    elapsed, cpu_elapsed = time.perf_counter() - wall, time.process_time() - cpu
    if digest != config["expected_digest"]:
        raise ValueError("Window values differ from the generated NumPy reference")
    duration = config["windows"] * config["window_samples"] / config["sampling_rate"]
    return {
        "elapsed_seconds": elapsed,
        "cpu_seconds": cpu_elapsed,
        "processed_signal_seconds": duration,
        "signal_seconds_per_second": duration / elapsed,
        "window_digest": digest,
    }


def _worker(output, mode):
    config = json.loads((output / "config.json").read_text())
    if mode == "memory":
        data = np.load(output / "signal.npy", allow_pickle=False)
        result = _timed_read(lambda: data, config)
    else:
        with SQLite3(str(output / (mode + ".db")), mode="ro", timeout=1) as db:
            shape = (config["samples"], config["channels"])
            result = _timed_read(
                lambda: db.load_array("signal", "data", ids=1, verbose=False).reshape(
                    shape
                ),
                config,
            )
    result.update(
        mode=mode,
        pid=os.getpid(),
        peak_rss_bytes=_peak_rss_bytes(),
        access_pattern=(
            "resident_slice" if mode == "memory" else "whole_blob_then_slice"
        ),
    )
    _write_json(output / (mode + ".json"), result)


def _run(output, config):
    output.mkdir(mode=0o700)
    _prepare(output, config)
    rows = []
    for mode in MODES:
        command = [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--output",
            str(output),
            "--worker",
            mode,
        ]
        result = subprocess.run(command, capture_output=True, timeout=120)
        (output / (mode + ".stdout.log")).write_bytes(result.stdout)
        (output / (mode + ".stderr.log")).write_bytes(result.stderr)
        result.check_returncode()
        rows.append(json.loads((output / (mode + ".json")).read_text()))
    report = {
        "schema_version": 1,
        "config": config,
        "results": rows,
        "orchestrator_pid": os.getpid(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "sqlite": sqlite3.sqlite_version,
        "zlib": zlib.ZLIB_VERSION,
        "scitex_db": scitex_db.__version__,
        "loader_sha256": hashlib.sha256(
            Path(inspect.getfile(SQLite3.load_array)).read_bytes()
        ).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "storage_bytes": {
            name: (output / name).stat().st_size
            for name in ("signal.npy", "plain.db", "compressed.db")
        },
        "scope": {
            "data": "Synthetic independent normal float32 samples; not physiological recordings.",
            "timing": "Window access plus checksum; excludes fixture creation, connection open and initial NumPy load.",
            "rss": "Whole fresh worker lifetime including imports and initial load; not an allocation delta. Null when unavailable.",
            "cache": "No cache eviction; fixture creation may populate the OS cache. Fixed memory/plain/compressed order.",
            "throughput": "Processed window duration; overlapping/repeated samples count repeatedly, not unique recording duration.",
            "limitations": "Current whole-BLOB baseline only; no chunked storage, out-of-RAM proof, DataLoader, or cross-host generalization.",
        },
    }
    _write_json(output / "report.json", report)
    print(json.dumps(report, indent=2, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New fixture/result directory; existing paths are refused.",
    )
    parser.add_argument("--samples", type=int, default=1_000_000)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--window-samples", type=int, default=1000)
    parser.add_argument("--windows", type=int, default=100)
    parser.add_argument("--sampling-rate", type=float, default=250)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--worker", choices=MODES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.absolute()
    if args.worker:
        _worker(output, args.worker)
        return
    if min(args.samples, args.channels, args.window_samples) <= 0 or args.windows < 2:
        parser.error(
            "samples/channels/window-samples must be positive; windows must be at least 2"
        )
    if args.window_samples > args.samples or args.seed < 0:
        parser.error("window-samples must not exceed samples; seed must be nonnegative")
    if not math.isfinite(args.sampling_rate) or args.sampling_rate <= 0:
        parser.error("sampling-rate must be finite and positive")
    if output.exists() or output.is_symlink():
        parser.error("output must be a new directory")
    config = {
        key: value
        for key, value in vars(args).items()
        if key not in ("output", "worker")
    }
    _run(output, config)


if __name__ == "__main__":
    main()
