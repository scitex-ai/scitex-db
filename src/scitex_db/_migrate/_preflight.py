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
    NulFinding,
    SchemaObject,
    connect_readonly,
    list_indexes,
    list_tables,
    list_triggers,
    nul_findings,
    primary_key_columns,
    read_columns,
    stored_types,
)
from ._plan import CARDS_STORE_DISPOSITIONS, MigrationPlanError, TablePlan
from ._plan import build_plan, exclusions, tables_to_migrate
from ._triggers import TriggerTranslationError, translate_schema_object

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
    nul_findings: tuple[NulFinding, ...] = ()

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
            # The COUNT leads, because it is what decides the remedy: 2 rows is
            # a hand-correction with an audit trail, 2000 is something
            # systematic, and a report naming only the column cannot tell them
            # apart.
            detail = "; ".join(f.describe() for f in self.nul_findings)
            reasons.append(
                (f"{detail}. " if detail else "")
                + f"column(s) {list(self.nul_columns)} contain a NUL (0x00) byte, "
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
    #: Objects the translator produced output for. THIS IS A SYNTACTIC CLAIM,
    #: NOT A PROMISE THAT THEY WILL ARRIVE. Nothing here has asked a destination
    #: whether the produced DDL is valid for it -- this report has no
    #: destination, by design. A trigger with a subquery in its WHEN clause
    #: translates cleanly and PostgreSQL refuses it outright; that gap cost a
    #: full 21,792-row copy on 2026-07-31. Acceptance is proven in
    #: `._run.migrate`, after the tables exist and before any row is copied,
    #: which is the first moment the question can be asked truthfully.
    carried: tuple[SchemaObject, ...] = field(default_factory=tuple)
    #: Objects belonging to EXCLUDED tables. Not a problem and not a promise:
    #: their table is not being migrated, so applying them would fail against a
    #: relation that does not exist. Held separately from `carried` because
    #: counting them there overstates what will arrive, and separately from
    #: `uncarried` because nothing is wrong with them and they must not block.
    skipped: tuple[SchemaObject, ...] = field(default_factory=tuple)
    #: Objects the CALLER declined, each with a stated reason. Distinct from
    #: `uncarried` (nobody decided) and from `skipped` (its table is not
    #: going): someone looked at this object and said no, on the record.
    declined: tuple[tuple[SchemaObject, str], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Ready only if every table is ready AND nothing is left uncarried.

        `uncarried` gates the verdict deliberately. A table's columns are not
        the whole of what a store guarantees: on the scitex-cards store the
        TRIGGERS ARE the append-only invariant (four `BEFORE DELETE` that
        RAISE(ABORT), one immutability guard), so a destination without them
        accepts the DELETE the source refuses. A row-for-row verification
        cannot see that -- every row matches while the guarantee is gone.

        `carried` holds the objects that DO have a faithful translation, and
        they do not block. The distinction is the point: "we can move this"
        and "nobody has decided what to do about this" are different states,
        and collapsing them would either block a migration that is actually
        safe or wave through one that is not.
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
        for obj, reason in self.declined:
            lines.append(
                f"  {obj.kind} {obj.name} on {obj.table}: DECLINED by the "
                f"caller -- {reason}"
            )
        for obj in self.skipped:
            lines.append(
                f"  {obj.kind} {obj.name} on {obj.table}: not applied -- its "
                f"table is excluded from the migration, so there is nothing "
                f"for it to attach to. Printed rather than dropped silently, "
                f"because a silent skip here failed mid-run once."
            )
        for obj in self.uncarried:
            lines.append(
                f"  {obj.kind} {obj.name} on {obj.table}: CANNOT BE CARRIED "
                f"-- no faithful translation is known for this form. Port it "
                f"by hand or drop it deliberately; it will not arrive on its "
                f"own."
            )
        lines.append(
            f"verdict: {'READY' if self.ok else 'NOT READY'} "
            f"-- {len(self.tables)} table(s) to migrate, "
            f"{self.total_rows} row(s), {len(self.excluded)} excluded, "
            f"{len(self.carried)} schema object(s) carried, "
            f"{len(self.uncarried)} uncarried"
        )
        if self.carried:
            # Said out loud, on every report, because READY reads as "this will
            # work" and for these objects it means only "these translated".
            # The unstated half is where the 2026-07-31 failure lived.
            lines.append(
                f"note: the {len(self.carried)} carried object(s) are TRANSLATED, "
                f"not yet ACCEPTED -- no destination has been asked whether the "
                f"produced DDL is valid for it. `migrate()` proves that after "
                f"the tables exist and before any row is copied."
            )
        return "\n".join(lines)


def _fully_declared(finding, table: str, transformations) -> bool:
    """Whether EVERY affected row in this column has a declared escape.

    Compared by COUNT, and the count is exact rather than sampled -- the
    finding's ``row_count`` comes from a ``COUNT(*)``, not from the capped key
    sample it prints for humans. Partial coverage returns False and the column
    stays a blocker, because the undeclared remainder would raise mid-copy.
    """
    declared = sum(
        1
        for e in transformations.escapes
        if e.table == table and e.column == finding.column
    )
    return declared == finding.row_count


def preflight(
    source_path: str,
    dispositions: Mapping[str, TablePlan] = CARDS_STORE_DISPOSITIONS,
    transformations: "Transformations | None" = None,
    excluded_objects: Mapping[str, str] | None = None,
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
            nul = nul_findings(conn, table, columns, keys)
            # A NUL column stops being a blocker only when EVERY affected row
            # has a declared escape. Partial coverage must still block: the
            # undeclared remainder would raise mid-copy, which is the late
            # failure this preflight exists to prevent.
            if transformations is not None:
                nul = tuple(
                    f
                    for f in nul
                    if not _fully_declared(f, table, transformations)
                )
            count = conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
            entries.append(
                TablePreflight(
                    table=table,
                    columns=columns,
                    key_columns=keys,
                    row_count=int(count),
                    unstorable=bad,
                    ddl=create_table_ddl(table, columns),
                    nul_columns=tuple(f.column for f in nul),
                    nul_findings=nul,
                )
            )
        # Classify every non-table object by asking the translator to actually
        # produce its DDL. Attempting the translation is the check: a form
        # listed as "supported" that turns out not to translate would be a
        # claim without a test behind it, and the whole point of this gate is
        # that nothing is assumed to arrive.
        carried: list[SchemaObject] = []
        uncarried: list[SchemaObject] = []
        skipped: list[SchemaObject] = []
        declined: list[tuple[SchemaObject, str]] = []
        declared = dict(excluded_objects or {})
        migrating = set(tables_to_migrate(plan))
        for obj in list_triggers(conn) + list_indexes(conn):
            # A caller may DECLINE an object with a stated reason -- the same
            # rule tables already live under, one level down: every object is
            # carried, or excluded FOR A REASON, and nothing is merely absent.
            # The case this exists for is an object the destination gets
            # NATIVELY rather than by translation: scitex-cards generates the
            # PostgreSQL form of their guards from a running server, so a
            # translated copy would be the inferior duplicate of a better one.
            if obj.name in declared:
                declined.append((obj, declared.pop(obj.name)))
                continue
            # An object on an EXCLUDED table is a third thing, neither "will
            # arrive" nor "cannot be translated". Its table is not going, so
            # applying it would target a relation that does not exist -- which
            # is exactly how this was found, mid-run and after every row had
            # already been copied.
            if obj.table not in migrating:
                skipped.append(obj)
                continue
            try:
                translate_schema_object(obj)
            except TriggerTranslationError:
                uncarried.append(obj)
            else:
                carried.append(obj)

        if declared:
            # A name that matched nothing is a stale exclusion, and staleness
            # here is dangerous in the quiet direction: the object it used to
            # cover may have been renamed, in which case the rename is now
            # UNCARRIED and the exclusion is silently protecting nothing.
            raise MigrationPlanError(
                f"excluded_objects names {sorted(declared)}, which do not "
                f"exist in this source. An exclusion that matches nothing "
                f"protects nothing -- if the object was renamed, its new name "
                f"is now unaccounted for."
            )

        return PreflightReport(
            source=source_path,
            tables=tuple(entries),
            excluded=exclusions(plan),
            uncarried=tuple(uncarried),
            carried=tuple(carried),
            skipped=tuple(skipped),
            declined=tuple(declined),
        )
    finally:
        conn.close()


# EOF
