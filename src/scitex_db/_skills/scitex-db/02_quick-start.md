---
description: |
  [TOPIC] Quick start
  [DETAILS] Smallest example — open a SQLite DB, create a table, insert rows, store an ndarray as a numpy blob, run a health check.
tags: [scitex-db-quick-start]
---

# Quick Start

## SQLite — minimum viable use

```python
import numpy as np
import scitex_db

db = scitex_db.SQLite3("experiment.db")

# Schema is a {column: SQL type} mapping, not a DataFrame.
db.create_table(
    "trials",
    {"id": "INTEGER PRIMARY KEY", "trial": "INTEGER", "rt_ms": "REAL"},
)

db.insert_many(
    "trials",
    [{"trial": 1, "rt_ms": 342}, {"trial": 2, "rt_ms": 410}],
)

out = db.get_rows("trials", where="rt_ms > 300")   # DataFrame by default

# numpy ndarray as a compressed blob -- the first argument is the TABLE,
# not a key. The array lives in a BLOB column of that table.
db.create_table("eeg", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
arr = np.random.randn(1000, 64).astype("float32")
db.save_array("eeg", arr, column="data")
back = db.load_array("eeg", column="data")
```

## PostgreSQL

```python
import os

db = scitex_db.PostgreSQL(
    host="localhost", database="lab", user="me", password=os.environ["PGPASS"],
)
```

`PostgreSQL` is **not** a drop-in replacement for `SQLite3` — the two
classes name the same operations differently and neither implements the
full base surface. See [16_sqlite-to-postgres.md](16_sqlite-to-postgres.md)
before planning a move.

## Health check

```python
from scitex_db import check_health
check_health("experiment.db", fix_issues=False)
```

## Next

- [03_python-api.md](03_python-api.md) — full public surface
- [04_cli-reference.md](04_cli-reference.md) — `scitex-db` CLI
- [13_mixins.md](13_mixins.md) — mixin architecture
- [14_numpy-blob.md](14_numpy-blob.md) — ndarray storage details
- [16_sqlite-to-postgres.md](16_sqlite-to-postgres.md) — porting to PostgreSQL
