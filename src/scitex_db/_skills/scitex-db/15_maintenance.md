---
description: |
  [TOPIC] Maintenance
  [DETAILS] SQLite path helpers, read-only duplicate previews and current health limitations.
tags: [scitex-db-maintenance, scitex-db]
---

# Maintenance Helpers

These standalone helpers accept an on-disk SQLite database path. An open
`SQLite3` instance is unnecessary; these are not PostgreSQL connection helpers.

## Preview duplicate rows

`delete_sqlite3_duplicates(lpath_db, table_name, columns="all",
include_blob=False, chunk_size=10000, dry_run=True)` returns
`(total_rows, duplicate_rows)`. The default preview opens an existing file in
SQLite read-only mode and counts groups without creating or dropping tables.
Rows with the same selected values, including NULL values, belong to one group.
With `columns="all"`, primary keys, BLOB columns (unless `include_blob=True`)
and names ending in `_at` are excluded. Explicit column names select the
comparison fields instead. `chunk_size` is currently unused; this is not a
bounded-memory or chunked deduplication API.

Failures are logged and return `(None, None)`; a missing file is not created
by preview. The legacy `delete_duplicates` alias emits `DeprecationWarning`
and forwards the same path arguments. Use `table_name=`, not `table=`.

Apply mode (`dry_run=False`) still rebuilds the table and can discard its
constraints, indexes and triggers, and replace an existing `<table>_temp`.
Schema-preserving application remains unresolved and is not demonstrated here.
Read-only preview does not qualify apply mode or concurrent/WAL behavior.

## Inspect and health reports

`inspect(db_path, table_names=None, sample_size=5, verbose=True, ...)` returns
a list of table dictionaries with `table_name`, `columns`, `row_count`,
`is_approximate` and `sample_data`. Column dictionaries include type, primary
key and NULL metadata. BLOB samples use size placeholders. Index metadata is
not included. Large-table counts can be approximate; see the `is_approximate`
field rather than assuming every `row_count` is an integer.

`check_health(db_path, verbose=True, fix_issues=False)` returns a report with
`database_path`, `exists`, `accessible`, `integrity`, `tables`, `issues`,
`stats`, `recommendations` and `loadability`. A completed scan also adds
`health_score` and `status`; early returns, such as a missing file, omit them.
There are no `ok` or `fixed` keys. Existing-file scans currently depend on
undeclared umbrella `scitex` imports in loadability helpers and can fail in a
core-only install. The CLI preflight described in
[10_cli-reference.md](10_cli-reference.md) reports that missing provider before
scanning; it does not complete the health check.

`batch_health_check` aggregates per-path reports when it completes, but its
missing-file aggregation currently raises `KeyError("status")`. Completed
health checks, repair behavior and that aggregation gap remain unqualified.

## Disposable preview example

This example creates and removes only its own temporary fixture. It verifies
the default preview, inspection shape and missing-file health early return;
it does not run repairs or apply deduplication.

```python
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from scitex_db import check_health, delete_sqlite3_duplicates, inspect

with TemporaryDirectory() as directory:
    path = Path(directory) / "maintenance.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            "CREATE TABLE measurements (id INTEGER PRIMARY KEY, name TEXT, value REAL);"
            "INSERT INTO measurements VALUES (1, 'alpha', 1), (2, 'alpha', 1), (3, 'beta', 2);"
            "CREATE TABLE measurements_temp (marker TEXT);"
            "INSERT INTO measurements_temp VALUES ('preserve me');"
        )
    original = path.read_bytes()
    preview = delete_sqlite3_duplicates(
        str(path), table_name="measurements", columns=["name", "value"]
    )
    assert preview == (3, 1)
    assert path.read_bytes() == original
    tables = inspect(
        str(path), table_names=["measurements"], sample_size=1, verbose=False
    )
    assert len(tables) == 1 and tables[0]["table_name"] == "measurements"
    assert tables[0]["row_count"] == 3 and len(tables[0]["sample_data"]) == 1
    missing = Path(directory) / "missing.db"
    report = check_health(str(missing), verbose=False, fix_issues=False)
    assert report["exists"] is False and report["issues"] and not missing.exists()
    assert not {"status", "health_score", "ok", "fixed"}.intersection(report)
    print(json.dumps({"preview": preview, "tables": len(tables), "missing": report["exists"]}))
```

Source: `_sqlite3/_delete_duplicates.py`, `_delete_duplicates.py`, `_inspect.py`
and `_check_health.py`. Behavioral controls:
`tests/scitex_db/_sqlite3/test__delete_duplicates_preview.py` and the existing
`tests/scitex_db/test__inspect.py`. The example's installed execution is a
separate content check; static validation alone does not accept these claims.
