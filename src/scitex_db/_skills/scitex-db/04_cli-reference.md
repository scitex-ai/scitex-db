---
description: |
  [TOPIC] CLI reference
  [DETAILS] `scitex-db` console entry — list-python-apis, mcp, skills.
tags: [scitex-db-cli-reference]
---

# CLI Reference

```
scitex-db [OPTIONS] COMMAND [ARGS]...
```

Database utilities — PostgreSQL helpers for the SciTeX ecosystem.

The CLI is deliberately thin: `scitex-db` is a **library first**. The
console entry point exists for introspection and skill management, not
as an administration tool — use `psql` for that.

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
| `list-python-apis` | List the public Python API surface of `scitex_db` |
| `mcp list-tools` | MCP tools exposed by scitex-db (none — library-only) |
| `skills` | List / get / install agent-facing skills |

Plus `install-shell-completion` / `print-shell-completion` when
`scitex-dev` is installed.

## Examples

```bash
scitex-db list-python-apis
scitex-db list-python-apis --json
scitex-db mcp list-tools
scitex-db skills list
```

For per-command flags, run `scitex-db <command> --help` or
`scitex-db --help-recursive`.
