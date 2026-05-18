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

| Sub-command | Purpose                                    |
|-------------|--------------------------------------------|
| `inspect`   | Dump schema for a database                 |
| `health`    | Run integrity + health checks on one or more databases |

### scitex-db inspect

```
scitex-db inspect <db_path> [--tables TBL [TBL ...]] [--quiet]
```

* `db_path` — SQLite3 file
* `--tables` — only inspect the named tables (default: all)
* `--quiet` — minimal output

Wraps `scitex_db.inspect()`.

### scitex-db health

```
scitex-db health <db_path> [<db_path> ...] [--fix] [--quiet]
```

* One path → calls `check_health(path, fix_issues=--fix)`
* Many paths → calls `batch_health_check(paths, fix_issues=--fix)`
* `--fix` — attempt to repair where possible
* `--quiet` — minimal output

No other sub-commands exist; running `scitex-db` with no arguments
prints help and exits non-zero.
