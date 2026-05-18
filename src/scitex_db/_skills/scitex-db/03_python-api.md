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

Both `SQLite3` and `PostgreSQL` are composed from the same set of
capability mixins, so the surface is largely identical:

```python
db = scitex_db.SQLite3("trials.db")

# Schema
db.create_table(name, schema_or_df)
db.drop_table(name)
db.list_tables()

# Rows
db.insert(df_or_rows, table)
db.read_table(table) -> pd.DataFrame
db.execute(sql, params=...)

# numpy blobs
db.save_array(key, arr)
db.load_array(key) -> ndarray

# Maintenance
db.health_check()
db.vacuum()
```

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
