---
name: scitex-db
description: |
  [WHAT] Relational-DB wrapper for scientific Python.
  [WHEN] Use when the user asks to "store numpy arrays in SQLite", "persist experiment results to Postgres", "dedupe rows in a table", "check this SQLite DB is healthy / not corrupt", "inspect the schema of a DB", "save/load compressed ndarrays a....
  [HOW] `import scitex_db`; use `SQLite3` with a context manager (see quick start).
tags: [scitex-db]
primary_interface: python
interfaces:
  python: 3
  cli: 1
  mcp: 0
  skills: 2
  hook: 0
  http: 0
---


# scitex-db

> **Interfaces:** Python ⭐⭐⭐ (primary) · CLI ⭐ · MCP — · Skills ⭐⭐ · Hook — · HTTP —

SQLite and optional PostgreSQL classes compose backend-specific mixins, plus
standalone SQLite maintenance helpers. Both classes expose names such as
`get_rows`, but matching names do not establish backend parity. SQLite does not
inherit the base stubs; see [13_mixins](13_mixins.md) and
[16_sqlite-to-postgres](16_sqlite-to-postgres.md) before a backend move.

## Standalone installation and import

Install `scitex-db` and use its own namespace:

```python
import scitex_db
```

Use a context manager for SQLite operations; the
[disposable quick start](11_quick-start.md) checks actual rows and arrays.
The core dependencies include `scitex-logging`, not `scitex-core`; the
`postgresql` extra declares `psycopg2-binary` and `sqlalchemy`. See
[01_installation](01_installation.md) for the complete current requirement and
extra definitions and the difference between imports and native backend tests.

This distribution ships `scitex_db`, not a `scitex` package or a `scitex.db`
alias. A separately installed umbrella distribution owns any facade or command
forwarding. Its installed behavior must be checked separately; this skill does
not assert that the two import paths are the same module. Core-only import/CLI
availability does not qualify an existing-file health scan or PostgreSQL server.

## Sub-skills

### Mandatory

* [01_installation](01_installation.md) — pip install + extras + verify
* [11_quick-start](11_quick-start.md) — disposable verified SQLite example
* [03_python-api](03_python-api.md) — Public symbols
* [10_cli-reference](10_cli-reference.md) — canonical CLI contracts and limits

### Deep-dive

* [13_mixins](13_mixins.md) — The mixin architecture, and where the two backends diverge
* [16_sqlite-to-postgres](16_sqlite-to-postgres.md) — Porting to PostgreSQL: the failures that do not raise
* [14_numpy-blob](14_numpy-blob.md) — Storing ndarrays with compression
* [15_maintenance](15_maintenance.md) — `check_health`, `delete_duplicates`, `inspect`
* [02_quick-start](02_quick-start.md), [12_python-api](12_python-api.md) — historical redirects
* [04_cli-reference](04_cli-reference.md) — historical CLI redirect

* [17_readonly-workers](17_readonly-workers.md) — Worker-local read-only connections and thread limits
