---
description: |
  [TOPIC] Installation
  [DETAILS] pip install scitex-db. Default backend is SQLite (stdlib). Optional [postgresql] extra adds psycopg.
tags: [scitex-db-installation]
---

# Installation

## Standard

```bash
pip install scitex-db
```

Pulls `numpy`, `pandas`, `click`, and `scitex-core`. SQLite support is
built in via Python's stdlib `sqlite3` — no system deps.

## Optional extras

| Extra | Purpose |
|---|---|
| `postgresql` | Adds `psycopg` for the `PostgreSQL` backend |
| `git` | Tooling used by maintenance helpers |
| `dev` | Test + lint tooling |
| `docs` | Sphinx + RTD theme |
| `all` | Everything above |

```bash
pip install 'scitex-db[postgresql]'
```

## Verify

```bash
python -c "import scitex_db; print(scitex_db.__version__)"
scitex-db --version
scitex-db --help
```

## Editable install (development)

```bash
git clone https://github.com/ywatanabe1989/scitex-db
cd scitex-db
pip install -e '.[dev]'
```

## Umbrella alternative

`pip install scitex` exposes the same module as `scitex.db`. Standalone
`pip install scitex-db` does NOT expose the `scitex` namespace.
