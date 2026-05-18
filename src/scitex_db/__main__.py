#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scitex-db CLI — database inspection and health checks (Click)."""

from __future__ import annotations

import json
import sys

import click


def _get_version() -> str:
    try:
        from importlib.metadata import version

        return version("scitex-db")
    except Exception:
        return "0.0.0"


def _print_help_recursive(ctx: click.Context, _param, value):
    """Show flattened help for the root and every subcommand."""
    if not value or ctx.resilient_parsing:
        return
    cmd = ctx.command
    click.echo(cmd.get_help(ctx))
    if isinstance(cmd, click.Group):
        for name in sorted(cmd.commands):
            sub = cmd.commands[name]
            sub_ctx = click.Context(sub, info_name=name, parent=ctx)
            click.echo("\n---\n")
            click.echo(sub.get_help(sub_ctx))
    ctx.exit(0)


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(_get_version(), "-V", "--version", prog_name="scitex-db")
@click.option(
    "--help-recursive",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_print_help_recursive,
    help="Show help for the root and every subcommand.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON output where supported.",
)
@click.pass_context
def main(ctx, as_json):
    """Database utilities — SQLite/Postgres inspection and health checks.

    \b
    Configuration precedence (highest -> lowest):
      1. Explicit CLI flags
      2. ./config.yaml (project-local)
      3. $SCITEX_DB_CONFIG (path to a YAML file)
      4. ~/.scitex/db/config.yaml (user-wide)
      5. Built-in defaults
    """
    ctx.ensure_object(dict)
    ctx.obj["as_json"] = as_json
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command("inspect-db")
@click.argument("db_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--tables",
    multiple=True,
    help="Restrict inspection to the named tables (repeatable).",
)
@click.option("--quiet", "-q", is_flag=True, default=False, help="Minimal output.")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON output.",
)
def inspect_db(db_path, tables, quiet, as_json):
    """Inspect a database's structure (tables, schemas, row counts).

    \b
    Example:
        $ scitex-db inspect-db ./mydb.sqlite
        $ scitex-db inspect-db ./mydb.sqlite --tables users orders
    """
    from ._inspect import inspect

    inspect(db_path, table_names=list(tables) or None, verbose=not quiet)


@main.command("check-health")
@click.argument(
    "db_paths", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.option(
    "--fix", is_flag=True, default=False, help="Attempt to fix detected issues."
)
@click.option("--quiet", "-q", is_flag=True, default=False, help="Minimal output.")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what --fix would do without applying changes.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation when --fix is used.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON output.",
)
def check_health(db_paths, fix, quiet, dry_run, yes, as_json):
    """Check database health and optionally repair issues.

    \b
    Example:
        $ scitex-db check-health ./mydb.sqlite
        $ scitex-db check-health ./db1.sqlite ./db2.sqlite
        $ scitex-db check-health ./mydb.sqlite --fix --yes
    """
    from ._check_health import batch_health_check
    from ._check_health import check_health as _check

    if dry_run and fix:
        click.echo("Dry-run: --fix would attempt repair on listed databases.", err=True)
        fix = False
    if fix and not yes:
        click.echo(
            f"Refusing to --fix {len(db_paths)} database(s) without --yes/-y. "
            "Re-run with --dry-run to preview, or --yes to apply.",
            err=True,
        )
        sys.exit(2)

    if len(db_paths) == 1:
        _check(db_paths[0], verbose=not quiet, fix_issues=fix)
    else:
        batch_health_check(list(db_paths), verbose=not quiet, fix_issues=fix)


@main.group()
def mcp():
    """MCP (Model Context Protocol) server management."""


@mcp.command("list-tools")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def mcp_list_tools(as_json):
    """List MCP tools exposed by scitex-db (none — library-only).

    \b
    Example:
        $ scitex-db mcp list-tools
    """
    tools: list[str] = []
    if as_json:
        click.echo(json.dumps({"tools": tools}, indent=2))
    else:
        click.echo("(no MCP tools registered)")


@main.command("list-python-apis")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit JSON.",
)
def list_python_apis(as_json):
    """List the public Python API surface of scitex_db.

    \b
    Example:
        $ scitex-db list-python-apis
        $ scitex-db list-python-apis --json
    """
    apis = [
        "scitex_db._inspect.inspect",
        "scitex_db._check_health.check_health",
        "scitex_db._check_health.batch_health_check",
    ]
    if as_json:
        click.echo(json.dumps({"apis": apis}, indent=2))
    else:
        for a in apis:
            click.echo(a)


# audit-cli §1a — packages with _skills/ MUST expose
# `<cli> skills {list,get,install}`.
from ._skills import skills_group as _skills_group

main.add_command(_skills_group, name="skills")

# audit-cli §1a — wire `install-shell-completion` / `print-shell-completion`
try:
    from scitex_dev._cli._completion import attach_shell_completion

    attach_shell_completion(main, prog_name="scitex-db")
except Exception:
    # scitex-dev not installed (e.g. minimal runtime install) — skip silently;
    # tab-completion is a developer convenience, not a runtime dependency.
    pass

if __name__ == "__main__":
    sys.exit(main() or 0)


# audit §4 — inject version into root --help
try:
    from importlib.metadata import version as _v

    main.help = f"scitex-db (v{_v('scitex-db')}) — " + (main.help or "").lstrip()
except Exception:
    pass
