# scitex-db

<p align="center">
  <a href="https://scitex.ai">
    <img src="docs/scitex-logo-blue-cropped.png" alt="SciTeX" width="400">
  </a>
</p>

<p align="center"><b>Database utilities for scientific computing — SQLite3 + PostgreSQL with NumPy-aware storage.</b></p>

<p align="center">
  <a href="https://scitex-db.readthedocs.io/">Full Documentation</a> · <code>uv pip install scitex-db[all]</code>
</p>

<!-- scitex-badges:start -->
<p align="center">
  <a href="https://pypi.org/project/scitex-db/"><img src="https://img.shields.io/pypi/v/scitex-db?label=pypi" alt="pypi"></a>
  <a href="https://pypi.org/project/scitex-db/"><img src="https://img.shields.io/pypi/pyversions/scitex-db?label=python" alt="python"></a>
  <a href="https://github.com/ywatanabe1989/scitex-db/actions/workflows/rtd-sphinx-build-on-ubuntu-latest.yml"><img src="https://img.shields.io/github/actions/workflow/status/ywatanabe1989/scitex-db/rtd-sphinx-build-on-ubuntu-latest.yml?branch=develop&label=docs" alt="docs"></a>
  <a href='https://scitex-db.readthedocs.io/en/latest/'><img src='https://img.shields.io/readthedocs/scitex-db?label=docs' alt='Read the Docs'></a>
</p>
<p align="center">
  <a href="https://github.com/ywatanabe1989/scitex-db/actions/workflows/pytest-matrix-on-ubuntu-py3-11-3-12-3-13.yml"><img src="https://img.shields.io/github/actions/workflow/status/ywatanabe1989/scitex-db/pytest-matrix-on-ubuntu-py3-11-3-12-3-13.yml?branch=develop&label=tests" alt="tests"></a>
  <a href="https://codecov.io/gh/ywatanabe1989/scitex-db"><img src="https://img.shields.io/codecov/c/github/ywatanabe1989/scitex-db/develop?label=cov" alt="cov"></a>
  <a href="https://www.gnu.org/licenses/agpl-3.0"><img src="https://img.shields.io/badge/license-AGPL_v3-blue.svg" alt="License: AGPL v3"></a>
</p>
<!-- scitex-badges:end -->

---

## Problem and Solution

| # | Problem | Solution |
|---|---------|----------|
| 1 | **Storing ndarrays in SQLite** — `pickle.dumps → BLOB` gives no compression, no dtype/shape tracking, no deterministic hashing | **`save_array` / `load_array`** — typed compressed BLOBs round-trip with dtype, shape, compression and hash columns |
| 2 | **`sqlite3` API is low-level** — every project re-writes connect / transaction / execute boilerplate | **`with db.transaction(): ...`** — context-managed transactions, health checks, dedup, schema inspection built-in |
| 3 | **SQLite ↔ Postgres** — the same call site works against either backend, so switching stores never rewrites callers | **Mixin composition** — `SQLite3` and `PostgreSQL` share `_BaseMixins/`; the same call site works against either backend |

## Quick Start

```python
from scitex_db import SQLite3
import numpy as np

db = SQLite3("experiments.db")

db.create_table("results", {
    "id": "INTEGER PRIMARY KEY",
    "experiment": "TEXT",
    "accuracy": "REAL",
})
db.insert_many("results", [
    {"experiment": "exp1", "accuracy": 0.95},
    {"experiment": "exp2", "accuracy": 0.92},
])

# NumPy arrays round-trip with dtype/shape preserved
db.save_array("features", np.random.rand(1000, 50), column="embeddings",
              additional_columns={"model": "bert"})
features = db.load_array("features", "embeddings", where="model = 'bert'")
```

## Demo

```bash
scitex-db inspect-db experiments.db --tables results   # schema + row counts
scitex-db check-health experiments.db --fix --yes      # vacuum, fix orphans
```

Two commands cover the daily loop: look at a database, then verify it
is healthy. Both support `--json` for scripting.

## Installation

```bash
uv pip install "scitex-db[all]"
```

<details>
<summary>Per-backend extras</summary>

| Extra | Command | Adds |
|-------|---------|------|
| *(none)* | `uv pip install scitex-db` | SQLite3 backend, NumPy-aware storage, CLI |
| `postgresql` | `uv pip install "scitex-db[postgresql]"` | `psycopg2-binary` + `sqlalchemy` driver |
| `git` | `uv pip install "scitex-db[git]"` | `GitPython` for the db-versioning mixin |
| `all` | `uv pip install "scitex-db[all]"` | everything above, plus dev and docs |

</details>

### Configuration

Defaults work out of the box. To override, drop a `config.yaml` next to
your script, or point `SCITEX_DB_CONFIG` at one — see
[`.env.example`](./.env.example) for the full env-var list and
resolution order.

## Architecture

```mermaid
flowchart LR
    U["user code"] --> A["SQLite3('exp.db')"]
    U --> B["PostgreSQL(host=..., user=...)"]
    A --> M["_BaseMixins (CRUD · schema · batch · maintenance)"]
    B --> M
    A -.-> SM["_SQLite3Mixins<br/>(backend overrides)"]
    B -.-> PM["_PostgreSQLMixins<br/>(backend overrides)"]
    M --> H["scitex-db check-health<br/>(fix orphans, vacuum)"]
    M --> I["scitex-db inspect-db<br/>(schema + row counts)"]
```

<sub><b>Figure 1.</b> Backend composition — both drivers share `_BaseMixins/`; backend-specific behavior lives in override mixins, and maintenance CLIs sit on top.</sub>

Each backend composes its `_*Mixins/` folder onto `_BaseMixins/`, so
swapping `SQLite3` ↔ `PostgreSQL` does not change call sites.

## 2 Interfaces

<details open>
<summary><strong>Python API ⭐⭐⭐</strong> &nbsp;<sub>primary surface</sub></summary>

<br>

```python
from scitex_db import SQLite3, PostgreSQL, check_health, inspect

# Backends
db = SQLite3("experiments.db")
db = PostgreSQL(host=..., user=..., dbname=...)

# CRUD
db.insert("results", {"experiment": "exp1", "accuracy": 0.95})
db.insert_many("results", rows, batch_size=1000)
rows = db.get_rows("results", where="accuracy > 0.9")
db.update("results", {"accuracy": 0.97}, where="id = 1")
db.delete("results", where="id = 1")

# Arrays / Blobs
db.save_array(table, arr, column="data")
db.load_array(table, "data", where=...)
db.save_blob(table, obj, column="checkpoint")
db.load_blob(table, "checkpoint", where=...)

# Transactions / maintenance
with db.transaction():
    db.insert("a", {...}); db.insert("b", {...})
db.summary                # schema + row counts
inspect("experiments.db") # standalone helper
check_health("experiments.db", fix_issues=True)
```

</details>

<details>
<summary><strong>CLI ⭐⭐</strong> &nbsp;<sub><code>scitex-db &lt;subcommand&gt;</code></sub></summary>

<br>

```bash
scitex-db --help-recursive            # all subcommands at once
scitex-db inspect-db experiments.db   # schema + row counts
scitex-db inspect-db experiments.db --tables results --json
scitex-db check-health experiments.db --fix --yes
scitex-db check-health experiments.db --dry-run
scitex-db list-python-apis            # introspect public Python surface
```

Every subcommand supports `-h/--help`, `--json`, and the safety pair
`--dry-run` / `--yes` where it mutates state.

</details>

## Part of SciTeX

`scitex-db` is part of [**SciTeX**](https://scitex.ai). Install via the
umbrella with `pip install scitex[db]`, then import as `scitex.db` or
invoke `scitex db <subcommand>` — the standalone `scitex-db` package
remains the source of truth.

>Four Freedoms for Research
>
>0. The freedom to **run** your research anywhere — your machine, your terms.
>1. The freedom to **study** how every step works — from raw data to final manuscript.
>2. The freedom to **redistribute** your workflows, not just your papers.
>3. The freedom to **modify** any module and share improvements with the community.
>
>AGPL-3.0 — because we believe research infrastructure deserves the same freedoms as the software it runs on.

---

<p align="center">
  <a href="https://scitex.ai" target="_blank"><img src="docs/scitex-icon-navy-inverted.png" alt="SciTeX" width="40"/></a>
</p>
