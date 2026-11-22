---
description: |
  [TOPIC] Mixins
  [DETAILS] How SQLite3 and PostgreSQL are composed — and where the two surfaces diverge.
tags: [scitex-db-mixins, scitex-db]
---


# Mixin Architecture

The public classes are composed in `_sqlite3/_SQLite3.py::SQLite3` and
`_postgresql/_PostgreSQL.py::PostgreSQL`. Inspect each class's `__mro__`
and the defining class of a method when tracing a capability. A matching
method name does not establish matching arguments, results or transaction
semantics across backends.

## Base mixins are not a universal fallback

`SQLite3` directly lists its SQLite-specific mixins. Those classes do not
inherit the `_BaseMixins` classes; some modules import a base class without
using it as a parent. For example, `_SQLite3Mixins/_TableMixin.py` imports
`_BaseTableMixin`, but declares `class _TableMixin:`.

Consequently, absent names such as `SQLite3.select`, `insert`, `update`,
`delete`, `count` and `get_tables` are missing attributes. They do not
resolve to base stubs that raise `NotImplementedError`. Use the SQLite
methods below or explicit SQL through `execute`.

Some PostgreSQL mixins do inherit base classes. For example,
`_PostgreSQLMixins/_TransactionMixin.py::_TransactionMixin` inherits
`_BaseTransactionMixin`, whose `transaction` context manager calls
`begin`, `commit` and `rollback`; the PostgreSQL mixin defines those
operations. The inherited context manager is an implementation, not a
bare `NotImplementedError` stub. This source relationship alone does not
qualify PostgreSQL transaction behavior against a live server.

## Shared names and additional PostgreSQL operations

These methods are defined on both backend surfaces. This table records
names and source owners, not interchangeable behavior:

| Operation | Shared name | Backend-specific source |
|---|---|---|
| List tables | `get_table_names` | `_TableMixin.py` |
| Describe a table | `get_table_schema` | `_TableMixin.py` |
| Primary key | `get_primary_key` | `_TableMixin.py` |
| Run SQL | `execute` | SQLite `_QueryMixin.py`; PostgreSQL `_ConnectionMixin.py` |
| Read rows | `get_rows` | `_RowMixin.py` |
| Row count | `get_row_count` | `_RowMixin.py` |
| Insert records in batches | `insert_many` | `_BatchMixin.py` |

PostgreSQL additionally defines `get_tables` and `get_primary_keys` in
`_SchemaMixin.py`, and `select`, `insert`, `update`, `delete`, `count`
and `execute_query` in `_QueryMixin.py`. These are additional operations;
the shared table/row/SQL names above are not exclusive to SQLite.
PostgreSQL `get_table_info()` is defined in `_MaintenanceMixin.py` and
takes no table argument; it is not a drop-in spelling for SQLite
`get_table_schema(table_name)`.

SQLite's `_ArrayMixin`, `_ColumnMixin` and `_GitMixin` are listed in its
composition; the PostgreSQL class does not list counterparts. Port callers
by checking actual signatures, SQL parameter styles, result formats and
storage behavior rather than replacing only the class name. PostgreSQL
support also requires its optional driver; the lazy public export can be
`None` when an `ImportError` prevents loading it (`scitex_db.__getattr__`).

## SQLite query classification limits

`_SQLite3Mixins/_QueryMixin.py::_is_write_query` routes the wrapper's
writable check and observer dispatch using keywords. It is not a complete
SQLite parser or a guarantee that a read-classified query has no side effects.
In particular, all `PRAGMA` queries are read-classified: a writable connection
can execute `PRAGMA user_version = 7`, change that value and emit a post-load
notification. Native read-only connections and `query_only` remain separate
SQLite controls; the classifier alone is not an authorization boundary.

`_split_statements` ignores semicolons inside recognized quotes/comments and
parentheses, but does not track trigger `BEGIN ... END` blocks. It can return
trigger fragments. The existing
`test_a_semicolon_inside_a_trigger_body_does_not_split_the_statement` checks
only that `_script_is_write` returns `True`, not that splitting is absent.
The complete script is still passed to SQLite for execution. Comprehensive
SQL classification and trigger-aware parsing remain unresolved gaps.

## Evidence and coverage limits

The SQLite tests in `tests/scitex_db/_sqlite3/test__SQLite3.py` exercise
real temporary database files. For example,
`test_create_table_basic_lists_new_table`,
`test_get_table_schema_identifies_primary_key_row`,
`test_insert_then_get_rows_returns_inserted_row`,
`test_insert_many_writes_all_rows_with_batching` and the transaction
commit/rollback tests check results rather than method presence alone.
`test_sqlite3_exposes_mixin_method` separately checks method availability.
The context-exit persistence controls live in
`tests/scitex_db/_sqlite3/test__SQLite3_context_commit.py`.

The PostgreSQL `_BatchMixin` tests in
`tests/scitex_db/_postgresql/_PostgreSQLMixins/test__BatchMixin.py` check
SQL construction, parameter flattening, dtype mapping and option
validation using real Python data. They do not connect to a server and
skip at module level when `psycopg2` is unavailable. Passing these helpers
or inspecting the installed class MRO does not verify PostgreSQL schema,
query, transaction, array or migration behavior on a live database.

When adding a capability, choose its owning backend mixin and check whether
it belongs in a shared base contract. Verify inheritance explicitly;
adding a base declaration does not expose it on SQLite. Implement and test
each supported backend, and document any remaining backend limitation.

## See also

- [03_python-api.md](03_python-api.md) — current SQLite-first public API and
  verified examples.
- [16_sqlite-to-postgres.md](16_sqlite-to-postgres.md) — migration concerns;
  this architecture review does not qualify a live port.
