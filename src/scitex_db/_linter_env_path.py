"""Syntactic store-environment/Path warning; no evaluation or alias analysis."""

import ast


def _environ(node):
    return (isinstance(node, ast.Name) and node.id == "environ") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr == "environ"
    )


def _store_environment(node):
    key = None
    if isinstance(node, ast.Subscript) and _environ(node.value):
        key = node.slice
    elif isinstance(node, ast.Call):
        func = node.func
        getenv = (isinstance(func, ast.Name) and func.id == "getenv") or (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
            and func.attr == "getenv"
        )
        env_get = (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and _environ(func.value)
        )
        if getenv or env_get:
            key = node.args[0] if node.args else next(
                (kw.value for kw in node.keywords if kw.arg == "key"), None
            )
    if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
        return False
    name = key.value.upper()
    return name.endswith(("_DB", "_URL", "_DSN")) or "_STORE" in name


class _StoreEnvironmentPathChecker(ast.NodeVisitor):
    """Warn once per canonical Path call with a direct store-env argument.

    Names are syntactic: imports, aliases, rebinding and wrappers are not
    resolved. A matching variable may hold a genuine path; this is a review
    warning, not a DSN detector, runtime barrier or automatic rewrite.
    """

    category = "io"

    def __init__(self, lines, config=None):
        self._lines = lines
        self.issues = []

    def visit_Call(self, node):
        func = node.func
        path = (isinstance(func, ast.Name) and func.id == "Path") or (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "pathlib"
            and func.attr == "Path"
        )
        if path and any(_store_environment(arg) for arg in node.args):
            from ._linter_plugin import _load_scitex_dev, _store_path_rule

            Rule, Issue = _load_scitex_dev()
            self.issues.append(
                Issue(
                    rule=_store_path_rule(Rule),
                    line=node.lineno,
                    col=node.col_offset,
                    source_line=(
                        self._lines[node.lineno - 1]
                        if 0 < node.lineno <= len(self._lines) else ""
                    ),
                )
            )
        self.generic_visit(node)
