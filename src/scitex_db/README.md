# scitex_db — SQLite3 & PostgreSQL with NumPy-aware storage

Part of [**SciTeX**](https://scitex.ai). Ships two backend classes
composed from a dozen shared mixins, plus standalone maintenance helpers.

```python
from scitex_db import SQLite3, PostgreSQL, check_health, inspect
```

## SQLite3

```python
db = SQLite3("experiments.db")

with db.transaction():
    db.insert("results", {"experiment": "exp1", "accuracy": 0.95})

rows = db.select("results", where="accuracy > 0.9")
print(db.summary)
```

## PostgreSQL

```python
db = PostgreSQL(host="localhost", dbname="lab", user="me")

db.execute("SELECT COUNT(*) FROM experiments")
rows = db.select("experiments", where="status = 'done'")
```

## NumPy arrays

```python
import numpy as np

arr = np.random.randn(1000, 64).astype("float32")
db.save_array("features", arr, column="data")
back = db.load_array("features", "data")
# back.shape == (1000, 64)
```

## Maintenance

```python
check_health("experiments.db", fix_issues=True)
inspect("experiments.db")                     # schema + row counts
delete_sqlite3_duplicates("experiments.db", table="results")
```

## CLI

```bash
scitex-db inspect-db experiments.db
scitex-db check-health experiments.db --fix --yes
scitex-db list-python-apis
```

## Dependencies

- Python >= 3.10
- numpy, pandas, click, scitex-core
- Optional: psycopg2 (PostgreSQL), GitPython (git helpers)