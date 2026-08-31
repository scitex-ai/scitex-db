---
description: |
  [TOPIC] Python API
  [DETAILS] Public callables — SQLite3, PostgreSQL backends, delete_duplicates, inspect.
tags: [scitex-db-python-api]
---

# Python API

```python
import scitex_db
```

## Top-level exports (`__all__`)

| Symbol | Purpose |
|---|---|
| `SQLite3` | SQLite backend class (composed from mixins) |
| `PostgreSQL` | PostgreSQL backend class (composed from mixins) |
| `delete_duplicates` | Generic deduplication helper |
| `delete_sqlite3_duplicates` | SQLite-specific dedup |
| `inspect` | Schema/row-count introspection function |
| `__version__` | Package version string |

## Backend classes

`SQLite3` and `PostgreSQL` draw on the same mixin *namespace*, but their
surfaces are **not** interchangeable: they spell the same operations
differently, and each leaves part of the base surface unimplemented.
Write against one of them, not against "the API".

```python
db = scitex_db.SQLite3("trials.db")

# Schema
db.create_table("trials", {"id": "INTEGER PRIMARY KEY", "rt_ms": "REAL"})
db.drop_table("trials")
db.get_table_names()

# Rows
db.insert_many("trials", [{"rt_ms": 342.0}])
db.get_rows("trials", where="rt_ms > 300")     # DataFrame by default
db.get_row_count("trials")
db.execute("SELECT ...", parameters=())

# numpy blobs -- addressed by (table, column), not by key
db.save_array("eeg", arr, column="data")
db.load_array("eeg", column="data")

# Transactions
with db.transaction():
    db.insert_many("trials", [{"rt_ms": 410.0}])
```

The PostgreSQL spellings differ: `get_tables`, `insert`, `select`,
`count`, `execute_query`. See
[16_sqlite-to-postgres.md](16_sqlite-to-postgres.md) for the mapping and
for what a port actually costs.

See [13_mixins.md](13_mixins.md) for the full per-mixin breakdown.

## Maintenance helpers

```python
from scitex_db import delete_duplicates, delete_sqlite3_duplicates, inspect

inspect("experiment.db")                                # print schema
delete_sqlite3_duplicates("experiment.db", "trials")    # in-place
```

## See also

- [13_mixins.md](13_mixins.md) — capability groups
- [14_numpy-blob.md](14_numpy-blob.md) — ndarray storage format
- [15_maintenance.md](15_maintenance.md) — health/dedupe/inspect deep-dive
