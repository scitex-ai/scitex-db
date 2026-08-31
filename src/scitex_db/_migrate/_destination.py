#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The destination database, described by what the migration needs of it.

Split out of ``_run`` when that file reached its size limit, and the seam was
chosen rather than found: `_run` was holding three separable responsibilities --
the destination ADAPTER, the run REPORT, and the run itself. This is the adapter.
It has no knowledge of the migration order and the migration has no knowledge of
any driver, which is what lets the same code be exercised against sqlite3 and
psycopg2 without either being privileged.

Re-exported from ``._run`` so existing imports keep working -- `from
..._run import Destination` appears in tests and in callers outside this repo,
and a migration public surface should not churn for an internal file split.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = ["Destination"]

@dataclass(frozen=True)
class Destination:
    """A destination database, described by what the migration needs of it.

    Callables rather than a connection, so this package chooses no driver and
    can be exercised against sqlite3 and psycopg2 alike without either being
    stubbed out. Each entry is here because some step genuinely requires it:

    * ``execute(sql, params)`` -- DDL, schema objects, and the marker write.
    * ``fetch(sql)`` -- raw rows as sequences, used only to read the marker.
    * ``read_table(table, columns, key_columns)`` -- rows as MAPPINGS, for
      verification. Separate from ``fetch`` because the comparison pairs by
      column NAME; a positional tuple would silently reorder if a SELECT ever
      changed, and that is a defect the checksums could not catch because both
      sides would be reordered the same way.
    * ``placeholder`` -- the driver's parameter marker, ``?`` for sqlite3 and
      ``%s`` for psycopg2. See the module docstring for why it lives here.

    ``executemany`` is optional. Without it :meth:`write_many` loops over
    ``execute``, which is correct but slow; a driver that has a batch path
    should pass one. Making it optional keeps the minimal adapter to three
    callables, so writing one is not a barrier to running a migration.

    ``reset`` UNDOES A FAILED PROBE, AND PostgreSQL CANNOT MIGRATE WITHOUT IT.
    Pass ``conn.rollback`` for psycopg2; SQLite needs nothing. The reason is not
    obvious and was found by running a real migration rather than by reading the
    code: the first thing :func:`migrate` does is ask whether the destination
    already carries a completion marker, which on a FRESH destination means
    selecting from a table that does not exist. :func:`._copy.read_marker`
    catches that and answers "no marker", which is the correct ANSWER -- but on
    PostgreSQL a failed statement ABORTS THE ENTIRE TRANSACTION, so every
    statement afterwards fails with ``InFailedSqlTransaction``, starting with
    the very first ``CREATE TABLE``. Measured on PostgreSQL 16.14:

        SELECT ... FROM a missing table -> UndefinedTable
        subsequent CREATE TABLE         -> InFailedSqlTransaction
        after conn.rollback()           -> CREATE TABLE OK

    It is called immediately after the probe and before anything is written, so
    it can never discard real work.

    Left OPTIONAL rather than required, and the reasoning differs from
    :class:`._copy.Quiescence` on purpose. Quiescence must be constructed
    because getting it wrong loses data SILENTLY. Omitting ``reset`` fails
    LOUDLY at the first DDL, and a loud failure does not need to be made
    unconstructible -- it needs to be made SELF-EXPLAINING, which is why
    :func:`migrate` re-raises that first failure with this cause named.

    TRANSACTIONS ARE THE CALLER'S. This module never commits or rolls back,
    because whether the whole migration is one transaction is a property of the
    destination and the operator's plan, not of the copy algorithm. The
    marker-last ordering holds either way: under autocommit it is the last thing
    made durable, and under a single transaction it is the last thing written.
    """

    execute: Callable[[str, Sequence[Any]], None]
    fetch: Callable[[str], Iterable[Sequence[Any]]]
    read_table: Callable[
        [str, Sequence[str], Sequence[str]], Iterable[Mapping[str, Any]]
    ]
    placeholder: str = "?"
    executemany: Callable[[str, Sequence[Sequence[Any]]], None] | None = None
    reset: Callable[[], None] | None = None

    def write_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        """Insert a batch, using the driver's batch path when it has one."""
        if self.executemany is not None:
            self.executemany(sql, rows)
            return
        for row in rows:
            self.execute(sql, row)


# EOF
