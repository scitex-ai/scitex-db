---
description: |
  [TOPIC] Cli Reference
  [DETAILS] See file body for details.
tags: [scitex-db-cli-reference, scitex-db]
---


# CLI Reference

`scitex-db` ships a console entry point declared in `pyproject.toml`:

```toml
[project.scripts]
scitex-db = "scitex_db.__main__:main"
```

## Sub-commands

| Sub-command      | Purpose                                    |
|------------------|--------------------------------------------|
| `inspect-db`     | Inspect a database's structure (tables, schemas, row counts) |
| `check-health`   | Check database health and optionally repair issues |
| `list-python-apis` | List the public Python API surface of `scitex_db` |
| `mcp`            | MCP (Model Context Protocol) server management |
| `skills`         | List / get / install agent-facing skills |

### scitex-db inspect-db

```
scitex-db inspect-db <db_path> [--tables TBL [TBL ...]] [--quiet] [--json]
```

* `db_path` — SQLite3 file
* `--tables` — only inspect the named tables (default: all)
* `--quiet` — minimal output
* `--json` — machine-readable JSON output

Wraps `scitex_db.inspect()`.

### scitex-db check-health

```
scitex-db check-health <db_path> [<db_path> ...] [--fix] [--quiet] [--dry-run] [--json]
```

* One path → calls `check_health(path, fix_issues=--fix)`
* Many paths → calls `batch_health_check(paths, fix_issues=--fix)`
* `--fix` — attempt to repair where possible
* `--quiet` — minimal output
* `--dry-run` — preview what --fix would do
* `--json` — machine-readable JSON output

### scitex-db list-python-apis

```
scitex-db list-python-apis [--json]
```

Lists the public Python API surface of `scitex_db`.

### scitex-db skills

```
scitex-db skills {list|get|install}
```

Agent-facing skill management. See `scitex-db skills --help` for details.
