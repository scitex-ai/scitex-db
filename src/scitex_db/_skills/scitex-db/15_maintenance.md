---
description: |
  [TOPIC] Maintenance
  [DETAILS] Methods on an open PostgreSQL instance — vacuum / analyze / reindex / optimize, size reporting, summaries, and pg_dump-backed backup + restore.
tags: [scitex-db-maintenance, scitex-db]
---


# Maintenance

These are **methods on an open connection**, not standalone functions.
Open a `PostgreSQL` instance first.

```python
import os
import scitex_db

db = scitex_db.PostgreSQL(
    dbname="lab", user="me", password=os.environ["PGPASSWORD"],
    host="localhost", port=55432,
)
```

## Reclaim and re-plan

```python
db.vacuum()                    # whole database
db.vacuum("results", full=True)
db.analyze("results")          # refresh planner statistics
db.reindex("results")          # rebuild indexes
db.optimize("results")         # VACUUM FULL + ANALYZE + REINDEX
```

Every one of these takes an in-process `maintenance_lock` (300 s
timeout) so two of them cannot run against the same instance at once,
and every one calls `_check_writable` first — they raise rather than
silently no-op on a read-only connection.

`VACUUM FULL` takes an ACCESS EXCLUSIVE lock and rewrites the table.
Readers block for its whole duration; do not reach for `optimize` on a
live store during working hours.

## Size and shape

```python
db.get_database_size()      # e.g. '412 MB'
db.get_table_size("results")
db.get_table_info()         # per-table name + size + row estimate
db.get_summaries(table_names=["results"], limit=5)
```

`get_summaries` returns a `{table: DataFrame}` mapping. Calling the
instance itself (`db()`), or reading `db.summary`, prints the same
thing.

## Backup and restore

These shell out to the PostgreSQL client tools, so `pg_dump`, `psql`
and `pg_restore` must be on `PATH`.

```python
db.backup_table("results", "/backups/results.sql")
db.restore_table("results", "/backups/results.sql")

db.backup_database("/backups/lab.dump")
db.restore_database("/backups/lab.dump")

db.copy_table("results", "results_2026", where="run_id > 100")
```

`restore_*` and `copy_table` check writability first.

## See also

- [03_python-api.md](03_python-api.md) — the public surface
- [13_mixins.md](13_mixins.md) — where these methods live
