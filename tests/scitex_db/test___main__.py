"""Observe the CLI configuration gap until the intended loader is implemented.

These controls record ignored files; successful commands do not qualify a
configuration loader or its precedence. Update them when that feature lands.
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest


@pytest.fixture(params=["project", "environment", "user", "dotenv"])
def cli_configuration_case(request, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    database = project / "fixture.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            "CREATE TABLE cli_selected(value INTEGER);"
            "INSERT INTO cli_selected VALUES(11);"
            "CREATE TABLE config_only(value INTEGER);"
            "INSERT INTO config_only VALUES(22);"
        )
        connection.commit()
    environment = dict(os.environ, HOME=str(home), SCITEX_LOGGING_LEVEL="INFO")
    environment.pop("SCITEX_DB_CONFIG", None)
    paths = {
        "project": project / "config.yaml",
        "environment": project / "selected.yaml",
        "user": home / ".scitex" / "db" / "config.yaml",
        "dotenv": project / "selected.yaml",
    }
    config = paths[request.param]
    config.parent.mkdir(parents=True, exist_ok=True)
    if request.param == "environment":
        environment["SCITEX_DB_CONFIG"] = str(config)
    if request.param == "dotenv":
        (project / ".env").write_text(f"SCITEX_DB_CONFIG={config}\n")
    yield home, project, database, config, environment


def _inspect_result(case, content, options):
    home, project, database, config, environment = case
    config.write_text(content)
    files = [database, config, *project.glob(".env")]
    before = {path: path.read_bytes() for path in files}
    result = subprocess.run(
        [sys.executable, "-m", "scitex_db", "inspect-db", str(database), *options],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "exit": result.returncode,
        "tables": re.findall(r"Table: (\w+)", result.stdout + result.stderr),
        "fixture_bytes_unchanged": all(
            path.read_bytes() == content for path, content in before.items()
        ),
        "no_new_config_files": sorted(home.rglob("*.yaml"))
        == ([config] if config.is_relative_to(home) else []),
    }


@pytest.mark.parametrize("content", ["tables:\n  - config_only\n", "[invalid: yaml\n"])
def test_cli_ignores_unimplemented_configuration_files(cli_configuration_case, content):
    # Arrange
    expected = {
        "exit": 0,
        "tables": ["cli_selected", "config_only"],
        "fixture_bytes_unchanged": True,
        "no_new_config_files": True,
    }
    # Act
    actual = _inspect_result(cli_configuration_case, content, [])
    # Assert
    assert actual == expected


@pytest.mark.parametrize("content", ["tables:\n  - config_only\n", "[invalid: yaml\n"])
def test_cli_explicit_table_selection_remains_effective(cli_configuration_case, content):
    # Arrange
    expected = {
        "exit": 0,
        "tables": ["cli_selected"],
        "fixture_bytes_unchanged": True,
        "no_new_config_files": True,
    }
    # Act
    actual = _inspect_result(cli_configuration_case, content, ["--tables", "cli_selected"])
    # Assert
    assert actual == expected


@pytest.mark.parametrize("option", ["--help", "--help-recursive"])
def test_cli_help_discloses_unimplemented_configuration(option, tmp_path):
    # Arrange
    command = [sys.executable, "-m", "scitex_db", option]
    # Act
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    # Assert
    assert result.returncode == 0 and "not implemented" in result.stdout


@pytest.fixture
def inspection_case(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    database = tmp_path / "inspection.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(
            "CREATE TABLE records(id INTEGER PRIMARY KEY, label TEXT NOT NULL,"
            "value REAL, optional TEXT, payload BLOB);"
            "CREATE TABLE empty(id INTEGER PRIMARY KEY);"
        )
        connection.execute(
            "INSERT INTO records VALUES(1, ?, 1.25, NULL, ?)",
            ("日本語", b"\x00\xff\x10"),
        )
        connection.commit()
    environment = dict(os.environ, HOME=str(home), SCITEX_LOGGING_LEVEL="INFO")
    yield database, environment


def _run_inspection(case, before, after):
    database, environment = case
    original = database.read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "scitex_db", *before, "inspect-db", str(database), *after],
        cwd=database.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, database.read_bytes() == original


@pytest.mark.parametrize(
    "before,after", [([], ["--json"]), (["--json"], []), (["--json"], ["--json"])]
)
@pytest.mark.parametrize("quiet", [[], ["--quiet"]])
def test_inspect_json_preserves_schema_values_and_bytes(inspection_case, before, after, quiet):
    # Arrange
    expected = [{
        "table_name": "records",
        "columns": [
            {"cid": 0, "name": "id", "type": "INTEGER", "notnull": False, "default": None, "pk": True},
            {"cid": 1, "name": "label", "type": "TEXT", "notnull": True, "default": None, "pk": False},
            {"cid": 2, "name": "value", "type": "REAL", "notnull": False, "default": None, "pk": False},
            {"cid": 3, "name": "optional", "type": "TEXT", "notnull": False, "default": None, "pk": False},
            {"cid": 4, "name": "payload", "type": "BLOB", "notnull": False, "default": None, "pk": False},
        ],
        "row_count": 1,
        "is_approximate": False,
        "sample_data": [{"id": 1, "label": "日本語", "value": 1.25, "optional": None, "payload": "<BLOB 3 bytes>"}],
    }]
    # Act
    result, unchanged = _run_inspection(inspection_case, before, after + quiet + ["--tables", "records"])
    # Assert
    assert (result.returncode, json.loads(result.stdout), "Table:" in result.stderr, unchanged) == (0, expected, False, True)


@pytest.mark.parametrize(
    "options,expected",
    [([], [("empty", 0), ("records", 1)]),
     (["--tables", "records"], [("records", 1)]),
     (["--tables", "records", "--tables", "empty"], [("records", 1), ("empty", 0)])],
)
def test_inspect_json_selects_tables_in_requested_order(inspection_case, options, expected):
    # Arrange
    arguments = ["--json", *options]
    # Act
    result, unchanged = _run_inspection(inspection_case, [], arguments)
    observed = [(row["table_name"], row["row_count"]) for row in json.loads(result.stdout)]
    # Assert
    assert (result.returncode, observed, unchanged) == (0, expected, True)


@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_inspect_json_refuses_nonfinite_values(inspection_case, value):
    # Arrange
    database, _ = inspection_case
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE records SET value = ?", (value,))
        connection.commit()
    # Act
    result, unchanged = _run_inspection(inspection_case, [], ["--json", "--tables", "records"])
    # Assert
    assert (result.returncode, result.stdout, "standard JSON" in result.stderr, unchanged) == (1, "", True, True)


@pytest.mark.parametrize("quiet,visible", [([], True), (["--quiet"], False)])
def test_inspect_human_output_keeps_quiet_contract(inspection_case, quiet, visible):
    # Arrange
    arguments = ["--tables", "records", *quiet]
    # Act
    result, unchanged = _run_inspection(inspection_case, [], arguments)
    # Assert
    assert (result.returncode, "Table: records" in result.stdout + result.stderr, unchanged) == (0, visible, True)


def test_inspect_json_retains_default_sample_limit(inspection_case):
    # Arrange
    database, _ = inspection_case
    with closing(sqlite3.connect(database)) as connection:
        connection.executemany("INSERT INTO records(id, label) VALUES(?, 'extra')", [(n,) for n in range(2, 9)])
        connection.commit()
    # Act
    result, unchanged = _run_inspection(inspection_case, [], ["--json", "--tables", "records"])
    row = json.loads(result.stdout)[0]
    # Assert
    assert (result.returncode, row["row_count"], [sample["id"] for sample in row["sample_data"]], unchanged) == (0, 8, [1, 2, 3, 4, 5], True)


@pytest.fixture
def health_cli_files(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    paths = [tmp_path / "first.db", tmp_path / "second.db"]
    for path in paths:
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE samples(id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO samples VALUES(7)")
            connection.commit()
    yield paths, dict(os.environ, HOME=str(home), SCITEX_LOGGING_LEVEL="INFO")


def _health_cli_result(case, before, after, multiple=False, deadline=60):
    paths, environment = case
    selected = paths if multiple else paths[:1]
    snapshots = {path: path.read_bytes() for path in paths}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scitex_db", *before, "check-health", *map(str, selected), *after],
            cwd=paths[0].parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=deadline,
        )
        observed = {"exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr, "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        observed = {"exit": None, "stdout": repr(exc.stdout), "stderr": repr(exc.stderr), "timed_out": True}
    observed["bytes_unchanged"] = all(path.read_bytes() == content for path, content in snapshots.items())
    (paths[0].parent / "health-cli.json").write_text(json.dumps(observed, indent=2) + "\n")
    return observed


def _missing_health_provider(observed):
    return (
        observed["exit"] == 1
        and observed["stdout"] == ""
        and "cannot find the 'scitex' loadability provider" in observed["stderr"]
        and "No checks or repairs were attempted" in observed["stderr"]
        and not observed["timed_out"]
        and observed["bytes_unchanged"]
    )


@pytest.mark.parametrize(
    "before,after",
    [([], []), ([], ["--quiet"]), ([], ["--json"]), (["--json"], []),
     ([], ["--fix", "--yes"]), ([], ["--fix", "--dry-run"])],
)
def test_health_cli_names_missing_provider(health_cli_files, before, after):
    # Arrange
    case = health_cli_files
    # Act
    observed = _health_cli_result(case, before, after)
    # Assert
    assert _missing_health_provider(observed)


def test_health_cli_preflight_rejects_multiple_paths(health_cli_files):
    # Arrange
    case = health_cli_files
    # Act
    observed = _health_cli_result(case, [], [], multiple=True)
    # Assert
    assert _missing_health_provider(observed)


@pytest.mark.parametrize("options", [[], ["--json"]])
def test_health_cli_preserves_fix_confirmation(health_cli_files, options):
    # Arrange
    arguments = ["--fix", *options]
    # Act
    observed = _health_cli_result(health_cli_files, [], arguments)
    # Assert
    assert (
        observed["exit"] == 2 and observed["stdout"] == ""
        and "without --yes/-y" in observed["stderr"]
        and not observed["timed_out"] and observed["bytes_unchanged"]
    )


@pytest.mark.parametrize("options", [[], ["--fix", "--yes"]])
def test_health_cli_preflight_precedes_locked_database_access(health_cli_files, options):
    # Arrange
    paths, _ = health_cli_files
    # Act
    with closing(sqlite3.connect(paths[0])) as owner:
        owner.execute("BEGIN EXCLUSIVE")
        observed = _health_cli_result(health_cli_files, [], options, deadline=5)
        rows = owner.execute("SELECT id FROM samples").fetchall()
    # Assert
    assert _missing_health_provider(observed) and rows == [(7,)]
