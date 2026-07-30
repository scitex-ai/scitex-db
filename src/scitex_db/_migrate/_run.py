#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The production entry point: one guarded run from a source path to a marker.

Everything this composes was built and merged separately, each verified against
real PostgreSQL 16.14 and 18.4. This module is the only place they are wired
together, and its job is to make the SAFE order the ONLY order:

    preflight (refuse unless READY)
      -> DDL
      -> copy rows (keyset paged)
      -> indexes, then triggers
      -> verify (per-row checksums over every column)
      -> completion marker, LAST and only if verification was clean

THERE IS NO WAY TO SKIP THE PREFLIGHT, deliberately. Not a ``force=`` argument,
not a ``skip_checks=`` escape hatch. The preflight is what knows that a column
holds a NUL byte PostgreSQL will reject, or that a table has no key to pair rows
by; a run that could proceed past it would fail mid-copy with a driver error
naming neither the table nor the reason -- which is exactly how the NUL bytes in
``messages.body`` were found on 2026-07-30, by running against a real PostgreSQL
rather than by reading the code. A gate that callers can turn off is not a gate.

WHY QUIESCENCE IS REQUIRED, beyond not losing late writes. The source is read
TWICE -- once to copy, once to verify -- so if writers are live, those two reads
see different databases and a mismatch becomes ambiguous: nobody can tell a copy
bug from ordinary drift. That is not hypothetical. On 2026-07-30 this toolkit
reported 2 mismatches against the live card store which turned out to be drift at
~15.5 rows/minute, proved only by re-running against a single materialized
snapshot. Quiescence is what makes a verification FAILURE mean something, not
merely what keeps late writes from being lost.

THE DESTINATION CARRIES ITS OWN PLACEHOLDER, and that is a correctness fix rather
than a convenience. :func:`._copy.finalize` once hardcoded sqlite3's ``?``, which
is a syntax error in PostgreSQL -- so every real migration would have failed at
its FINAL step, after copying every row. Binding ``placeholder`` to the same
object that carries the driver's callables means a caller cannot supply a
psycopg2 writer and forget to change it. The wrong combination is unconstructible
rather than merely documented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from ._copy import (
    MigrationRefused,
    MigrationResult,
    Quiescence,
    apply_schema_objects,
    destination_is_usable,
    finalize,
    verify_plan,
)
from ._ddl import quote_identifier
from ._introspect import connect_readonly, list_tables, read_rows
from ._plan import CARDS_STORE_DISPOSITIONS, TablePlan, build_plan
from ._preflight import PreflightReport, TablePreflight, preflight

__all__ = ["Destination", "RunReport", "migrate"]


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


@dataclass(frozen=True)
class RunReport:
    """What the run did, at every stage, including what it did not carry.

    ``rows_copied`` and ``result.reports[].rows_compared`` are two counts of the
    same rows taken by DIFFERENT readers -- the copy loop counts what it
    inserted, the verification counts what it paired. They are both reported
    rather than reconciled into one number, because when they disagree the
    disagreement is the diagnosis: verification already fails on a missing row,
    and seeing that it compared MORE rows than were copied says the source grew
    underneath the run, which is a quiescence failure rather than a copy bug.
    Collapsing them would throw away the distinction that took a re-run against
    a snapshot to establish the first time.
    """

    preflight: PreflightReport
    rows_copied: Mapping[str, int]
    applied_objects: tuple[str, ...]
    result: MigrationResult
    transformations: Any = None

    @property
    def ok(self) -> bool:
        return self.result.ok

    def summary(self) -> str:
        """Every stage's outcome, including the things that did not move.

        Exclusions and uncarried objects are printed on success as well as on
        failure. A summary listing only what it copied reads as a complete copy,
        and this migration deliberately leaves tables behind.
        """
        lines = [f"source: {self.preflight.source}"]
        for table, n in self.rows_copied.items():
            lines.append(f"  {table}: {n} row(s) copied")
        lines.append(
            f"  schema objects applied: {list(self.applied_objects) or 'NONE'}"
        )
        # Printed on success as well as failure. A destination that differs
        # from its source in ANY way must say so in the same place it reports
        # the successes, or the reader takes "verified" to mean "identical".
        lines.append(
            self.transformations.summary()
            if self.transformations is not None
            else "transformations: none declared (destination is byte-identical)"
        )
        lines.append(self.result.summary())
        return "\n".join(lines)


def _insert_sql(entry: TablePreflight, placeholder: str) -> str:
    columns = [c.name for c in entry.columns]
    names = ", ".join(quote_identifier(c) for c in columns)
    marks = ", ".join(placeholder for _ in columns)
    return f"INSERT INTO {quote_identifier(entry.table)} ({names}) VALUES ({marks})"


def _entry_for(report: PreflightReport, table: str) -> TablePreflight:
    return next(e for e in report.tables if e.table == table)


def _transformed(
    row: Mapping[str, Any], entry: TablePreflight, transformations: Any
) -> Mapping[str, Any]:
    """Apply the declared transformations to one row, or pass it through.

    Used on BOTH the copy path and the verification's source read, from the
    same declaration. That is what makes the check ``destination == rule(source)``
    rather than "skip the transformed rows" -- an undeclared difference in a
    transformed row still fails, because only the declared rule was applied to
    the side being compared.
    """
    if transformations is None:
        return row
    key = tuple(row[k] for k in entry.key_columns)
    return {
        name: transformations.apply(entry.table, key, name, value)
        for name, value in row.items()
    }


def _copy_table(
    conn: Any,
    entry: TablePreflight,
    destination: Destination,
    *,
    batch_size: int,
    transformations: Any = None,
) -> int:
    """Copy one table's rows, returning how many were inserted.

    The count is what the loop actually inserted, not the preflight's row count.
    Reporting the preflight's number here would be an estimate dressed as a
    result -- and a run that copied nothing would report the full total.
    """
    columns = [c.name for c in entry.columns]
    sql = _insert_sql(entry, destination.placeholder)
    copied = 0
    batch: list[tuple[Any, ...]] = []
    for row in read_rows(
        conn, entry.table, columns, entry.key_columns, batch_size=batch_size
    ):
        row = _transformed(row, entry, transformations)
        batch.append(tuple(row[c] for c in columns))
        if len(batch) >= batch_size:
            destination.write_many(sql, batch)
            copied += len(batch)
            batch = []
    if batch:
        destination.write_many(sql, batch)
        copied += len(batch)
    return copied


def migrate(
    source_path: str,
    destination: Destination,
    quiescence: Quiescence,
    *,
    source_identity: str,
    completed_at: str,
    store_identity: str | None,
    dispositions: Mapping[str, TablePlan] = CARDS_STORE_DISPOSITIONS,
    batch_size: int = 1000,
    transformations: Any = None,
) -> RunReport:
    """Migrate ``source_path`` into ``destination``, or refuse and write nothing.

    ``quiescence`` is positional and has no default: a migration that could be
    started by forgetting an argument is one that will be. See
    :class:`._copy.Quiescence` for why it must name a mechanism.

    ``completed_at`` is supplied rather than read from the clock, so the marker
    records the run the operator believes they performed and a test's marker is
    deterministic.

    ``store_identity`` is keyword-only with no default and may be ``None``. It
    goes into the marker so a reader can ask the destination WHICH store it is,
    not merely whether it is complete. See :func:`._copy.finalize` for why an
    address cannot serve as an identity, and for why identity alone does not
    make a destination authoritative.

    This function does NOT read the identity out of the source. The package
    hardcodes no table or column name -- tables come from the plan and columns
    from ``PRAGMA table_info`` -- and ``schema_meta.store_uuid`` is a fact about
    scitex-cards' schema, not about migrations. The caller knows where its own
    identity lives; this records what it is told.

    Raises :class:`._copy.MigrationRefused` before touching the destination if
    the preflight is not READY, or if the destination already carries a
    completion marker. The second guard matters as much as the first: migrating
    into an already-migrated database would insert every row a second time, and
    the resulting duplicates would fail verification only AFTER the writes had
    happened.

    Raises :class:`._verify.MigrationVerificationError` if any table cannot be
    verified, and :class:`._copy.MigrationRefused` if any table's verification
    fails -- in both cases leaving the destination WITHOUT a marker, which is
    what makes it unusable rather than silently partial.
    """
    report = preflight(source_path, dispositions, transformations)
    if not report.ok:
        raise MigrationRefused(
            "refusing to migrate: the preflight is NOT READY, so nothing has "
            "been written. Every blocker below is a condition this run would "
            "otherwise have hit partway through, with the destination already "
            "half-populated:\n" + report.summary()
        )

    already_migrated = destination_is_usable(destination.fetch)
    # The probe just SELECTed from a table that does not exist on a fresh
    # destination. PostgreSQL treats that as aborting the transaction, so the
    # connection has to be cleared before anything is written. Nothing has been
    # written yet, so this can only ever discard the failed probe.
    if destination.reset is not None:
        destination.reset()

    if already_migrated:
        raise MigrationRefused(
            "refusing to migrate: the destination already carries a completion "
            "marker, so it holds a finished migration. Copying into it would "
            "insert every row a second time. Point at an empty database, or "
            "drop the destination deliberately -- this tool will not overwrite "
            "a completed store on its own."
        )

    conn = connect_readonly(source_path)
    try:
        plan = build_plan(list_tables(conn), dispositions)

        for entry in report.tables:
            try:
                destination.execute(entry.ddl, ())
            except Exception as exc:
                # The first write is where a poisoned transaction surfaces, and
                # the driver's own message ("current transaction is aborted")
                # names the symptom rather than the cause. Say the cause here,
                # because the reader is looking at a CREATE TABLE that is not
                # itself wrong.
                raise MigrationRefused(
                    f"{entry.table}: the destination rejected the very first "
                    f"statement of the migration. If this is PostgreSQL and the "
                    f"error mentions an aborted transaction, the cause is the "
                    f"completion-marker probe that ran just before this: on a "
                    f"fresh destination it selects from a table that does not "
                    f"exist, which aborts the transaction. Pass "
                    f"`Destination(reset=conn.rollback)` so it is cleared. "
                    f"Driver error: {exc}"
                ) from exc

        rows_copied = {
            entry.table: _copy_table(
                conn,
                entry,
                destination,
                batch_size=batch_size,
                transformations=transformations,
            )
            for entry in report.tables
        }

        # After the rows, and indexes before triggers -- see
        # `._copy.apply_schema_objects`, which owns that ordering.
        applied = apply_schema_objects(report.carried, destination.execute)

        columns = {e.table: [c.name for c in e.columns] for e in report.tables}
        keys = {e.table: list(e.key_columns) for e in report.tables}

        # Every column goes into the checksummed set, `revision` included. That
        # is not incidental: scitex-cards' optimistic lock is
        # `UPDATE ... WHERE id=? AND revision=?`, so a revision that arrived
        # wrong would leave a lock that still FUNCTIONS while comparing against
        # the wrong number. Widening the set later would have meant every row
        # migrated before the widening was never checked on that column.
        reports = verify_plan(
            plan,
            lambda table: (
                _transformed(row, _entry_for(report, table), transformations)
                for row in read_rows(
                    conn,
                    table,
                    columns[table],
                    keys[table],
                    batch_size=batch_size,
                )
            ),
            lambda table: destination.read_table(
                table, columns[table], keys[table]
            ),
            key_columns=keys,
            columns=columns,
            empty_tables=report.empty_tables,
        )

        result = finalize(
            plan,
            reports,
            quiescence,
            destination.execute,
            source_identity=source_identity,
            completed_at=completed_at,
            store_identity=store_identity,
            placeholder=destination.placeholder,
            transformations=transformations,
        )
    finally:
        conn.close()

    return RunReport(
        preflight=report,
        rows_copied=rows_copied,
        applied_objects=applied,
        result=result,
        transformations=transformations,
    )


# EOF
