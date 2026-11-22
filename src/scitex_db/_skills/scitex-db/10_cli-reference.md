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
scitex-db inspect-db <db_path> [--tables TBL]... [--quiet] [--json]
```

* `db_path` — SQLite3 file
* `--tables` — only inspect the named tables (default: all)
* `--quiet` — minimal output
* `--json` — emit the inspection result as standard JSON; the global flag
  `scitex-db --json inspect-db ...` has the same effect

Wraps `scitex_db.inspect()`. JSON is a list of tables with `table_name`,
`columns`, `row_count`, `is_approximate` and `sample_data`. Sample values retain
SQLite integers, finite reals, strings and nulls. The default is up to five
sample rows per table. BLOB samples are strings such as `<BLOB 3 bytes>`, not
raw bytes or decoded scientific arrays. Repeated `--tables` flags select
and order the tables. `--quiet` suppresses human output, not JSON output.
Non-finite numbers such as infinity cannot be encoded as standard JSON:
the command exits nonzero, writes the error to stderr and leaves stdout empty.

```bash
scitex-db inspect-db trials.db --tables trials --tables participants --json
scitex-db --json inspect-db trials.db
```

The owning callback is `scitex_db.__main__.inspect_db`. Actual subprocess
controls in `tests/scitex_db/test___main__.py` check JSON flag positions,
quiet/human behavior, schema/types/Unicode/null/BLOB samples, table selection,
the five-row sample limit, non-finite refusal and unchanged database bytes.

### scitex-db check-health

```
scitex-db check-health <db_path> [<db_path> ...] [--fix] [--quiet] [--dry-run] [--json]
```

* One path → calls `check_health(path, fix_issues=--fix)`
* Many paths → calls `batch_health_check(paths, fix_issues=--fix)`
* `--fix` — attempt to repair where possible
* `--quiet` — minimal output
* `--dry-run` — preview what --fix would do
* `--json` — accepted by the current callback, but health-result JSON
  serialization remains unimplemented; this is not the inspection JSON path

When the `scitex` loadability provider cannot be found, the CLI exits with
code 1, empty stdout and a named missing-provider error on stderr before any
SQLite scan or repair. Core installs do not supply this provider. The presence
check does not import or validate its implementation. `--fix` without `--yes`
still refuses with code 2 before this preflight; `--fix --dry-run` never
repairs. Neither health JSON nor provider functionality is implemented by
this guard.

Owning source: `scitex_db.__main__.check_health`. Actual controls in
`tests/scitex_db/test___main__.py` cover ordinary/quiet/JSON/global-JSON,
confirmed-fix/dry-run, multiple paths, consent priority and a real exclusive
SQLite lock. The locked controls keep their owned child below five seconds,
shorter than the unchanged native scan's ten-second connection timeout.
Database bytes and seeded rows remain unchanged. These controls qualify the
missing-provider path only; provider-present health/loadability/repair
behavior remains unverified.

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
