---
description: |
  [TOPIC] Python API
  [DETAILS] Public exports, backend differences and SQLite maintenance return values.
tags: [scitex-db-python-api]
---

# Python API

Import the standalone package with `import scitex_db`. Public attributes are
loaded lazily; PostgreSQL support requires the optional PostgreSQL dependencies
and can resolve to `None` when they are absent.

## Top-level exports (`__all__`)

| Symbol | Purpose |
|---|---|
| `SQLite3` | SQLite backend class |
| `PostgreSQL` | Optional PostgreSQL backend class |
| `delete_duplicates` | Deprecated alias forwarding SQLite path arguments |
| `delete_sqlite3_duplicates` | SQLite duplicate preview or explicit apply |
| `inspect` | Return a list of SQLite table dictionaries |
| `check_health` | SQLite health report; existing-file provider limitation below |
| `batch_health_check` | Mapping of database paths to health reports |
| `register_post_save_hook` | Register a callback for successful writes |
| `register_post_load_hook` | Register a callback for successful reads |
| `__version__` | Installed distribution version string |

The export list and lazy targets are owned by `src/scitex_db/__init__.py`.
Export presence does not establish a working PostgreSQL service or a completed
health scan.

## Backend classes

`SQLite3` and `PostgreSQL` compose backend-specific mixins; their surfaces
are not interchangeable. Both expose `get_table_names`, `insert_many`,
`get_rows`, `get_row_count` and `execute`. PostgreSQL additionally exposes
`get_tables`, `insert`, `select`, `count` and `execute_query`. SQLite does not
inherit the base mixin stubs; absent names are missing attributes.
See [13_mixins.md](13_mixins.md) and
[16_sqlite-to-postgres.md](16_sqlite-to-postgres.md) before porting code.

Use a context manager for each connection; see
[11_quick-start.md](11_quick-start.md) for a disposable SQLite example and
[17_readonly-workers.md](17_readonly-workers.md) for worker-local connections.
For arrays, `load_array` requires a column name and returns a leading row
dimension; [14_numpy-blob.md](14_numpy-blob.md) gives a checked save/load example.

## SQLite row-query errors

`SQLite3.get_rows(...)` preserves SQLite exception subclasses, original error
arguments and native error metadata, as `execute(...)` does. Missing tables
and incomplete SQL raise `sqlite3.OperationalError`, including when
`return_as` is `"dataframe"`, `"list"` or `"dict"`. The former generic
`sqlite3.Error("Query execution failed: ...")` wrapper is removed, so callers
can catch the native subclass. Successful result formats are unchanged.
Source owner: `_SQLite3Mixins/_RowMixin.py::get_rows`; native failure,
continued-read and format controls:
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__RowMixin_errors.py`.
This does not establish PostgreSQL error parity or change SQL construction.

## Filtered SQLite batches

`insert_many`/`replace_many` return `None` when a valid `where` excludes
all nonempty input rows; no batch INSERT/REPLACE executes. This case preserves
rows and schema in `ro` and `rwc`. Transaction-entry/commit policy is
unchanged; this is not an atomicity or pending-work guarantee.
Owner: `_SQLite3Mixins/_BatchMixin.py::_run_many`; native controls:
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__BatchMixin_filter.py`.

## SQLite lock waits

`SQLite3(path, timeout=60.0)` preserves SQLite's configured busy-handler budget
in `ro`, `rw` and `rwc` modes, including explicit `connect` and later `reconnect`.
The default is 60 seconds; `timeout=0.137` initializes `PRAGMA busy_timeout` to
137 milliseconds. Zero selects no busy waiting; pass `timeout=300.0` explicitly
for five minutes. This is SQLite lock-wait policy, not an overall operation or
filesystem-I/O deadline. Native policy and reconnect controls live in
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__ConnectionMixin_timeout.py`.

## Observer dispatch limits

`register_post_save_hook` and `register_post_load_hook` append process-local,
synchronous callbacks. Successful SQLite `execute`/`executemany` calls dispatch
once according to the wrapper's SQL classification. Scripts classified as
writes dispatch once; scripts classified as reads emit no post-load event.
Direct driver calls are not automatically observed.
With default `autocommit=False`, an `execute` event can precede a later rollback;
notifications are not commit or durable-audit receipts. Post-load callbacks
receive the caller's live cursor and must not consume its rows to observe it.
Callback `Exception`s are caught and logged; `BaseException` propagates after
SQL may already have executed. Callbacks are not sandboxed. Comprehensive
cross-backend observation remains unqualified. Owning controls:
`tests/scitex_db/_observers/test___init__.py` and SQLite `_QueryMixin.py`.

## CSV import preconditions

`SQLite3.load_from_csv(..., batch_size=10000, chunk_size=100000)` requires
positive integers for both sizes, including NumPy integers; booleans are refused.
Invalid sizes raise `ValueError` naming the parameter before entering the
transaction, executing SQL or reading CSV. Pending caller work remains available
for rollback, and target rows, schema and indexes are preserved on this refusal.
Native controls in `test__ImportExportMixin.py` cover replace-mode refusal,
caller rollback, ordinary/NumPy append imports, quoted values and extra-column
filtering. Transaction atomicity for failures during valid chunked imports,
concurrent imports and network storage remain unqualified.

`if_exists` accepts the case-sensitive strings `"append"`, `"replace"` or `"fail"`.
Invalid policies raise `ValueError` naming `if_exists` before reading CSV or
entering the transaction, preserving pending work, rows, schema and indexes.
Native controls in `test__ImportExportMixin_policy.py` cover invalid types/values,
missing-source precedence and all three supported policies across multiple
chunks. A valid `"fail"` policy still refuses an existing table inside the
transaction; valid-policy failures do not gain a pending-work guarantee.

CSV reader initialization precedes the import transaction. Missing files raise
`FileNotFoundError`; empty files and directory paths raise `ValueError`, before
SQL executes or pending caller work is committed. The reader closes on exit.
Native refusal controls live in
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__ImportExportMixin_sources.py`.
Later parsing/write failures can still occur after the transaction starts;
valid-import failure atomicity remains unqualified.

## CSV export batches

`SQLite3.save_to_csv(table_name, output_path, ..., batch_size=10000)` requires a
positive integer batch size, including NumPy integers; booleans, zero, negatives
and other types raise
`ValueError` before SQL executes or an output file is created or overwritten.
The error message identifies `batch_size`. Positive batches preserve CSV headers
and rows, including empty tables and quoted values. Filesystem or query errors
during a valid export can still leave partial output. Native controls live in
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__ImportExportMixin.py`; they use a
SQLite VM-step limit to bound the zero-size regression. Concurrent exports,
network storage and large-data memory/I/O performance remain unqualified.

## SQLite maintenance helpers

These standalone helpers take a database file path, not a backend connection
or a PostgreSQL URL. `inspect(path, verbose=False)` returns a list of records
with `table_name`, `columns`, `row_count`, `is_approximate` and `sample_data`.
With the default `verbose=True`, it also logs a human-readable summary.

`delete_sqlite3_duplicates(path, table_name, ...)` previews read-only by default
and returns `(total_rows, duplicate_rows)`. Writing requires explicit
`dry_run=False`; failures log and return `(None, None)`. The deprecated
`delete_duplicates` alias emits `DeprecationWarning` and forwards the same
arguments. It is not a backend-agnostic deduplication API.

This complete example creates only a disposable native SQLite fixture and
checks the default preview without applying deletions:

```python
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from scitex_db import delete_sqlite3_duplicates, inspect

with TemporaryDirectory() as directory:
    path = Path(directory) / "trials.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE trials (id INTEGER PRIMARY KEY, rt_ms REAL)")
        connection.executemany("INSERT INTO trials (rt_ms) VALUES (?)", [(342.0,), (342.0,), (410.0,)])
        connection.commit()
    before = path.read_bytes()
    records = inspect(str(path), verbose=False)
    assert records[0]["table_name"] == "trials"
    assert records[0]["row_count"] == 3
    assert delete_sqlite3_duplicates(str(path), "trials", columns=["rt_ms"]) == (3, 1)
    assert path.read_bytes() == before
```

The owning implementations are `_inspect.py::inspect` and
`_sqlite3/_delete_duplicates.py::delete_sqlite3_duplicates`. Behavioral controls
in `tests/scitex_db/test__inspect.py` check result records and counts;
`tests/scitex_db/_sqlite3/test__delete_duplicates.py` checks default preview
preservation and explicit apply. See [15_maintenance.md](15_maintenance.md)
for capped counts, BLOB samples, apply side effects and failure handling.

`check_health` and `batch_health_check` are exported, but existing-file scans
currently depend on umbrella `scitex` imports in loadability helpers. Core-only
installation does not establish completed health or repair support. Missing-file
reports can return early without a status or score; the maintenance guide
describes that separate verified scope.

## Observer registration

`register_post_save_hook(callback)` and `register_post_load_hook(callback)`
register callbacks with `(db_path, query, parameters)` and
`(db_path, query, result)` respectively. Read results are live cursors; callbacks
must not consume them. The registry is owned by `_observers/__init__.py`, with
controls in `tests/scitex_db/_observers/test___init__.py`.
