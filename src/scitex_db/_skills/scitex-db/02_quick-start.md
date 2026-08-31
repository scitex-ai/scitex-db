---
description: |
  [TOPIC] Quick start
  [DETAILS] Smallest example — connect to PostgreSQL, create a table, insert rows, store an ndarray as a compressed blob.
tags: [scitex-db-quick-start]
---

# Quick Start

## Minimum viable use

```python
import os
import numpy as np
import scitex_db

db = scitex_db.PostgreSQL(
    dbname="lab",
    user="me",
    password=os.environ["PGPASSWORD"],
    host="localhost",
    port=55432,
)

# Schema is a {column: SQL type} mapping, not a DataFrame.
db.create_table(
    "trials",
    {"id": "SERIAL PRIMARY KEY", "trial": "INTEGER", "rt_ms": "REAL"},
)

db.insert("trials", {"trial": 1, "rt_ms": 342.0})
db.insert_many("trials", [{"trial": 2, "rt_ms": 410.0}])

rows = db.select("trials", where="rt_ms > 300")
n = db.count("trials", where="rt_ms > 300")
```

## numpy ndarrays

The first argument is the TABLE, not a key — the array lives in a
`BYTEA` column of that table.

```python
db.create_table("eeg", {"id": "SERIAL PRIMARY KEY", "data": "BYTEA"})
arr = np.random.randn(1000, 64).astype("float32")
db.save_array("eeg", arr, column="data")
back = db.load_array("eeg", column="data")
```

## Transactions

```python
with db.transaction():
    db.insert("trials", {"trial": 3, "rt_ms": 388.0})
```

## Observers

Register a hook to see every write and read the wrapper performs:

```python
import scitex_db

scitex_db.register_post_save_hook(
    lambda db_path, query, parameters: print("wrote", query)
)
```

## Next

- [03_python-api.md](03_python-api.md) — full public surface
- [04_cli-reference.md](04_cli-reference.md) — `scitex-db` CLI
- [13_mixins.md](13_mixins.md) — mixin architecture
- [14_numpy-blob.md](14_numpy-blob.md) — ndarray storage details
- [15_maintenance.md](15_maintenance.md) — vacuum / analyze / sizes
