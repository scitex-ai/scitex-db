---
description: |
  [TOPIC] Maintenance
  [DETAILS] See file body for details.
tags: [scitex-db-maintenance, scitex-db]
---


# Maintenance Helpers

Standalone functions that operate on a database path (SQLite3) or
connection string (PostgreSQL). They do not require an open
`SQLite3` / `PostgreSQL` instance.

## check_health

```python
from scitex_db import check_health

report = check_health("experiments.db", verbose=True, fix_issues=False)
```

Runs `PRAGMA integrity_check`, verifies schema consistency, surfaces
corruption. Returns a dict: `{"ok": bool, "issues": [...], "fixed": [...]}`.

## batch_health_check

```python
from scitex_db import batch_health_check
batch_health_check(["a.db", "b.db", "c.db"], verbose=True, fix_issues=True)
```

Iterates and reports per-file status.

## delete_duplicates

```python
from scitex_db import delete_duplicates, delete_sqlite3_duplicates

delete_duplicates(db, table="results", columns=["name", "value"])
delete_sqlite3_duplicates("experiments.db", table="results")
```

`delete_duplicates` works on any open connection and takes the subset
of columns that define uniqueness. `delete_sqlite3_duplicates` is the
path-level SQLite3 specialization (opens the DB, acts, closes it).

## inspect

```python
from scitex_db import inspect
schema = inspect("experiments.db")
# {"tables": {"results": {"columns": [...], "indexes": [...]}}, ...}
```

Returns a structured snapshot of tables, columns (with types/PK/NULL
flags), and indexes. Handy as an audit step before migrations.

See also [10_cli-reference.md](10_cli-reference.md) for the shell
entry points wrapping these.
