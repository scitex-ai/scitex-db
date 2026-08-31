---
description: |
  [TOPIC] Python API
  [DETAILS] Public callables — the PostgreSQL backend class and the post-save / post-load observer hooks.
tags: [scitex-db-python-api]
---

# Python API

```python
import scitex_db
```

## Top-level exports (`__all__`)

| Symbol | Purpose |
|---|---|
| `PostgreSQL` | Backend class (composed from mixins) |
| `register_post_save_hook` | Run a callable after every successful write |
| `register_post_load_hook` | Run a callable after every successful read |
| `__version__` | Package version string |

Every symbol is imported lazily (PEP 562 `__getattr__`), so `import
scitex_db` stays cheap. `PostgreSQL` resolves to `None` when `psycopg2`
is not installed — see [01_installation.md](01_installation.md).

## Backend class

```python
import os

db = scitex_db.PostgreSQL(
    dbname="lab", user="me", password=os.environ["PGPASSWORD"],
    host="localhost", port=55432,
)

# Schema
db.create_table("trials", {"id": "SERIAL PRIMARY KEY", "rt_ms": "REAL"})
db.get_table_names()
db.table_exists("trials")
db.get_table_schema("trials")
db.drop_table("trials")

# Rows
db.insert("trials", {"rt_ms": 342.0})
db.insert_many("trials", [{"rt_ms": 410.0}])
db.select("trials", where="rt_ms > 300")
db.count("trials")
db.update("trials", {"rt_ms": 300.0}, where="id = 1")
db.delete("trials", where="id = 1")
db.execute_query("SELECT 1")

# numpy blobs -- addressed by (table, column), not by key
db.save_array("eeg", arr, column="data")
db.load_array("eeg", column="data")

# Transactions
with db.transaction():
    db.insert("trials", {"rt_ms": 410.0})
```

See [13_mixins.md](13_mixins.md) for the full per-mixin breakdown.

## Observer hooks

The hooks are a registry: `register_post_save_hook` and
`register_post_load_hook` append to a process-wide list, and a hook that
raises is swallowed rather than allowed to break the host's database
access.

```python
import scitex_db

scitex_db.register_post_save_hook(
    lambda db_path, query, parameters: print("wrote", query)
)
scitex_db.register_post_load_hook(
    lambda db_path, query, result: print("read", query)
)
```

## See also

- [13_mixins.md](13_mixins.md) — capability groups
- [14_numpy-blob.md](14_numpy-blob.md) — ndarray storage format
- [15_maintenance.md](15_maintenance.md) — vacuum / analyze / sizes
