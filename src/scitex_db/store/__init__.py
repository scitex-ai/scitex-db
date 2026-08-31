#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The portable-store seam: guards that survive a dialect change.

Five silent-failure classes, learned from a real SQLite → PostgreSQL
migration in which NINE OF TWELVE defects produced no error at all.
They returned a notification id, created a file, printed a green check,
or reported a version string that matched. A crash would have been
cheap.

This package is NOT a query wrapper. It does not wrap ``connect``,
``execute``, ``cursor``, or rows — every package that would use it
already has working data access. It sits below ``SQLite3`` /
``PostgreSQL`` and neither imports the other.

**stdlib only.** ``psycopg`` / ``psycopg2`` live behind an extra and are
imported lazily inside the one function that needs them. No numpy, no
pandas, no scitex-core, no click. This is the entire reason the seam is
adoptable: measured 2026-08-02, every package that considered
``scitex_db`` and declined recorded weight as the reason. A guard nobody
can afford to import is a guard nobody has. A change that would add a
dependency here is the wrong change, not the wrong constraint.

Contract: ``docs/portable-store-seam-surface.md``.
"""

from __future__ import annotations

from ._backend import BackendReport, describe_backend
from ._ddl import DDLResult, execute_ddl, should_run_ddl
from ._tx import begin_write
from ._portable_sql import (
    MIN_SQLITE_VERSION_FOR_IS_NOT_DISTINCT_FROM,
    POSTGRESQL_NULL_SAFE,
    SQLITE_NULL_SAFE,
    SQLITE_ONLY_UPSERT_FORMS,
    null_safe_eq,
    to_paramstyle,
)
from ._url import (
    POSTGRESQL,
    SQLITE,
    StoreLocation,
    UnknownStoreScheme,
    parse_store_url,
    resolve_store,
)

__all__ = [
    "MIN_SQLITE_VERSION_FOR_IS_NOT_DISTINCT_FROM",
    "POSTGRESQL",
    "POSTGRESQL_NULL_SAFE",
    "SQLITE",
    "SQLITE_NULL_SAFE",
    "SQLITE_ONLY_UPSERT_FORMS",
    "BackendReport",
    "DDLResult",
    "StoreLocation",
    "UnknownStoreScheme",
    "begin_write",
    "describe_backend",
    "execute_ddl",
    "null_safe_eq",
    "parse_store_url",
    "resolve_store",
    "should_run_ddl",
    "to_paramstyle",
]

# EOF
