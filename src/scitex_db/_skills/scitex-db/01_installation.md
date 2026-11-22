---
description: |
  [TOPIC] Installation
  [DETAILS] Standalone scitex_db import,declared runtime dependencies and optional PostgreSQL driver dependencies; installed checks are separate from native backend qualification.
tags: [scitex-db-installation]
---

# Installation

## Standard

Python 3.10 or newer is required. Install into your chosen environment:

```bash
python -m pip install scitex-db
```

The declared runtime dependencies in `pyproject.toml` are `click>=8.0`,
`numpy`, `pandas` and `scitex-logging>=0.2.0`; `scitex-core` is not a declared
runtime dependency. SQLite uses Python's `sqlite3` module, so the Python build
must include SQLite support. Native build requirements for dependencies depend
on the platform and available wheels; this is not a no-system-dependencies
promise.

## Optional extras

| Extra | Declared purpose |
|---|---|
| `postgresql` | `psycopg2-binary` and `sqlalchemy`; the driver import is `psycopg2`, not `psycopg` |
| `git` | `GitPython` for Git-related helpers |
| `dev` | Dev tooling,pytest/coverage/pre-commit and `psycopg2-binary` for tests |
| `docs` | Sphinx, RTD theme,MyST parser and Sphinx extensions |
| `all` | References the four named extras (`git`,`postgresql`,`dev`,`docs`; plus their dependencies) |

The `all` row groups the four named extras; it does not add a new backend.

```bash
python -m pip install 'scitex-db[postgresql]'
```

A core-only environment can import `scitex_db` and use SQLite without the
PostgreSQL driver. The lazy `PostgreSQL` attribute returns `None` if an
`ImportError` prevents the backend from loading (`scitex_db.__getattr__`).
Installing the extra enables driver imports; it does not create a PostgreSQL
server, database or credentials, or establish live query/transaction support.

## Verify the installed environment

```bash
python -c "import sqlite3, scitex_db; print(scitex_db.__version__, sqlite3.sqlite_version)"
scitex-db --version
scitex-db --help
```

These check the selected interpreter's imports, distribution version and CLI
availability. They do not prove a completed health scan,repairs, configuration
loading or native PostgreSQL behavior. Use the disposable SQLite example in
[11_quick-start.md](11_quick-start.md) for actual row/array results.

## Editable install (development)

```bash
git clone https://github.com/scitex-ai/scitex-db.git
cd scitex-db
python -m pip install -e '.[dev]'
```

Editable metadata and imports describe that checkout; they do not prove that a
published wheel or a running service has adopted it. The project targets
`src/scitex_db` for wheel packaging. Requirement versions and extras belong in
`pyproject.toml`; check installed `importlib.metadata.requires("scitex-db")`
when diagnosing a particular environment.

## Standalone namespace and umbrella scope

This distribution provides `scitex_db` and the `scitex-db` command. It does not
ship a `scitex` package or implement a `scitex.db` alias. A separately installed
umbrella distribution owns any facade or CLI forwarding it exposes; inspect
that distribution's installed version and behavior rather than assuming module
identity or backend parity. No umbrella install or alias is required for this
package's SQLite API.

Source owners: `pyproject.toml`, `src/scitex_db/__init__.py`, `__main__.py` and
`_postgresql/_PostgreSQL.py`. Existing leaf checks in
`tests/scitex_db/test___main__.py` and `test__skills.py` cover their stated CLI
and static method-name scope; installed core/extra profiles and actual SQLite
fixtures are separate behavioral evidence. See [13_mixins.md](13_mixins.md)
and [15_maintenance.md](15_maintenance.md) for backend and health limits.
