---
description: |
  [TOPIC] Mixins
  [DETAILS] See file body for details.
tags: [scitex-db-mixins, scitex-db]
---


# Mixin Architecture

`SQLite3` and `PostgreSQL` are each composed from twelve mixins in the
`_BaseMixins/` namespace, overridden by backend-specific mixins in
`_SQLite3Mixins/` and `_PostgreSQLMixins/`.

## The twelve capability groups

| Mixin             | Methods (examples)                                         |
|-------------------|------------------------------------------------------------|
| `_BaseConnectionMixin` | `connect`, `close`, `__enter__`, `__exit__`, `execute` |
| `_BaseTransactionMixin` | `begin`, `commit`, `rollback`, `transaction()` cm     |
| `_BaseSchemaMixin`      | `create_table`, `drop_table`, `add_column`, `list_tables` |
| `_BaseTableMixin`       | `rename_table`, `truncate_table`, `table_exists`      |
| `_BaseRowMixin`         | `insert`, `update`, `delete`, `upsert`                |
| `_BaseQueryMixin`       | `select`, `select_one`, `count`, raw `execute`        |
| `_BaseBlobMixin`        | `save_array`, `load_array`, compression on/off        |
| `_BaseBatchMixin`       | `insert_many`, `executemany`                          |
| `_BaseIndexMixin`       | `create_index`, `drop_index`, `list_indexes`          |
| `_BaseMaintenanceMixin` | `vacuum`, `analyze`, `integrity_check`                |
| `_BaseImportExportMixin`| `to_csv`, `from_csv`, `to_df`, `from_df`              |
| `_BaseBackupMixin`      | `backup(dest)`, `restore(src)`                        |

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

Backend-specific mixins override only where the dialect differs (e.g.
`RETURNING` clause behavior, BLOB typing). The base mixins document the
canonical signature; call those names on either class.

## Why mixins

Makes it obvious which capability a method belongs to when reading
source, and avoids a 2000-line god-class. When adding a new capability,
add a new `_BaseXMixin` + backend-specific sibling rather than
extending an existing one.
