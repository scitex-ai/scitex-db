"""Native connection cleanup, separate from health/loadability acceptance.

Python 3.13 diagnoses an unclosed sqlite3 connection during actual collection.
Older interpreters run the same controls but do not establish that diagnostic.
The currently undeclared umbrella dependency is recorded, never accepted as a
successful health check or replaced with a mock.
"""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest


@pytest.fixture(params=["healthy", "malformed"])
def health_resource_case(request, tmp_path):
    database = tmp_path / "health.db"
    if request.param == "healthy":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE samples(id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO samples VALUES(7)")
            connection.commit()
    else:
        database.write_bytes(b"This is not a SQLite database.\n")
    yield database, tmp_path / "health-resource.json"


def _run_health_resource_probe(database, report_path):
    program = r'''
from pathlib import Path
import gc, json, sys, warnings
import scitex_db._check_health as health_module
path=Path(sys.argv[1]);before=path.read_bytes()
with warnings.catch_warnings(record=True) as seen:
    warnings.simplefilter("always", ResourceWarning)
    try:
        result=health_module.check_health(str(path), verbose=False)
        outcome="completed"
    except ModuleNotFoundError as exc:
        if exc.name != "scitex":
            raise
        outcome="unavailable_umbrella"
    gc.collect()
    gc.collect()
observed={
    "outcome":outcome,
    "warnings":[{"category":w.category.__name__,"message":str(w.message)} for w in seen],
    "unclosed_databases":[str(w.message) for w in seen if issubclass(w.category,ResourceWarning) and "unclosed database" in str(w.message)],
    "database_bytes_unchanged":path.read_bytes()==before,
    "python":sys.version,
    "health_module":health_module.__file__,
}
Path(sys.argv[2]).write_text(json.dumps(observed,indent=2)+"\n")
print(json.dumps(observed))
'''
    return subprocess.run(
        [sys.executable, "-I", "-c", program, str(database), str(report_path)],
        cwd=database.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_health_scan_closes_native_connection(health_resource_case):
    # Arrange
    database, report_path = health_resource_case
    # Act
    result = _run_health_resource_probe(database, report_path)
    report = json.loads(result.stdout)
    # Assert
    assert (
        result.returncode == 0
        and report["unclosed_databases"] == []
        and report["database_bytes_unchanged"]
        and report["outcome"] in {"completed", "unavailable_umbrella"}
    )
