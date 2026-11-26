"""Native count boundaries, bounded SQL probes and installed CLI semantics."""
from contextlib import closing
import json
import sqlite3
import subprocess
import sys

import pytest

from scitex_db import inspect
from scitex_db._inspect import OptimizedInspector


@pytest.fixture(params=[
    (filename, rows)
    for filename in ["counts.db", "counts?#%3f 日本語.db"]
    for rows in [0, 99999, 100000, 100001]
])
def count_database(request, tmp_path):
    filename, rows = request.param
    path = tmp_path / filename
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('CREATE TABLE "order counts"(id INTEGER PRIMARY KEY)')
        connection.executemany('INSERT INTO "order counts" VALUES(?)',
                               ((value,) for value in range(1, rows + 1)))
    yield path, rows


def _expected_count(rows):
    return (rows, False) if rows < 100000 else (">=100,000", True)


def test_public_count_reports_only_what_probe_proves(count_database):
    # Arrange
    path, rows = count_database
    before = path.read_bytes()
    # Act
    result = inspect(str(path), sample_size=0, verbose=False)[0]
    # Assert
    assert (result["row_count"], result["is_approximate"], result["sample_data"],
            path.read_bytes()) == (*_expected_count(rows), [], before)


def test_direct_batch_count_uses_same_inclusive_boundary(count_database):
    # Arrange
    path, rows = count_database
    before = path.read_bytes()
    # Act
    with OptimizedInspector(str(path)) as inspector:
        result = inspector.get_table_stats_batch(["order counts"], sample_size=0)["order counts"]
    # Assert
    assert (result["row_count"], result["is_approximate"], result["sample_data"],
            path.read_bytes()) == (*_expected_count(rows), [], before)


def test_skip_count_keeps_existing_flags_and_samples(count_database):
    # Arrange
    path, rows = count_database
    before = path.read_bytes()
    # Act
    result = inspect(str(path), sample_size=1, skip_count=True, verbose=False)[0]
    # Assert
    assert (result["row_count"], result["is_approximate"], result["sample_data"],
            path.read_bytes()) == ("Not counted", None, [{"id": 1}] if rows else [], before)


def test_cli_json_preserves_truthful_count_boundary(count_database):
    # Arrange
    path, rows = count_database
    before = path.read_bytes()
    # Act
    process = subprocess.run([sys.executable, "-I", "-m", "scitex_db", "inspect-db",
                              str(path), "--json"], capture_output=True, text=True, timeout=60)
    process.check_returncode()
    result = json.loads(process.stdout)[0]
    # Assert
    assert (result["table_name"], result["row_count"], result["is_approximate"],
            result["sample_data"], path.read_bytes()) == (
        "order counts", *_expected_count(rows),
        [{"id": value} for value in range(1, min(rows, 5) + 1)], before
    )


def test_native_count_probe_retains_existing_scan_bound(count_database):
    # Arrange
    path, rows = count_database
    queries = []
    # Act
    with OptimizedInspector(str(path)) as inspector:
        with inspector.connection() as cursor:
            cursor.connection.set_trace_callback(queries.append)
        inspector.get_table_stats_batch(["order counts"], sample_size=0)
    counts = [" ".join(query.split()) for query in queries if "COUNT(*)" in query]
    # Assert
    assert counts == ['SELECT COUNT(*) FROM ( SELECT 1 FROM "order counts" LIMIT 100000 )'] + (
        ['SELECT COUNT(*) FROM "order counts"'] if rows < 100000 else []
    )
