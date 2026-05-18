---
description: |
  [TOPIC] Numpy Blob
  [DETAILS] See file body for details.
tags: [scitex-db-numpy-blob, scitex-db]
---


# Numpy BLOB Storage

The `_BaseBlobMixin` lets you stash ndarrays directly as BLOB columns
with optional compression (zlib). Typical size reduction for float64
arrays is 70–90%.

## Save / load

```python
import numpy as np
from scitex_db import SQLite3

arr = np.random.randn(2000, 2000)

with SQLite3("arrays.db", compress_by_default=True) as db:
    db.create_table("m", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
    row_id = db.save_array("m", arr, column="data")

    back = db.load_array("m", row_id=row_id, column="data")
    assert back.shape == arr.shape
```

`save_array(table, ndarray, column=…, row=None)` inserts a new row if
`row` is `None`, otherwise updates `row`.

## Per-call compression override

```python
db.save_array("m", arr, column="data", compress=False)   # force raw
```

## Payload format

Serialization: `dtype + shape + optionally-zlib-compressed .tobytes()`.
Deserialization reads the header, then reshapes/decompresses. Round-
trips exactly, including `dtype` and endianness on the same platform.

## Large arrays

For arrays >~100 MB, consider writing to disk (scitex-io) and storing
only the path. BLOB reads load the full payload into memory.

## PostgreSQL

Same API via `PostgreSQL`; backend uses `BYTEA`. Compression and header
format are backend-shared so arrays saved from one backend can be
migrated to the other at the byte level.
