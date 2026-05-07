# scitex-db

<!-- scitex-badges:start -->
[![PyPI](https://img.shields.io/pypi/v/scitex-db.svg)](https://pypi.org/project/scitex-db/)
[![Python](https://img.shields.io/pypi/pyversions/scitex-db.svg)](https://pypi.org/project/scitex-db/)
[![Tests](https://github.com/ywatanabe1989/scitex-db/actions/workflows/test.yml/badge.svg)](https://github.com/ywatanabe1989/scitex-db/actions/workflows/test.yml)
[![Install Test](https://github.com/ywatanabe1989/scitex-db/actions/workflows/install-test.yml/badge.svg)](https://github.com/ywatanabe1989/scitex-db/actions/workflows/install-test.yml)
[![Coverage](https://codecov.io/gh/ywatanabe1989/scitex-db/graph/badge.svg)](https://codecov.io/gh/ywatanabe1989/scitex-db)
[![Docs](https://readthedocs.org/projects/scitex-db/badge/?version=latest)](https://scitex-db.readthedocs.io/en/latest/)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
<!-- scitex-badges:end -->

Database utilities for scientific computing.

## Problem and Solution

| # | Problem | Solution |
|---|---------|----------|
| 1 | **Storing ndarrays in SQLite means `pickle.dumps → BLOB`** -- no compression, no type info, no deterministic hashing | **`SQLite3.save_array(name, arr)` / `load_array(name)`** -- compressed BLOB storage with typed round-trip; compatible with pandas via `to_df` |
| 2 | **`sqlite3` API is low-level** -- every project re-writes connect/transaction/execute boilerplate | **`with db:` context-manager transactions** -- health checks, duplicate removal, schema inspection built in |

## Overview

`scitex-db` provides enhanced database operations designed for scientific research:

### Features

**SQLite3 with Scientific Extensions:**
- 📊 **Array Storage** - Store/retrieve NumPy arrays efficiently
- 🔬 **Blob Storage** - Serialize Python objects with metadata
- 📦 **Batch Operations** - High-performance bulk inserts
- 🔍 **Advanced Queries** - Scientific query patterns
- 🗂️ **Git Integration** - Version control for databases
- 📤 **Import/Export** - CSV, JSON, DataFrame conversions
- 🔧 **Maintenance Tools** - Health checks, deduplication

**PostgreSQL Support:**
- Full-featured PostgreSQL wrapper
- Optimized for scientific datasets

**CLI Tools:**
```bash
scitex-db inspect database.db
scitex-db health database.db --fix
```

## Installation

```bash
pip install scitex-db
```

For PostgreSQL:
```bash
pip install scitex-db[postgresql]
```

For all features:
```bash
pip install scitex-db[all]
```

## Architecture

```
scitex_db/
├── __init__.py                ← public API (SQLite3, PostgreSQL, ...)
├── __main__.py                ← `python -m scitex_db` CLI entry
├── _BaseMixins/               ← backend-agnostic mixins (CRUD, schema, ...)
├── _sqlite3/                  ← SQLite3 driver
├── _SQLite3Mixins/            ← SQLite3-specific mixin overrides
├── _postgresql/               ← PostgreSQL driver
├── _PostgreSQLMixins/         ← PostgreSQL-specific mixin overrides
├── _check_health.py           ← `scitex-db health` command
├── _inspect.py                ← `scitex-db inspect` (schema dump + stats)
├── _inspect_optimized.py      ← faster path for large DBs
├── _delete_duplicates.py      ← duplicate-row cleanup
├── _utils.py                  ← shared helpers
└── _skills/                   ← agent-facing skill files
```

Each backend (`_sqlite3/`, `_postgresql/`) composes its mixin folder
with `_BaseMixins/` to expose a uniform `SQLite3` / `PostgreSQL` class —
swap drivers without changing call sites.

## Quick Start

### Basic Usage

```python
from scitex_db import SQLite3

# Initialize
db = SQLite3("experiments.db")

# Create table
db.create_table("results", {
    "id": "INTEGER PRIMARY KEY",
    "experiment": "TEXT",
    "accuracy": "REAL"
})

# Insert data
db.insert_many("results", [
    {"experiment": "exp1", "accuracy": 0.95},
    {"experiment": "exp2", "accuracy": 0.92}
])

# Query
results = db.get_rows("results", where="accuracy > 0.9")
print(results)
```

### Array Storage

```python
import numpy as np

# Save arrays
data = np.random.rand(1000, 50)
db.save_array("features", data,
              column="embeddings",
              additional_columns={"model": "bert"})

# Load arrays
loaded = db.load_array("features", "embeddings",
                       where="model = 'bert'")
```

### Blob Storage

```python
# Store arbitrary objects
model = {"weights": np.random.rand(100), "config": {...}}
db.save_blob("models", model,
             column="checkpoint",
             additional_columns={"epoch": 10})

# Retrieve
model = db.load_blob("models", "checkpoint", where="epoch = 10")
```

### Git Integration

```python
from scitex_db import SQLite3

db = SQLite3("versioned.db")
db.init_git()  # Initialize git tracking

# Automatic commits on changes
db.insert("results", {"value": 42})
# Commits with message: "Insert 1 row(s) into results"
```

## Advanced Features

### Transaction Management

```python
with db.transaction():
    db.insert("table1", {...})
    db.insert("table2", {...})
    # Auto-commit on success, rollback on error
```

### Batch Operations

```python
# High-performance bulk insert
large_dataset = [{"id": i, "value": i**2} for i in range(10000)]
db.insert_many("data", large_dataset, batch_size=1000)
```

### Database Inspection

```python
# Get comprehensive summary
db.summary  # or db()

# Inspect specific table
db.inspect_table("results")

# Health check
from scitex_db import check_health
check_health("database.db", fix_issues=True)
```

## Demo

```mermaid
flowchart LR
    U["user code"] --> A["scitex_db.SQLite3('experiments.db')"]
    U --> B["scitex_db.PostgreSQL(host=..., user=..., ...)"]
    A --> M["_BaseMixins (CRUD · schema · maintenance)"]
    B --> M
    A -.-> SM["_SQLite3Mixins<br/>(backend overrides)"]
    B -.-> PM["_PostgreSQLMixins<br/>(backend overrides)"]
    M --> H["scitex-db health<br/>(fix orphans, vacuum)"]
    M --> I["scitex-db inspect<br/>(schema + row counts)"]
```

## Part of SciTeX Ecosystem

- `scitex-core` - Core infrastructure
- `scitex-io` - Data I/O (can use scitex-db)
- `scitex-writer` - Academic writing
- `scitex-scholar` - Paper management
- `scitex` - Main package

## License

MIT License - see LICENSE file for details.
