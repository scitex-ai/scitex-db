---
description: |
  [TOPIC] Quick Start
  [DETAILS] See file body for details.
tags: [scitex-db-quick-start, scitex-db]
---


# Quick Start

## SQLite3 — context-managed

```python
from scitex_db import SQLite3

with SQLite3("experiments.db", compress_by_default=True) as db:
    db.create_table(
        "results",
        {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
    )
    db.insert_many("results", [{"name": "run_1", "value": 3.14}])
    rows = db.get_rows("results", where="value > 3.0")
```

Writes are thread-safe; the context manager commits + closes cleanly.

## PostgreSQL

```python
from scitex_db import PostgreSQL

with PostgreSQL(host="localhost", dbname="mydb", user="me") as db:
    db.execute("SELECT COUNT(*) FROM experiments")
    rows = db.select("experiments", where="status = 'done'")
```

Note the different spellings: `select` here, `get_rows` on SQLite3. The
two classes are not interchangeable — see
[16_sqlite-to-postgres.md](16_sqlite-to-postgres.md).

## Numpy arrays

```python
import numpy as np
arr = np.random.randn(1000, 1000)
with SQLite3("arrays.db") as db:
    db.create_table("measurements", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
    db.save_array("measurements", arr, column="data")
```

See [14_numpy-blob.md](14_numpy-blob.md).

## Maintenance

```python
from scitex_db import check_health, delete_sqlite3_duplicates, inspect

health = check_health("experiments.db")
delete_sqlite3_duplicates("experiments.db", table="results")
schema = inspect("experiments.db")
```
