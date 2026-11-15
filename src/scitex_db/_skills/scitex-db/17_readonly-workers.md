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
It opens existing storage read-only and performs no writes. The main guard and
explicit spawn context keep process startup portable. Each task creates its own
connection; a worker may execute multiple tasks.

```python
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import json
import os
import sys

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
multi-host/NFS access from a local worker test.

The SQL above selects indexed sample rows. `load_array`/`load_arrays` still load
and decode each selected array BLOB completely; choose row/chunk boundaries to
match your access pattern. This guide is not a PyTorch Dataset adapter or a
throughput/RAM benchmark.

Behavioral controls: `tests/scitex_db/_sqlite3/test__SQLite3.py` executes this
specific script on an owned fixture, checks row values and child-process use,
and verifies native cross-thread refusal. Other guides and arbitrary code
fences are not executed by those controls.
