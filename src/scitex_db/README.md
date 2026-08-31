# scitex_db — PostgreSQL with NumPy-aware storage

Part of [**SciTeX**](https://scitex.ai). Ships one backend class
composed from a dozen shared mixins, plus a `schema_change` package for
pre-flighting an in-place schema change against a live store.

```python
import os
from scitex_db import PostgreSQL
```

## PostgreSQL

```python
db = PostgreSQL(
    dbname="lab", user="me", password=os.environ["PGPASSWORD"],
    host="localhost", port=55432,
)

with db.transaction():
    db.insert("results", {"experiment": "exp1", "accuracy": 0.95})

rows = db.select("results", where="accuracy > 0.9")
print(db.summary)
```

## NumPy arrays

```python
import numpy as np

arr = np.random.randn(1000, 64).astype("float32")
db.save_array("features", arr, column="data")
back = db.load_array("features", column="data")
# back.shape == (1000, 64)
```

## Maintenance

```python
db.vacuum("results")
db.analyze("results")
db.get_database_size()
db.get_table_info()
```

## CLI

```bash
scitex-db list-python-apis
scitex-db mcp list-tools
scitex-db skills list
```

## Dependencies

- Python >= 3.10
- numpy, pandas, click, scitex-core
- Optional: psycopg2 + sqlalchemy, via the `postgresql` extra
