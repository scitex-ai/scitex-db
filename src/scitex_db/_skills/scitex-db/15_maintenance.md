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

Apply mode (`dry_run=False`) opens an existing file for writing and deletes
rows in a single `BEGIN IMMEDIATE` transaction, retaining the smallest native
ROWID in each selected group. It preserves the table definition, constraints,
indexes, triggers, AUTOINCREMENT sequence and unrelated `<table>_temp` data.
Foreign-key enforcement is enabled: normal DELETE triggers and foreign-key
actions (including cascading child deletes) run. SQL failures roll back the
transaction. Counts describe direct target-table deletes, excluding additional
trigger/cascade effects. Preview counts do not guarantee apply will succeed.

Apply refuses missing files, invalid/empty column-name selections, targets
without a native ROWID and tables shadowing all three native ROWID aliases.
Failures log and return `(None, None)`. It performs no automatic `VACUUM` or
table rebuild. Ordinary ROWID tables are the verified scope; virtual tables,
concurrent/WAL behavior and large-database performance remain unqualified.

## Copy with VACUUM INTO

On an open SQLite3 instance, `vacuum(into=destination)` copies the database to
that destination. The filename is converted to text and bound as a SQL value, including
apostrophes;
do not add SQL quotes yourself. This is a separate instance method from the
standalone path helpers above. Like ordinary `vacuum()`, it commits any pending
transaction before running, so use it at an intentional transaction boundary.
It returns `None`; SQLite errors are wrapped as `ValueError`.

Native controls in `tests/scitex_db/_sqlite3/_SQLite3Mixins/test__MaintenanceMixin.py` verify
literal destinations, rows, an index and `user_version`; the existing
`test__SQLite3.py` covers ordinary vacuum/optimize. This does not qualify repair,
concurrent/WAL or NFS behavior, or large-database performance.

## Inspect and health reports

`inspect(db_path, table_names=None, sample_size=5, verbose=True, ...)` returns
a list of table dictionaries with `table_name`, `columns`, `row_count`,
`is_approximate` and `sample_data`. Column dictionaries include type, primary
key and NULL metadata. Default BLOB size placeholders are projected in SQLite
using each value's runtime type and byte length, so the BLOB payload is not
transferred into Python merely to format its label. Empty BLOBs, NULLs, text
and mixed storage types retain their existing result semantics. Index metadata is
not included. Counts below 100,000 are exact integers with
`is_approximate=False`. The capped probe reports `row_count=">=100,000"` and
`is_approximate=True` once it sees 100,000 rows, including a table with exactly
that many rows. This is an inclusive lower bound, not an exact count or a claim
of strictly more rows. `skip_count=True` returns `"Not counted"` and a null
approximation flag. The existing count queries and 100,000-row probe cap are
unchanged.

Table names are literal SQLite identifiers, including spaces, reserved words,
quotes, Unicode and dots within a name. Pass the native name without adding SQL
quotes; SQL fragments and schema-qualified expressions are not accepted as
selection syntax. Default discovery also handles these table names.

Inspection opens an existing file through a SQLite read-only URI. The reusable
`OptimizedInspector.connection()` cursor rejects SQL writes. Removing the file
before lazy open or after close makes the next open fail without recreating it.
Connection reuse and the metadata result format are preserved; concurrent/WAL
behavior remains outside this selected qualification.
`inspect_fast(skip_blob_content=False)` still returns native bytes. Direct
`get_table_stats_batch` calls also keep raw bytes by default; its new optional
`skip_blob_content=True` enables SQL projection. Row counting and sample limits
are unchanged. Selected 16 MiB fixture checks measure Python allocations only,
not RSS, SQLite native heap, disk I/O or out-of-RAM/chunked/range performance.
Large sample counts can still consume substantial memory.

`check_health(db_path, verbose=True, fix_issues=False)` returns a report with
`database_path`, `exists`, `accessible`, `integrity`, `tables`, `issues`,
`stats`, `recommendations` and `loadability`. A completed scan also adds
`health_score` and `status`; early returns, such as a missing file, omit them.
There are no `ok` or `fixed` keys. Existing-file scans currently depend on
undeclared umbrella `scitex` imports in loadability helpers and can fail in a
core-only install. The CLI preflight described in
[10_cli-reference.md](10_cli-reference.md) reports that missing provider before
scanning; it does not complete the health check.

`batch_health_check` returns the per-path reports unchanged and logs a summary.
Reports without a `status`, such as missing-file early returns, count as
`Incomplete`; no healthy/critical classification or score is invented. Empty
input returns an empty dictionary, and repeated paths retain one mapping entry.
This does not complete existing-file scans: the provider, completed health
checks and repair behavior remain unqualified.

## Disposable preview and apply example

This example creates and removes only its own temporary fixture. It verifies
the default preview, inspection shape and missing-file health early return;
then applies deduplication only to that owned fixture. It does not run repairs.

```python
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from scitex_db import batch_health_check, check_health, delete_sqlite3_duplicates, inspect

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
    assert path.read_bytes() == original
    applied = delete_sqlite3_duplicates(
        str(path), table_name="measurements", columns=["name", "value"], dry_run=False
    )
    assert applied == (3, 1)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        assert connection.execute("SELECT id FROM measurements ORDER BY id").fetchall() == [(1,), (3,)]
        assert connection.execute("PRAGMA table_info(measurements)").fetchone()[5] == 1
        assert connection.execute("SELECT marker FROM measurements_temp").fetchall() == [("preserve me",)]
    missing = Path(directory) / "missing.db"
    report = check_health(str(missing), verbose=False, fix_issues=False)
    assert report["exists"] is False and report["issues"] and not missing.exists()
    assert not {"status", "health_score", "ok", "fixed"}.intersection(report)
    batch = batch_health_check([str(missing)], verbose=False, fix_issues=False)
    assert batch == {str(missing): report} and not missing.exists()
    print(json.dumps({"preview": preview, "applied": applied, "tables": len(tables), "missing": report["exists"]}))
```

Source: `_sqlite3/_delete_duplicates.py`, `_delete_duplicates.py`, `_inspect.py`
and `_check_health.py`. Behavioral controls:
`tests/scitex_db/_sqlite3/test__delete_duplicates_preview.py` and the existing
`tests/scitex_db/test__inspect.py` and
`tests/scitex_db/test__check_health_batch.py` and
`tests/scitex_db/test__inspect_readonly.py` and
`tests/scitex_db/_sqlite3/test__delete_duplicates_apply.py` and
`tests/scitex_db/test__inspect_blob_projection.py` and
`tests/scitex_db/test__inspect_identifiers.py` and
`tests/scitex_db/test__inspect_count_boundary.py`. The example's installed execution is a
separate content check; static validation alone does not accept these claims.
