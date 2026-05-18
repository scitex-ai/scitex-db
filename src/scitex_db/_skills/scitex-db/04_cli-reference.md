---
description: |
  [TOPIC] CLI reference
  [DETAILS] `scitex-db` console entry — check-health, inspect-db, list-python-apis, mcp.
tags: [scitex-db-cli-reference]
---

# CLI Reference

```
scitex-db [OPTIONS] COMMAND [ARGS]...
```

Database utilities — SQLite/Postgres inspection and health checks.

## Global options

| Flag | Purpose |
|---|---|
| `-V`, `--version` | Show the version and exit |
| `--help-recursive` | Show help for the root and every subcommand |
| `--json` | Emit machine-readable JSON output where supported |
| `-h`, `--help` | Show this message and exit |

## Configuration precedence (highest → lowest)

1. Explicit CLI flags
2. `./config.yaml` (project-local)
3. `$SCITEX_DB_CONFIG` (path to a YAML file)
4. `~/.scitex/db/config.yaml` (user-wide)
5. Built-in defaults

## Commands

| Command | Purpose |
|---|---|
| `check-health` | Check database health and optionally repair issues |
| `inspect-db` | Inspect a database's structure (tables, schemas, row counts) |
| `list-python-apis` | List the public Python API surface of `scitex_db` |
| `mcp` | MCP (Model Context Protocol) server management |

## Examples

```bash
scitex-db inspect-db trials.db
scitex-db check-health trials.db --json
scitex-db list-python-apis
scitex-db mcp --help
```

For per-command flags, run `scitex-db <command> --help` or
`scitex-db --help-recursive`.

## See also

- [10_cli-reference.md](10_cli-reference.md) — historical/extended notes
