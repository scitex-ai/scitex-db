---
description: |
  [TOPIC] Quick start
  [DETAILS] Smallest example — open a SQLite DB, write a DataFrame, store an ndarray as a numpy blob, run a health check.
tags: [scitex-db-quick-start]
---

# Quick Start

## SQLite — minimum viable use

```python
import scitex_db
import pandas as pd
import numpy as np

db = scitex_db.SQLite3("experiment.db")

# DataFrame round-trip
df = pd.DataFrame({"trial": [1, 2, 3], "rt_ms": [342, 410, 287]})
db.create_table("trials", df)
db.insert(df, "trials")
out = db.read_table("trials")

# numpy ndarray as a compressed blob
arr = np.random.randn(1000, 64).astype("float32")
db.save_array("eeg_epoch_001", arr)
back = db.load_array("eeg_epoch_001")
```

## PostgreSQL

```python
db = scitex_db.PostgreSQL(
    host="localhost", database="lab", user="me", password=os.environ["PGPASS"],
)
```

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
