---
description: |
  [TOPIC] Mixins
  [DETAILS] How SQLite3 and PostgreSQL are composed — and where the two surfaces diverge.
tags: [scitex-db-mixins, scitex-db]
---


# Mixin Architecture

`SQLite3` and `PostgreSQL` are each composed from mixins in the
`_BaseMixins/` namespace, overridden by backend-specific mixins in
`_SQLite3Mixins/` and `_PostgreSQLMixins/`.

## The base declares; the backends implement a subset

`_BaseMixins` declares 59 methods, almost all as a bare
`raise NotImplementedError`. That is a declaration, not a promise — and
the two backends have honoured it unevenly. Measured 2026-08-02 by
walking the source:

| | declared in base | not implemented by this backend |
|---|---|---|
| `SQLite3` | 59 | **23** — `select`, `insert`, `update`, `delete`, `count`, `table_exists`, `get_tables`, `get_table_info`, `analyze`, `backup_database`, … |
| `PostgreSQL` | 59 | 1 — `transaction` |

Calling one of those 23 on a `SQLite3` instance reaches the base method
and raises `NotImplementedError` at runtime.

## The same operation has two names

Where both backends do implement an operation, they often spell it
differently. This is the part that makes "swap the backend" a rewrite
rather than a config change:

| operation | `SQLite3` | `PostgreSQL` |
|---|---|---|
| list tables | `get_table_names` | `get_tables` |
| describe a table | `get_table_schema` | `get_table_info` |
| primary key | `get_primary_key` | `get_primary_keys` |
| run SQL | `execute` | `execute_query` |
| read rows | `get_rows` | `select` |
| row count | `get_row_count` | `count` |
| insert rows | `insert_many` | `insert` |

32 method names exist only on `SQLite3` (the `_ArrayMixin`, `_ColumnMixin`
and `_GitMixin` groups have no PostgreSQL counterpart at all); 23 exist
only on `PostgreSQL`.

## Test coverage is asymmetric too

`SQLite3`: 98 test functions across 3 files. `PostgreSQL`: 12 test
functions in 1 file (`_BatchMixin`). Treat the PostgreSQL class as
lightly exercised and verify behaviour against your own data before
relying on it.

## Method resolution

```
class SQLite3(_SQLite3ConnectionMixin,
              _SQLite3QueryMixin,
              ...
              _BaseConnectionMixin,
              _BaseQueryMixin,
              ...):
    ...
```

Backend-specific mixins come first in the MRO, so they win wherever they
define a name. Where they do not define it, the base's
`NotImplementedError` is what you get.

## Why mixins

Makes it obvious which capability a method belongs to when reading
source, and avoids a 2000-line god-class. When adding a new capability,
add a new `_BaseXMixin` + backend-specific sibling rather than
extending an existing one — and implement it on **both** backends, or
say plainly in this file that you did not.

## See also

- [16_sqlite-to-postgres.md](16_sqlite-to-postgres.md) — what a real port
  costs, and the five silent failures to guard against.
