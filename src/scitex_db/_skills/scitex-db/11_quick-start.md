---
description: |
  [TOPIC] Quick Start
  [DETAILS] Disposable context-managed SQLite rows, array round trip, inspection and read-only duplicate preview; backend and health limits.
tags: [scitex-db-quick-start, scitex-db]
---

# Quick Start

## A complete disposable SQLite example

This example creates and removes only its own temporary database. It checks
persisted rows, an array round trip and a read-only duplicate preview. It does
not apply deletions, run an existing-file health scan or perform repairs.

```python
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scitex_db import SQLite3, delete_sqlite3_duplicates, inspect

with TemporaryDirectory() as directory:
    path = Path(directory) / "experiments.db"
    arr = np.arange(2048, dtype=np.float32)
    with SQLite3(str(path), compress_by_default=True) as db:
        db.create_table(
            "results",
            {"id": "INTEGER PRIMARY KEY", "name": "TEXT", "value": "REAL"},
        )
        db.insert_many("results", [{"name": "run_1", "value": 3.14}] * 2)
        rows = db.get_rows("results", where="value > 3.0", order_by="id")
        assert rows["id"].tolist() == [1, 2]
        assert rows["name"].tolist() == ["run_1", "run_1"]
        db.create_table("measurements", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
        db.save_array("measurements", arr, additional_columns={"id": 1}, verbose=False)
        loaded = db.load_array("measurements", "data", verbose=False)
        assert loaded.shape == (1, 2048) and loaded.dtype == arr.dtype
        assert np.array_equal(loaded[0], arr)
    # Clean context exit commits and closes; reopen to verify persisted rows.
    with SQLite3(str(path), mode="ro") as db:
        assert db.get_rows("results", order_by="id")["id"].tolist() == [1, 2]
    before = path.read_bytes()
    tables = inspect(str(path), table_names=["results"], sample_size=1, verbose=False)
    assert tables[0]["table_name"] == "results" and tables[0]["row_count"] == 2
    preview = delete_sqlite3_duplicates(
        str(path), table_name="results", columns=["name", "value"], dry_run=True
    )
    assert preview == (2, 1) and path.read_bytes() == before
    print(json.dumps({"rows": len(rows), "array_shape": loaded.shape, "preview": preview}))
assert not path.exists()
```

Use a context manager for each `SQLite3` connection: clean exit commits,
an exception rolls back and exit closes. Keep the connection in its creating
thread; open a fresh one in each worker. See
[17_readonly-workers.md](17_readonly-workers.md).

`compress_by_default=False` is the constructor default; the example explicitly
enables it for array payloads larger than 1024 bytes. `load_array` requires the
array column name and returns a leading row dimension even for one row.
See [14_numpy-blob.md](14_numpy-blob.md) for per-call overrides and NULL/empty
array behavior. Duplicate preview uses `table_name=`, not `table=`; applying
changes requires an explicit `dry_run=False` and has further side effects.

## PostgreSQL is a separate qualification

The optional PostgreSQL backend uses constructor argument `dbname`, not
`database`. It requires its driver dependencies and a reachable configured
server. Both backends expose names such as `get_rows`; PostgreSQL additionally
exposes `select`. Matching names do not establish matching semantics. This
SQLite example does not connect to or qualify PostgreSQL. See
[13_mixins.md](13_mixins.md) and [16_sqlite-to-postgres.md](16_sqlite-to-postgres.md).

## Health and maintenance limits

Existing-file health scans currently use undeclared umbrella-provider imports;
a core-only installation does not establish completed health or repair support.
Use [15_maintenance.md](15_maintenance.md) for the separate missing-file report
and preview/apply contracts. The example above uses only inspection and default
read-only duplicate preview on its owned fixture.

## Source and behavioral evidence

Owners: `_sqlite3/_SQLite3.py` (context exit), `_SQLite3Mixins/_RowMixin.py`,
`_BatchMixin.py` and `_ArrayMixin.py`, `_inspect.py`, and
`_sqlite3/_delete_duplicates.py`. Existing controls include
`tests/scitex_db/_sqlite3/test__SQLite3.py`,
`test__SQLite3_context_commit.py`, `test__delete_duplicates_preview.py`, and
`tests/scitex_db/test__inspect.py` / `test__inspect_readonly.py`.
Executing this reviewed fixture and checking results is separate from static
validation, distribution packaging or actually served documentation.
