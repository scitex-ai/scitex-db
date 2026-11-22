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

## Configuration limit

Configuration files are not implemented by the CLI. Supply database paths and
options explicitly, for example:

```bash
scitex-db inspect-db trials.db --tables trials --tables participants
```

`./config.yaml`, `$SCITEX_DB_CONFIG` and `~/.scitex/db/config.yaml` do not set
CLI defaults; `.env` is not loaded automatically. Valid and malformed files
are ignored. A successful inspection therefore does not establish that a
configuration file was parsed, validated or applied.

Portable project/user configuration under `.scitex/db` remains an intended
contract, not an implemented feature. There is no supported file precedence.
The Python `store.resolve_store(env=...)` helper separately reads the
caller-named environment variable; it is not a CLI configuration loader.

Owning behavior: `scitex_db.__main__.main` and `inspect_db`. The actual
subprocess controls in `tests/scitex_db/test_cli_configuration.py` exercise
valid/malformed project, environment-selected, user and `.env` locations,
explicit table selection, unchanged fixture bytes and the help disclosure.
These observations qualify the selected current limitation, not a loader.

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
