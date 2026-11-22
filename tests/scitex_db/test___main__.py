"""Observe the CLI configuration gap until the intended loader is implemented.

These controls record ignored files; successful commands do not qualify a
configuration loader or its precedence. Update them when that feature lands.
"""

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
