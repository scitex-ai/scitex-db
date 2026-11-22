---
description: |
  [TOPIC] Numpy Blob
  [DETAILS] See file body for details.
tags: [scitex-db-numpy-blob, scitex-db]
---


# Numpy BLOB Storage

`SQLite3.save_array` stores numeric NumPy arrays in BLOB columns through
`_ArrayMixin.save_arrays`. Compression uses zlib when requested and the
payload exceeds 1,024 bytes. Savings depend on dtype and values; measure
stored size and CPU cost on representative data instead of assuming a percentage.

## Save / load

```python
import numpy as np
from scitex_db import SQLite3

arr = np.arange(2048, dtype=np.float32).reshape(512, 4)

with SQLite3("arrays.db", compress_by_default=True) as db:
    db.create_table("m", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
    db.save_array("m", arr, additional_columns={"id": 1}, verbose=False)
    db.save_array("m", arr, additional_columns={"id": 2}, compress=False, verbose=False)
    db.save_array("m", arr + 1, ids=2, compress=False, verbose=False)

    first = db.load_array("m", "data", ids=1, verbose=False)
    updated = db.load_array("m", "data", ids=2, verbose=False)
    assert first.shape == (1, 512, 4)
    np.testing.assert_array_equal(first[0], arr)
    np.testing.assert_array_equal(updated[0], arr + 1)

    frame = db.get_rows("m", order_by="id")
    stacked = db.get_array_dict(frame)["data"]
    decoded = db.decode_array_columns(frame.copy())
    np.testing.assert_array_equal(stacked[0], arr)
    np.testing.assert_array_equal(stacked[1], arr + 1)
    np.testing.assert_array_equal(decoded["data"].iloc[0], arr)
    np.testing.assert_array_equal(decoded["data"].iloc[1], arr + 1)
```

Run the example in a new directory: it creates synthetic `arrays.db`.
Choose insertion IDs explicitly with `additional_columns`; `ids=2` updates
the existing row in this example. `load_array` requires the array column name
and returns a leading row dimension even when selecting one row. A save call
does not return an inserted row ID.

## Per-call compression override

`compress_by_default=False` is the constructor default. The example enables
it and overrides it with `compress=False` for the second row. The compression
flag and companion metadata are stored per array column and row.

## Payload format

The BLOB contains array bytes, optionally zlib-compressed. Companion columns
store dtype, shape, compression flag and hash; they are not a combined binary
header. `load_arrays` reconstructs arrays from that metadata and stacks the
selected rows. The example checks its float32 shape and values.

Shape strings are parsed as Python literals by both `load_arrays` and
`binary_to_array`; executable Python expressions are rejected. The latter
parser also serves `get_array_dict` and `decode_array_columns`. Existing
literal tuple, list and integer shape forms remain accepted by the helper.

With `columns`, `dtype` and `shape` omitted, both DataFrame helpers infer
payload columns from their dtype/shape companions, preserving DataFrame order.
Scalar fields and hashes without their own companions are excluded; real array
names ending in metadata suffixes still qualify when they have companions.
Explicit-column and nondefault dtype/shape-hint calls retain their existing
selection paths. `get_array_dict` returns stacked arrays; `decode_array_columns`
replaces cells in the supplied DataFrame, so the example passes a copy.
Both honor each row's compression flag: integer `1`, text `"1"` and `True`
mean compressed, matching the main reader. A missing flag means raw bytes.

The array reader tests below cover numeric payloads with explicit and inferred columns,
including raw/compressed rows in the same DataFrame. Wrapper-created tables
use BOOLEAN metadata; saving arrays to pre-existing native tables can add TEXT
metadata. Both formats retain the existing dtype and stacking conversions.
Malformed/null metadata, generic BLOBs, PostgreSQL and large-scale behavior
remain outside this selected coverage.

## Large arrays

BLOB reads load and decode each selected payload completely. Selecting a row
ID is not a sample-range read within a recording. Qualify the working set and
compression trade-off on the actual data; chunked/range storage remains
separate work. Keep each connection in its creating thread; see
[read-only workers](17_readonly-workers.md).

## PostgreSQL

PostgreSQL and migration need backend-specific checks. This SQLite example
does not establish compatible storage bytes or cross-backend migration.

Behavioral controls: `tests/scitex_db/_sqlite3/test__SQLite3.py` runs this
specific example in an owned directory and checks values, dtype, stacked shape
and stored compression flags. Array reader controls also live in
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__ArrayMixin.py`.
