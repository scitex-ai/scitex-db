#!/usr/bin/env python3
"""Tests for scitex_db._linter_plugin."""

from scitex_dev.linter.checker import lint_source

from scitex_db._linter_plugin import _SQLite3ConstructionChecker, get_plugin


def _ids(issues):
    return [i.rule.id for i in issues]


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
    import ast

    src = "from scitex_db import SQLite3\ndb = SQLite3('x.db')\n"
    tree = ast.parse(src)
    chk = _SQLite3ConstructionChecker(src.splitlines())
    # Act
    chk.visit(tree)
    # Assert
    assert chk._source(999) == ""
