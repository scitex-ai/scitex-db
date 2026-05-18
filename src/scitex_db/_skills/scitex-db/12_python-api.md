---
description: |
  [TOPIC] Python Api
  [DETAILS] See file body for details.
tags: [scitex-db-python-api, scitex-db]
---


# Python API

Everything re-exported from top-level `scitex_db` / `scitex.db`.

## Classes

| Name        | Purpose                                                    |
|-------------|------------------------------------------------------------|
| `SQLite3`   | SQLite3 wrapper with numpy BLOB + compression + mixins     |
| `PostgreSQL`| PostgreSQL wrapper with the same mixin-derived API surface |

Both implement context-manager (`__enter__`/`__exit__`) and share the
method set documented in [03_mixins.md](03_mixins.md).

## Functions

| Name                        | Purpose                                            |
|-----------------------------|----------------------------------------------------|
| `check_health(path_or_url)` | Validate one database (integrity + schema smoke)   |
| `batch_health_check(paths)` | Validate many databases in one call                |
| `delete_duplicates(db, …)`  | Backend-agnostic duplicate removal                 |
| `delete_sqlite3_duplicates` | SQLite3-specific, uses ROWID tricks                |
| `inspect(path_or_conn)`     | Return schema as a structured dict                 |

Note: `check_health` and `batch_health_check` are re-exported; only
`check_health` appears in `__all__`, but both are importable.

## Sub-packages (advanced)

* `scitex_db._BaseMixins` — abstract mixin protocols
* `scitex_db._SQLite3Mixins`, `scitex_db._postgresql._PostgreSQLMixins` — concrete implementations

Prefer the public classes; mixin modules are private.
