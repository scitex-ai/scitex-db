---
description: |
  [TOPIC] Mixins
  [DETAILS] How PostgreSQL is composed — the base declaration namespace, the concrete mixins, and the MRO.
tags: [scitex-db-mixins, scitex-db]
---


# Mixin Architecture

`PostgreSQL` is composed from twelve concrete mixins in
`_postgresql/_PostgreSQLMixins/`, layered over the declaration namespace
in `_BaseMixins/`.

## The base declares; the backend implements

`_BaseMixins` declares **61** methods. **55** of them are a bare
`raise NotImplementedError` — a declaration, not a promise — and **6**
carry a real body that the backend inherits (notably `transaction`, in
`_BaseTransactionMixin`).

Measured by walking the source with `ast`:

| | value |
|---|---|
| declared in `_BaseMixins` | 61 |
| of those, abstract | 55 |
| abstract names `PostgreSQL` leaves unimplemented | **0** |
| names `PostgreSQL` adds beyond the base | 7 |

So every declared name resolves to a real body. The seven additions are
`get_summaries`, `maintenance_lock`, `optimize`, `summary`, plus the
internal `_check_writable`, `_get_connection_params` and
`_map_dtype_to_postgres`.

## Capability groups

Each base mixin has exactly one concrete sibling:

| capability | base | concrete |
|---|---|---|
| connection | `_BaseConnectionMixin` | `_ConnectionMixin` |
| query | `_BaseQueryMixin` | `_QueryMixin` |
| transaction | `_BaseTransactionMixin` | `_TransactionMixin` |
| table | `_BaseTableMixin` | `_TableMixin` |
| schema | `_BaseSchemaMixin` | `_SchemaMixin` |
| index | `_BaseIndexMixin` | `_IndexMixin` |
| row | `_BaseRowMixin` | `_RowMixin` |
| batch | `_BaseBatchMixin` | `_BatchMixin` |
| blob | `_BaseBlobMixin` | `_BlobMixin` |
| import/export | `_BaseImportExportMixin` | `_ImportExportMixin` |
| maintenance | `_BaseMaintenanceMixin` | `_MaintenanceMixin` |
| backup | `_BaseBackupMixin` | `_BackupMixin` |

## Method resolution

```
class PostgreSQL(_BackupMixin,
                 _BatchMixin,
                 _ConnectionMixin,
                 ...
                 _BlobMixin):
    ...
```

The concrete mixins come first in the MRO, so they win wherever they
define a name; where they do not, the base body (or its
`NotImplementedError`) is what you get.

## Test coverage is thin

`PostgreSQL` has 12 test functions in one file (`_BatchMixin`). The
class is lightly exercised — verify behaviour against your own data
before relying on it, and add tests alongside any change.

## Why mixins

Makes it obvious which capability a method belongs to when reading
source, and avoids a 2000-line god-class. When adding a capability, add
a new `_BaseXMixin` plus its concrete sibling rather than extending an
existing one.

## See also

- [03_python-api.md](03_python-api.md) — the public surface
- [15_maintenance.md](15_maintenance.md) — the maintenance mixin in detail
