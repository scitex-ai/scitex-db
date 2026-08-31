---
name: scitex-db
description: |
  [WHAT] Relational-DB wrapper for scientific Python, on PostgreSQL.
  [WHEN] Use when the user asks to "persist experiment results to Postgres", "store numpy arrays in a database", "inspect the schema of a Postgres database", "save/load compressed ndarrays from a table", "vacuum / analyze / reindex a store", or "pre-flight an in-place schema change on a live store".
  [HOW] `import scitex_db` then call `PostgreSQL(dbname=..., user=..., ...)`.
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

One database class, `PostgreSQL`, composed from a dozen shared mixins,
plus a `schema_change` package for pre-flighting an in-place schema
change against a live store.

The backend requires the `postgresql` extra (`psycopg2`). Without it
`scitex_db.PostgreSQL` is `None` rather than an ImportError — see
[01_installation](01_installation.md).

## Installation & import (two equivalent paths)

The same module is reachable via two install paths. Both forms work at
runtime; which one a user has depends on their install choice.

```python
# Standalone — pip install scitex-db
import scitex_db
scitex_db.PostgreSQL(...)

# Umbrella — pip install scitex
import scitex.db
scitex.db.PostgreSQL(...)
```

`pip install scitex-db` alone does NOT expose the `scitex` namespace;
`import scitex.db` raises `ModuleNotFoundError`. To use the
`scitex.db` form, also `pip install scitex`.

See [../../general/02_interface-python-api.md] for the ecosystem-wide
rule and empirical verification table.

## Sub-skills

### Mandatory

* [01_installation](01_installation.md) — pip install + extras + verify
* [02_quick-start](02_quick-start.md) — minimal end-to-end example
* [03_python-api](03_python-api.md) — Public symbols
* [04_cli-reference](04_cli-reference.md) — `scitex-db` console entry

### Deep-dive

* [13_mixins](13_mixins.md) — The mixin architecture and the measured surface
* [14_numpy-blob](14_numpy-blob.md) — Storing ndarrays in `BYTEA` columns
* [15_maintenance](15_maintenance.md) — vacuum / analyze / sizes / backup
