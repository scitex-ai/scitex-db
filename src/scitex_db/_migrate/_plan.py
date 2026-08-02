#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The table plan: every source table must be MIGRATED or EXPLICITLY EXCLUDED.

WHY A PLAN EXISTS AT ALL, instead of just copying every table found. Two tables
in the scitex-cards store must NOT cross to PostgreSQL, each for a stated reason
(both answered by scitex-cards, 2026-07-30):

* ``mirror_hashes`` (2874 rows) -- per-card hashes for keeping the retired YAML
  mirror in agreement with the database. A PostgreSQL deployment has no second
  store to agree with, so the table has no meaning there; it is being dropped
  rather than carried.
* ``users`` / ``user_names`` -- empty, but NOT because the feature is unused.
  The reader is broken on a SQLite store: ``list_users`` parses the store as
  YAML, raises on the canonical binary store, and the caller fail-softs to
  ``[]``. Migrating the schema of a registry that nothing populates would
  faithfully reproduce an inert design, and treating the empty table as ground
  truth about the fleet would be worse.

A SKIP MUST NOT BE SILENT, which is the actual reason this module is a type and
not a list comprehension. If the copy loop just iterated the tables it knew
about, "excluded on purpose" and "nobody noticed this table exists" would look
identical afterwards -- and the second one loses data while reporting success.
So :func:`build_plan` REFUSES a source table it has no disposition for, rather
than skipping it. A table added to the store next month makes the migration
fail loudly instead of quietly leaving it behind.

The same asymmetry applies in reverse: a disposition naming a table that does
not exist is also an error, because it is either a typo or a stale plan, and
both mean the plan no longer describes the store it claims to describe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence

__all__ = [
    "Disposition",
    "MigrationPlanError",
    "TablePlan",
    "build_plan",
    "CARDS_STORE_DISPOSITIONS",
]


class MigrationPlanError(Exception):
    """Raised when a plan does not describe the store it is applied to."""


class Disposition(Enum):
    """What is to happen to one source table.

    ``EXCLUDE`` is deliberately not spelled "skip". A skip is something that
    happens to work out; an exclusion is a decision with a reason attached, and
    :class:`TablePlan` requires that reason.
    """

    MIGRATE = "migrate"
    EXCLUDE = "exclude"


@dataclass(frozen=True)
class TablePlan:
    """One table's disposition, with the reason when it is excluded."""

    table: str
    disposition: Disposition
    reason: str = ""

    def __post_init__(self) -> None:
        if self.disposition is Disposition.EXCLUDE and not self.reason.strip():
            raise MigrationPlanError(
                f"{self.table}: excluded with no reason given. An unexplained "
                f"exclusion is indistinguishable from an oversight the next "
                f"time someone reads this plan, and the difference is whether "
                f"data was left behind on purpose."
            )
        if self.disposition is Disposition.MIGRATE and self.reason.strip():
            # Not an error worth raising -- a note on a migrated table is
            # harmless -- but the field means "why excluded", so document that
            # it is ignored here rather than letting it read as load-bearing.
            pass

    @property
    def migrates(self) -> bool:
        return self.disposition is Disposition.MIGRATE


#: Dispositions for the scitex-cards store, as agreed with its maintainer.
#: Every table present in that store on 2026-07-30 appears here; adding a table
#: to the store without adding it here makes :func:`build_plan` fail, which is
#: the intended behaviour.
CARDS_STORE_DISPOSITIONS: Mapping[str, TablePlan] = {
    t: TablePlan(t, Disposition.MIGRATE)
    for t in (
        "tasks",
        "task_comments",
        "task_edges",
        "task_roles",
        "inbox_recipients",
        "notifications",
        "messages",
        "schema_meta",
        "dm_threads",
        "dm_thread_member_events",
        "dm_messages",
        "dm_receipts",
    )
} | {
    "mirror_hashes": TablePlan(
        "mirror_hashes",
        Disposition.EXCLUDE,
        "YAML-mirror-era bookkeeping: per-card hashes for keeping the retired "
        "YAML mirror in agreement with the database. A PostgreSQL deployment "
        "has no second store to agree with, so the rows have no meaning there. "
        "Being dropped by scitex-cards as part of the YAML purge, not carried.",
    ),
    "users": TablePlan(
        "users",
        Disposition.EXCLUDE,
        "Empty, but not because the feature is unused: list_users parses the "
        "store as YAML and raises on the canonical SQLite store, so the caller "
        "fail-softs to [] and the stable u_* id design is inert in production. "
        "Migrating a registry nothing populates would reproduce the inert "
        "design faithfully. scitex-cards owns the fix; wait for it.",
    ),
    "user_names": TablePlan(
        "user_names",
        Disposition.EXCLUDE,
        "Empty for the same reason as `users` -- the reader, not the feature, "
        "is what is missing. See that entry.",
    ),
}


def build_plan(
    source_tables: Iterable[str],
    dispositions: Mapping[str, TablePlan] = CARDS_STORE_DISPOSITIONS,
) -> tuple[TablePlan, ...]:
    """Pair every source table with its disposition, or RAISE.

    ``source_tables`` is what the source database actually contains (SQLite
    internal tables such as ``sqlite_sequence`` should be filtered out by the
    caller's introspection, since they are an implementation detail of the
    engine rather than store content).

    Raises :class:`MigrationPlanError` if any source table has no disposition,
    or if any disposition names a table that is not present. Both directions
    matter: the first would silently leave data behind, the second means the
    plan is stale or misspelled and therefore no longer describes this store.

    The returned tuple is ordered by table name so the plan is reproducible and
    diffable, not dependent on dictionary or introspection order.
    """
    present = set(source_tables)
    planned = set(dispositions)

    unplanned = sorted(present - planned)
    if unplanned:
        raise MigrationPlanError(
            f"no disposition for source table(s) {unplanned}. Every table must "
            f"be explicitly MIGRATE or EXCLUDE-with-a-reason: skipping an "
            f"unknown table would leave its rows behind while reporting a "
            f"successful migration. If these are new, add them to the "
            f"disposition map; if they should not cross, say why."
        )

    absent = sorted(planned - present)
    if absent:
        raise MigrationPlanError(
            f"plan names table(s) {absent} that this store does not have. The "
            f"plan is stale or misspelled, so it no longer describes the store "
            f"it is being applied to."
        )

    return tuple(dispositions[t] for t in sorted(present))


def tables_to_migrate(plan: Sequence[TablePlan]) -> tuple[str, ...]:
    """Just the table names to copy, in plan order."""
    return tuple(p.table for p in plan if p.migrates)


def exclusions(plan: Sequence[TablePlan]) -> tuple[TablePlan, ...]:
    """The excluded entries, so a caller can REPORT what it chose not to carry.

    Exposed rather than left implicit because a migration summary that lists
    only what it copied reads as complete. Naming the exclusions alongside the
    copies is what makes the omission auditable.
    """
    return tuple(p for p in plan if not p.migrates)


# EOF
