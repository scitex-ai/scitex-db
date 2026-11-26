---
description: |
  [TOPIC] Read-only SQLite worker processes
  [DETAILS] Open a separate SQLite3 connection inside each worker; keep connections in their creating thread.
tags: [scitex-db-readonly-workers, scitex-db]
---

# Read-only worker processes

Pass a database path to each worker and open `SQLite3(path, mode="ro")`
inside that worker. Close it with the context manager. Keep live connections
out of process arguments and shared thread state: SQLite3 connections belong
to their creating thread, and cross-thread reuse raises `sqlite3.ProgrammingError`.
The public wrapper does not expose a `check_same_thread=False` switch.

The following complete script reads a synthetic table named `signal` with
`sample INTEGER PRIMARY KEY` and `value REAL`, containing samples 0 through 63.
Save it as `readonly_workers.py` and run `python readonly_workers.py signal.db`.
It reads existing storage through read-only connections. In WAL mode, SQLite
can still create `-wal` and `-shm` sidecars in a writable directory: read-only
database content does not mean zero filesystem writes. The main guard and
explicit spawn context keep process startup portable. Each task creates its own
connection; a worker may execute multiple tasks.
The example sets native math-library thread counts to one before importing
SQLite3, which imports NumPy. This keeps the process pool from multiplying
BLAS threads; it does not change SQLite connection thread ownership.

```python
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import os
import sys

for name in (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[name] = "1"

from scitex_db import SQLite3


def read_partition(task):
    path, start, stop = task
    with SQLite3(path, mode="ro") as db:
        rows = db.execute(
            "SELECT sample, value FROM signal "
            "WHERE sample >= ? AND sample < ? ORDER BY sample",
            (start, stop),
        ).fetchall()
    return {"rows": rows, "pid": os.getpid()}


def main(path):
    tasks = [(path, start, start + 8) for start in range(0, 64, 8)]
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        parts = list(pool.map(read_partition, tasks))
    print(json.dumps({
        "rows": [row for part in parts for row in part["rows"]],
        "worker_pids": sorted({part["pid"] for part in parts}),
        "parent_pid": os.getpid(),
    }))


if __name__ == "__main__":
    main(sys.argv[1])
```

Create or migrate tables before starting readers. Writable SQLite3 connections
configure WAL on supported storage; read-only opens leave the journal mode alone.
Select storage whose SQLite locking semantics are supported. Do not infer safe
multi-host/NFS access from a local worker test. Read-only-directory and immutable
URI operation are not qualified by this guide.

The SQL above selects indexed sample rows. `load_array`/`load_arrays` still load
and decode each selected array BLOB completely; choose row/chunk boundaries to
match your access pattern. This guide is not a PyTorch Dataset adapter or a
throughput/RAM benchmark.

Behavioral controls: `tests/scitex_db/_sqlite3/test__SQLite3.py` executes this
specific script on an owned fixture, checks row values and child-process use,
and verifies native cross-thread refusal. Other guides and arbitrary code
fences are not executed by those controls.

## Optional temporary copies

`SQLite3(path, use_temp=True, mode=...)` copies the source to an exclusively
allocated temporary filename. Copies from different directories with the same
basename have separate paths and contents; closing one owner removes only its
copy. Copy-source failures remove the newly allocated file before propagating
the error. The original source path and the selected mode/timeout are retained
by the connection wrapper. A legacy `temp_<basename>` file is not reused.

This is a filesystem `shutil.copy2`, not SQLite's backup API or a consistent
snapshot of a live database. Live writers, WAL/SHM copying, multi-process copy
coordination, network storage and snapshot consistency remain unqualified.
The default `use_temp=False` worker example above is unchanged. Source owner:
`_SQLite3Mixins/_ConnectionMixin.py::_create_temp_copy`; native identity,
source-failure, original-file preservation and close controls:
`tests/scitex_db/_sqlite3/_SQLite3Mixins/test__ConnectionMixin_temp.py`.
