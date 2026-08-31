---
description: |
  [TOPIC] Numpy BYTEA storage
  [DETAILS] Storing ndarrays in BYTEA columns via the blob mixin — save_array / load_array, the dtype+shape sidecar columns, and when to store a path instead.
tags: [scitex-db-numpy-blob, scitex-db]
---


# Numpy Array Storage

`_BlobMixin` stores ndarrays directly in `BYTEA` columns. The array's
`dtype` and `shape` are written to sidecar columns (`<column>_dtype`,
`<column>_shape`) so a read can reconstruct the array without the caller
remembering either.

## Save / load

```python
import os
import numpy as np
import scitex_db

arr = np.random.randn(2000, 2000)

db = scitex_db.PostgreSQL(
    dbname="lab", user="me", password=os.environ["PGPASSWORD"],
    host="localhost", port=55432,
)
db.create_table("m", {"id": "SERIAL PRIMARY KEY", "data": "BYTEA"})
db.save_array("m", arr, column="data")

back = db.load_array("m", column="data", ids="all")
```

`save_array(table_name, data, column="data", ids=None, where=None,
additional_columns=None, batch_size=1000)` runs inside a transaction and
accepts either a single ndarray or a list of them.

`load_array(table_name, column, ids="all", where=None, order_by=None,
batch_size=128, dtype=None, shape=None)` returns the reconstructed
array. Pass `dtype` / `shape` explicitly only when the sidecar columns
are absent.

## Reading arrays back out of a DataFrame

When rows arrive as a DataFrame, decode the binary columns in bulk:

```python
df = db.get_rows("m")
arrays = db.get_array_dict(df, columns=["data"])
decoded = db.decode_array_columns(df, columns=["data"])
single = db.binary_to_array(df["data"][0], dtype_str="float64", shape_str="(2000, 2000)")
```

## Large arrays

For arrays beyond roughly 100 MB, write the array to disk (scitex-io)
and store only the path. A `BYTEA` read loads the full payload into
memory, and PostgreSQL's own field ceiling is 1 GB.

## See also

- [03_python-api.md](03_python-api.md) — the public surface
- [13_mixins.md](13_mixins.md) — where `_BlobMixin` sits
