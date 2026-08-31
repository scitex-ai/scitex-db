#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pin the skill docs to the code they document.

Every ``db.<method>(`` shown in a skill's Python example must resolve to a
method that is actually IMPLEMENTED on the class the example constructs.

Why this is a test and not a review note: on 2026-08-02 a six-line
quick-start example had three lines that could not run --
``create_table(name, df)`` (the real signature takes a column dict),
``db.insert(df, table)`` (declared in ``_BaseQueryMixin``, never
overridden, so it raises ``NotImplementedError``) and
``db.read_table(...)`` (a name that exists nowhere in the package).
``13_mixins.md`` listed twelve such names and claimed they were callable,
which was false in 23 places. Nothing failed, because prose has no test.

A name DECLARED in ``_BaseMixins`` but whose whole body is
``raise NotImplementedError`` does not count as implemented -- that
distinction is the entire point. Counting it would make this gate green
against exactly the docs that sent the 2026-08-02 reader into a traceback.

The check is static (``ast`` over the source tree) rather than
``getattr``-based so that it runs identically whether or not the optional
``psycopg2`` extra is installed; a gate that silently skips when a
dependency is missing is not a gate.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "scitex_db"
_SKILLS = _SRC / "_skills" / "scitex-db"

_PY_FENCE = re.compile(r"```python\n(.*?)```", re.DOTALL)
_DB_CALL = re.compile(r"\bdb\.([a-z_][a-z0-9_]*)\s*\(")


def _is_abstract(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the body is nothing but ``raise NotImplementedError``."""
    body = [
        stmt
        for stmt in node.body
        if not (
            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        )
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Raise):
        return False
    exc = body[0].exc
    name = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(name, ast.Name) and name.id == "NotImplementedError"


def _implemented_methods(*roots: Path) -> set[str]:
    """Method names with a real body, across every class under ``roots``."""
    found: set[str] = set()
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    if isinstance(
                        stmt, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and not _is_abstract(stmt):
                        found.add(stmt.name)
    return found


def _doc_examples() -> list[tuple[Path, str]]:
    """Every Python fence in every skill markdown file."""
    return [
        (path, block)
        for path in sorted(_SKILLS.rglob("*.md"))
        for block in _PY_FENCE.findall(path.read_text(encoding="utf-8"))
    ]


@pytest.fixture
def postgres_methods() -> set[str]:
    return _implemented_methods(_SRC / "_postgresql", _SRC / "_BaseMixins")


def test_every_documented_db_method_exists_somewhere(
    postgres_methods: set[str],
) -> None:
    # Arrange
    known = postgres_methods
    # Act
    unknown = [
        f"{path.name}: db.{name}()"
        for path, block in _doc_examples()
        for name in _DB_CALL.findall(block)
        if name not in known
    ]
    # Assert
    assert not unknown, (
        "skill docs call methods PostgreSQL does not implement "
        f"(rename them or implement them): {sorted(set(unknown))}"
    )


def test_the_abstract_detector_can_actually_fire() -> None:
    # Arrange
    source = "class C:\n    def f(self):\n        raise NotImplementedError\n"
    node = ast.parse(source).body[0].body[0]
    # Act
    verdict = _is_abstract(node)
    # Assert
    assert verdict is True, (
        "_is_abstract failed to recognise a bare NotImplementedError body; "
        "with it broken the gate above would pass against any doc"
    )


def test_the_abstract_detector_does_not_over_fire() -> None:
    # Arrange
    source = "class C:\n    def f(self):\n        return 1\n"
    node = ast.parse(source).body[0].body[0]
    # Act
    verdict = _is_abstract(node)
    # Assert
    assert verdict is False, (
        "_is_abstract called a real implementation abstract; the gate would "
        "then reject correct documentation"
    )


# EOF
