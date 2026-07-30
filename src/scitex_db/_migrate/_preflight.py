#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dry-run a migration: report what it WOULD do, writing nothing.

WHY THIS IS A SEPARATE ENTRY POINT rather than a flag on the migration. A
``dry_run=False`` default means the destructive path is the one you get by
forgetting an argument, and a ``dry_run=True`` default means the useful path is.
Neither is good. Two functions with different names cannot be confused by
omission: :func:`preflight` has no destination and therefore cannot write, which
is a stronger guarantee than a branch that promises not to.

WHAT IT ANSWERS, all from the source alone:

* which tables would migrate, and which are excluded and why
* which columns hold data PostgreSQL would reject -- the failure that otherwise
  surfaces mid-copy as a driver error naming neither table nor reason
* which tables have no primary key, so a pairing key must be chosen rather
  than invented
* the DDL that would be executed, so a human can read it before it runs
* how many rows each table holds, which is the denominator the real run's
  verification will be measured against

EVERY PROBLEM IS COLLECTED, not raised on the first one. A preflight that stops
at the first bad column turns a schema review into as many runs as there are
problems, and the person running it has no way to tell whether they are halfway
or nearly done. :attr:`PreflightReport.ok` is the single question; the fields
say why not.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ._ddl import Column, create_table_ddl, unstorable_columns
from ._introspect import (
    SchemaObject,
    columns_with_nul,
    connect_readonly,
    list_indexes,
    list_tables,
    list_triggers,
    primary_key_columns,
    read_columns,
    stored_types,
)
from ._plan import CARDS_STORE_DISPOSITIONS, TablePlan, build_plan, exclusions
from ._plan import tables_to_migrate

__all__ = ["PreflightReport", "TablePreflight", "preflight"]


@dataclass(frozen=True)
class TablePreflight:
    """What the migration would do to one table, and what stands in the way."""

    table: str
    columns: tuple[Column, ...]
    key_columns: tuple[str, ...]
    row_count: int
    unstorable: tuple[str, ...]
    ddl: str
    nul_columns: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            not self.unstorable
            and not self.nul_columns
            and bool(self.key_columns)
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        """Human-readable reasons this table is not ready, in report order."""
        reasons = []
        if not self.key_columns:
            reasons.append(
                "no primary key: rows cannot be paired for verification, and a "
                "batched read has no stable order. Choose a unique key "
                "explicitly rather than letting one be invented."
            )
        if self.unstorable:
            reasons.append(
                f"column(s) {list(self.unstorable)} hold values PostgreSQL "
                f"would reject, because SQLite's declared type is an affinity "
                f"rather than a constraint. Fix the data or widen the target "
                f"type before migrating."
            )
        if self.nul_columns:
            reasons.append(
                f"column(s) {list(self.nul_columns)} contain a NUL (0x00) byte, "
                f"which SQLite text stores but PostgreSQL text rejects. psycopg2 "
                f"raises mid-copy on the first such row. Decide how to handle the "
                f"NUL (strip, or store as bytea) before migrating -- this tool "
                f"will not alter a stored value on its own."
            )
        return tuple(reasons)


@dataclass(frozen=True)
class PreflightReport:
    """The whole dry-run. ``ok`` is the single question; the rest says why not."""

    source: str
    tables: tuple[TablePreflight, ...]
    excluded: tuple[TablePlan, ...] = field(default_factory=tuple)
    uncarried: tuple[SchemaObject, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Ready only if every table is ready AND nothing is left uncarried.

        `uncarried` gates the verdict deliberately. The DDL translator emits
        columns, NOT NULL and PRIMARY KEY -- it does not carry TRIGGERS or
        INDEXES. On the scitex-cards store the triggers ARE the append-only
        invariant (four `BEFORE DELETE` that RAISE(ABORT), one immutability
        guard), so a destination without them accepts the DELETE the source
        refuses. A row-for-row verification cannot see that: every row matches
        while the guarantee is gone.

        So an uncarried object makes the preflight NOT READY rather than
        producing a destination that verifies clean and is quietly weaker
        than its source. Same rule the table plan already enforces -- account
        for it explicitly or fail -- applied to the objects that are not
        tables.
        """
        return all(t.ok for t in self.tables) and not self.uncarried

    @property
    def total_rows(self) -> int:
        return sum(t.row_count for t in self.tables)

    @property
    def empty_tables(self) -> tuple[str, ...]:
        """Tables with no rows, which the real run must declare as empty.

        Surfaced here because :func:`._verify.verify_table` refuses an empty
        comparison unless told the table is genuinely empty -- so the caller
        needs to know which ones those are BEFORE the run, rather than
        discovering it as a refusal partway through.
        """
        return tuple(t.table for t in self.tables if t.row_count == 0)

    def summary(self) -> str:
        """Every table's readiness, the exclusions, then the verdict.

        Exclusions and the row total are always printed, including on success.
        A preflight that says only "ok" invites the reader to assume it covered
        everything, and this migration deliberately leaves tables behind.
        """
        lines = [f"source: {self.source}"]
        for t in self.tables:
            state = "ready" if t.ok else "BLOCKED"
            lines.append(f"  {t.table}: {state} ({t.row_count} row(s), key {list(t.key_columns) or 'NONE'})")
            for reason in t.blockers:
                lines.append(f"      - {reason}")
        for plan in self.excluded:
            lines.append(f"  {plan.table}: NOT MIGRATED -- {plan.reason}")
        for obj in self.uncarried:
            lines.append(
                f"  {obj.kind} {obj.name} on {obj.table}: CANNOT BE CARRIED "
                f"-- the DDL translator emits columns, NOT NULL and PRIMARY KEY "
                f"only. Translate it or drop it deliberately; it will not "
                f"arrive on its own."
            )
        lines.append(
            f"verdict: {'READY' if self.ok else 'NOT READY'} "
            f"-- {len(self.tables)} table(s) to migrate, "
            f"{self.total_rows} row(s), {len(self.excluded)} excluded, "
            f"{len(self.uncarried)} uncarried schema object(s)"
        )
        return "\n".join(lines)


def preflight(
    source_path: str,
    dispositions: Mapping[str, TablePlan] = CARDS_STORE_DISPOSITIONS,
) -> PreflightReport:
    """Inspect ``source_path`` and report what a migration would do.

    Opens the source READ-ONLY and takes no destination argument, so it cannot
    write anywhere even by mistake.

    Propagates :class:`._plan.MigrationPlanError` when the source contains a
    table with no disposition -- deliberately, because that is the one problem
    a preflight must not merely report. Everything else here is a finding about
    a table that IS accounted for; an unaccounted table means the plan does not
    describe this store, and continuing would produce a confident report about
    the wrong set of tables.
    """
    conn = connect_readonly(source_path)
    try:
        plan = build_plan(list_tables(conn), dispositions)
        entries = []
        for table in tables_to_migrate(plan):
            columns = read_columns(conn, table)
            keys = primary_key_columns(columns)
            bad = unstorable_columns(table, columns, stored_types(conn, table, columns))
            nul = columns_with_nul(conn, table, columns)
            count = conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
            entries.append(
                TablePreflight(
                    table=table,
                    columns=columns,
                    key_columns=keys,
                    row_count=int(count),
                    unstorable=bad,
                    ddl=create_table_ddl(table, columns),
                    nul_columns=nul,
                )
            )
        return PreflightReport(
            source=source_path,
            tables=tuple(entries),
            excluded=exclusions(plan),
            uncarried=list_triggers(conn) + list_indexes(conn),
        )
    finally:
        conn.close()


# EOF
