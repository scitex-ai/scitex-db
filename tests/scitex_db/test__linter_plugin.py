#!/usr/bin/env python3
"""Tests for scitex_db._linter_plugin.

The second half pins the DOCS to this plugin's rule corpus.

Why that is here: on 2026-08-02 ``docs/portable-store-seam-surface.md``
shipped to main in 0.2.0 telling another package to add ``STX-DB002``
"in the existing plugin beside ``STX-DB001``" and to "state its limits
as plainly as DB001 states its own" -- while this module existed on
neither ``main`` nor ``develop``. It sat only on a branch that had been
open for a month. A reader following that document would have gone
looking for a plugin that was not in the repository.

The rule-id and entry-point checks are static (``ast`` over this file's
source, ``tomllib`` over ``pyproject.toml``) rather than import- or
``importlib.metadata``-based, so they report the same verdict whether or
not the package happens to be installed in the running environment. A
gate that silently skips when something is missing is not a gate.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from scitex_dev.linter.checker import lint_source

from scitex_db._linter_plugin import _SQLite3ConstructionChecker, get_plugin

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the project floor is 3.11
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_SRC = _ROOT / "src" / "scitex_db" / "_linter_plugin.py"
_PYPROJECT = _ROOT / "pyproject.toml"
_ENTRY_POINT_GROUP = "scitex_dev.linter.plugins"

_RULE_ID = re.compile(r"\bSTX-DB\d+\b")

# Rule ids prose may name WITHOUT this package defining them yet, each with a
# written reason. Itemised deliberately: a blanket "ignore undefined ids" flag
# would also hide the STX-DB001 drift this gate exists to catch.
# Delete an entry the moment its rule lands -- a stale exemption is a dead gate.
_PROPOSED_NOT_YET_IMPLEMENTED = {
    "STX-DB002": (
        "Open proposal in docs/portable-store-seam-surface.md: flag "
        "Path(<env lookup>) for *_DB|*_URL|*_DSN|*_STORE* names, closing the "
        "bypass that no type can reach. Specified for the portable-store "
        "seam; not yet built."
    ),
}


def _ids(issues):
    return [i.rule.id for i in issues]


def _defined_rule_ids(source: str) -> set[str]:
    """Rule ids this plugin constructs, read statically from its source."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "Rule":
            continue
        for kw in node.keywords:
            if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                found.add(kw.value.value)
    return found


def _prose_files() -> list[Path]:
    """Every markdown file that can make a claim about this plugin."""
    return sorted(
        [*(_ROOT / "docs").rglob("*.md")]
        + [*(_ROOT / "src" / "scitex_db" / "_skills").rglob("*.md")]
    )


def test_get_plugin_shape_keys():
    # Arrange
    # Act
    p = get_plugin()
    # Assert
    assert set(p.keys()) >= {"rules", "call_rules", "axes_hints", "checkers"}


def test_get_plugin_shape_expected_rule_ids():
    # Arrange
    # Act
    rule_ids = {r.id for r in get_plugin()["rules"]}
    # Assert
    assert "STX-DB001" in rule_ids


def test_get_plugin_shape_checkers_include_sqlite3_construction_checker():
    # Arrange
    # Act
    p = get_plugin()
    # Assert
    assert any(c is _SQLite3ConstructionChecker for c in p["checkers"])


def test_get_plugin_shape_axes_hints_empty():
    # Arrange
    # Act
    p = get_plugin()
    # Assert
    assert p["axes_hints"] == {}


def test_db001_bare_sqlite3_call_detected():
    # Arrange
    src = "from scitex_db import SQLite3\ndb = SQLite3('x.db')\n"
    # Act
    issues = lint_source(src)
    # Assert
    assert "STX-DB001" in _ids(issues)


def test_db001_attribute_sqlite3_call_detected():
    # Arrange
    src = "import scitex as stx\ndb = stx.db.SQLite3('x.db')\n"
    # Act
    issues = lint_source(src)
    # Assert
    assert "STX-DB001" in _ids(issues)


def test_db001_unrelated_call_not_flagged():
    # Arrange
    src = "foo('x.db')\n"
    # Act
    issues = lint_source(src)
    # Assert
    assert "STX-DB001" not in _ids(issues)


def test_sqlite3constructionchecker_direct_len_issues_is_1():
    # Arrange
    import ast

    src = "from scitex_db import SQLite3\ndb = SQLite3('x.db')\n"
    tree = ast.parse(src)
    chk = _SQLite3ConstructionChecker(src.splitlines())
    # Act
    chk.visit(tree)
    # Assert
    assert len(chk.issues) == 1


def test_sqlite3constructionchecker_direct_issue_line_equals_2():
    # Arrange
    import ast

    src = "from scitex_db import SQLite3\ndb = SQLite3('x.db')\n"
    tree = ast.parse(src)
    chk = _SQLite3ConstructionChecker(src.splitlines())
    # Act
    chk.visit(tree)
    # Assert
    assert chk.issues[0].line == 2


def test_sqlite3constructionchecker_direct_chk_source_999():
    # Arrange
    src = "from scitex_db import SQLite3\ndb = SQLite3('x.db')\n"
    tree = ast.parse(src)
    chk = _SQLite3ConstructionChecker(src.splitlines())
    # Act
    chk.visit(tree)
    # Assert
    assert chk._source(999) == ""


@pytest.fixture
def defined_rule_ids() -> set[str]:
    if not _PLUGIN_SRC.exists():
        return set()
    return _defined_rule_ids(_PLUGIN_SRC.read_text(encoding="utf-8"))


def test_every_rule_id_named_in_prose_is_defined_by_the_plugin(
    defined_rule_ids: set[str],
) -> None:
    # Arrange
    # Act
    known = defined_rule_ids | set(_PROPOSED_NOT_YET_IMPLEMENTED)
    dangling = [
        f"{path.relative_to(_ROOT)}: {rule_id}"
        for path in _prose_files()
        for rule_id in sorted(
            set(_RULE_ID.findall(path.read_text(encoding="utf-8")))
        )
        if rule_id not in known
    ]
    # Assert
    assert not dangling, (
        "prose names a linter rule this package neither defines nor lists as "
        "an open proposal -- add the rule to src/scitex_db/_linter_plugin.py, "
        "or add it to _PROPOSED_NOT_YET_IMPLEMENTED with a written reason, or "
        f"stop citing it as existing: {sorted(set(dangling))}"
    )


def test_no_stale_entries_in_the_proposed_rule_exemption_list(
    defined_rule_ids: set[str],
) -> None:
    # Arrange
    # Act
    landed = sorted(set(_PROPOSED_NOT_YET_IMPLEMENTED) & defined_rule_ids)
    # Assert
    assert not landed, (
        "these rules are now implemented but are still listed as proposals in "
        "_PROPOSED_NOT_YET_IMPLEMENTED -- delete the entries, or the gate "
        f"stops checking prose about them: {landed}"
    )


def test_the_documented_entry_point_group_is_declared_in_pyproject() -> None:
    # Arrange
    declared = (
        tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        .get("project", {})
        .get("entry-points", {})
        .get(_ENTRY_POINT_GROUP, {})
    )
    # Act
    citing = [
        str(path.relative_to(_ROOT))
        for path in _prose_files()
        if _ENTRY_POINT_GROUP in path.read_text(encoding="utf-8")
    ]
    # Assert
    assert not citing or declared, (
        f"prose tells the reader this package registers into the "
        f"'{_ENTRY_POINT_GROUP}' entry-point group, but pyproject.toml "
        f"declares no such group, so scitex-linter would never discover the "
        f"plugin: cited in {citing}"
    )


def test_the_rule_id_extractor_can_actually_fire() -> None:
    # Arrange
    source = 'Rule(id="STX-DB001", severity="warning")\n'
    # Act
    found = _defined_rule_ids(source)
    # Assert
    assert found == {"STX-DB001"}, (
        "_defined_rule_ids failed to read a rule id it was handed; with it "
        "broken the prose gate above would pass against any document"
    )


def test_the_rule_id_extractor_does_not_over_fire() -> None:
    # Arrange
    source = 'NotARule(id="STX-DB999")\nx = "STX-DB998"\n'
    # Act
    found = _defined_rule_ids(source)
    # Assert
    assert found == set(), (
        "_defined_rule_ids invented rule ids from non-Rule code; the prose "
        "gate would then accept citations of rules that do not exist"
    )
