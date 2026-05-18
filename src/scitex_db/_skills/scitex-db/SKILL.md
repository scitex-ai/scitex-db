---
name: scitex-db
description: |
  [WHAT] Relational-DB wrapper for scientific Python.
  [WHEN] Use when the user asks to "store numpy arrays in SQLite", "persist experiment results to Postgres", "dedupe rows in a table", "check this SQLite DB is healthy / not corrupt", "inspect the schema of a DB", "save/load compressed ndarrays a....
  [HOW] `import scitex_db` then call `SQLite3(db_path, ...)`.
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

Two database classes (`SQLite3`, `PostgreSQL`) composed from a dozen
shared mixins, plus standalone maintenance helpers.

## Installation & import (two equivalent paths)

The same module is reachable via two install paths. Both forms work at
runtime; which one a user has depends on their install choice.

```python
# Standalone — pip install scitex-db
import scitex_db
scitex_db.SQLite3(...)

# Umbrella — pip install scitex
import scitex.db
scitex.db.SQLite3(...)
```

`pip install scitex-db` alone does NOT expose the `scitex` namespace;
`import scitex.db` raises `ModuleNotFoundError`. To use the
`scitex.db` form, also `pip install scitex`.

See [../../general/02_interface-python-api.md] for the ecosystem-wide
rule and empirical verification table.

## Sub-skills

### Mandatory

* [01_installation](01_installation.md) — pip install + extras + verify
* [02_quick-start](02_quick-start.md) — SQLite3 + PostgreSQL minimal examples
* [03_python-api](03_python-api.md) — Public symbols
* [04_cli-reference](04_cli-reference.md) — `scitex-db` console entry

### Deep-dive

* [13_mixins](13_mixins.md) — The mixin architecture (capability groups)
* [14_numpy-blob](14_numpy-blob.md) — Storing ndarrays with compression
* [15_maintenance](15_maintenance.md) — `check_health`, `delete_duplicates`, `inspect`
* [11_quick-start](11_quick-start.md), [12_python-api](12_python-api.md) — historical leaves
* [10_cli-reference](10_cli-reference.md) — historical CLI notes
