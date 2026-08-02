"""Linter plugin for scitex-db: DB-specific rules (DB001).

Registered via entry point 'scitex_dev.linter.plugins' so scitex-linter
discovers this rule automatically when scitex-db is installed.

Mirrors scitex-io's `_linter_plugin.py` pattern (STX-IO001-015): plain
AST detection, no attempt to see through wrapper functions.
"""

import ast


class _SQLite3ConstructionChecker(ast.NodeVisitor):
    """Flag `SQLite3(...)` construction (STX-DB001).

    `SQLite3` is scitex-db's own recommended API — this rule does not
    claim direct instantiation is wrong. It exists because neurovista's
    2026-07-05 incident showed `SQLite3(...)` opened outside any
    stx.io-recorded path leaves the resulting .db file provenance-invisible
    (no clew data edge). AST detection can't tell whether a given call
    site is already routed through stx.io — it only fires wherever
    `SQLite3(` literally appears, same limitation as STX-IO015 for
    `sqlite3.connect`.
    """

    category = "io"

    def __init__(self, lines, config=None):  # signature dictated by checker.py
        self._lines = lines
        self._config = config
        self.issues = []

    def _source(self, lineno):
        if 1 <= lineno <= len(self._lines):
            return self._lines[lineno - 1]
        return ""

    def _is_sqlite3_construction(self, node):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "SQLite3"
        if isinstance(func, ast.Attribute):
            return func.attr == "SQLite3"
        return False

    def visit_Call(self, node):
        if self._is_sqlite3_construction(node):
            from scitex_dev.linter._rules._base import Rule
            from scitex_dev.linter.checker import Issue

            rule = Rule(
                id="STX-DB001",
                severity="warning",
                category="io",
                message=(
                    "`SQLite3(...)` construction detected — ensure this .db "
                    "file participates in stx.io provenance tracking"
                ),
                suggestion=(
                    "A bare `SQLite3(path)` produces no clew data edge, "
                    "however deeply it's wrapped — this rule only fires "
                    "where `SQLite3(` literally appears (AST detection "
                    "can't see through a custom loader wrapper around it).\n"
                    "  Route the resulting file through stx.io so it's "
                    "provenance-tracked: register a handler and use "
                    "`stx.io.save()`/`stx.io.load()`:\n"
                    "    from scitex_io import register_saver, register_loader\n"
                    "    @register_saver('.db')\n"
                    "    def save_db(obj, path, **kw): ...\n"
                    "    @register_loader('.db')\n"
                    "    def load_db(path, **kw): ..."
                ),
                requires="scitex",
            )
            self.issues.append(
                Issue(
                    rule=rule,
                    line=node.lineno,
                    col=node.col_offset,
                    source_line=self._source(node.lineno),
                )
            )
        self.generic_visit(node)


def get_plugin():
    """Return scitex-db linter rules, call mappings, and checkers."""
    from scitex_dev.linter._rules._base import Rule

    DB001 = Rule(
        id="STX-DB001",
        severity="warning",
        category="io",
        message=(
            "`SQLite3(...)` construction detected — ensure this .db file "
            "participates in stx.io provenance tracking"
        ),
        suggestion=(
            "Register a handler with `register_saver('.db')` / "
            "`register_loader('.db')` and route through "
            "`stx.io.save()`/`stx.io.load()`."
        ),
        requires="scitex",
    )

    return {
        "rules": [DB001],
        "call_rules": {},
        "axes_hints": {},
        "checkers": [_SQLite3ConstructionChecker],
    }
