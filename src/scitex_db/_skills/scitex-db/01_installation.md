---
description: |
  [TOPIC] Installation
  [DETAILS] pip install scitex-db. The PostgreSQL backend needs the [postgresql] extra, which adds psycopg.
tags: [scitex-db-installation]
---

# Installation

## Standard

```bash
pip install scitex-db
```

Pulls `numpy`, `pandas`, `click`, and `scitex-core`.

The `PostgreSQL` backend is **not** usable from this install alone — it
imports `psycopg2`, which arrives with the extra below. Without it,
`scitex_db.PostgreSQL` resolves to `None` rather than raising, so check
the symbol before using it if you support both install shapes.

## Optional extras

| Extra | Purpose |
|---|---|
| `postgresql` | Adds `psycopg2-binary` + `sqlalchemy` for the `PostgreSQL` backend |
| `dev` | Test + lint tooling |
| `docs` | Sphinx + RTD theme |
| `all` | Everything above |

```bash
pip install 'scitex-db[postgresql]'
```

## Verify

```bash
python -c "import scitex_db; print(scitex_db.__version__)"
python -c "import scitex_db; print(scitex_db.PostgreSQL)"   # None => extra missing
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
