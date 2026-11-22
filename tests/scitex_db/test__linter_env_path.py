"""Exercise the installed leaf checker through Dev's real dispatch path."""

import pytest
from scitex_dev.linter.checker import lint_source


def _db002(source):
    return [issue for issue in lint_source(source) if issue.rule.id == "STX-DB002"]


@pytest.mark.parametrize(
    "expression",
    [
        'Path(os.environ["APP_DB"])',
        'pathlib.Path(os.environ.get("DATABASE_URL"))',
        'Path(os.getenv("APP_DSN", "default"))',
        'Path(environ["APP_STORE_DIR"])',
        'Path(environ.get("APP_STORE"))',
        'Path(getenv("app_db"))',
        'Path(os.getenv(key="APP_URL"))',
        'Path("/owned", os.environ["APP_DB"])',
        'Path(os.environ["ONE_DB"], os.getenv("TWO_URL"))',
    ],
)
def test_direct_store_environment_path_warns_once(expression):
    # Arrange
    source = "location = " + expression + "\n"
    # Act
    issues = _db002(source)
    # Assert
    assert [(i.rule.severity, "resolve_store" in i.rule.suggestion) for i in issues] == [
        ("warning", True)
    ]


@pytest.mark.parametrize(
    "source",
    [
        'Path("postgresql://example.invalid/research")',
        'Path(os.environ["HOME"])',
        'Path(os.getenv("APP_DB_CONFIG"))',
        'Path(os.getenv(variable))',
        'value = os.environ["APP_DB"]; Path(value)',
        'Path(resolve_store(env="APP_DB").path)',
        'P(os.environ["APP_DB"])',
        'paths.Path(os.environ["APP_DB"])',
        'Path(other.getenv("APP_DB"))',
        '# Path(os.environ["APP_DB"])\n',
        'Path(os.environ["DB"])',
        'Path(env["APP_DB"])',
    ],
)
def test_unrelated_or_out_of_scope_shapes_are_not_claimed(source):
    # Arrange
    # The case supplies an unexecuted source snippet.
    # Act
    issues = _db002(source)
    # Assert
    assert issues == []


def test_warning_reports_original_location_without_executing_source():
    # Arrange
    source = 'raise RuntimeError("must not execute")\np = Path(os.getenv("APP_DB"))\n'
    # Act
    issues = _db002(source)
    # Assert
    assert [(i.line, i.col, i.source_line) for i in issues] == [
        (2, 4, source.splitlines()[1])
    ]
