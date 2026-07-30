#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the copy, and refuse to call it finished until it is verified.

TWO ORDERING RULES CARRY THE SAFETY, and they are the whole reason this is a
module rather than a loop:

1. THE COMPLETION MARKER IS WRITTEN LAST -- after every row has moved and after
   verification has passed. An absent marker means the destination is UNUSABLE,
   never "probably fine". Without this, a copy interrupted at 80% leaves a
   database that an adapter would happily connect to and serve: a store missing
   a fifth of its cards, with nothing anywhere reporting a problem. That is the
   same defect as an implicit fallback to the wrong backend, one layer out --
   scitex-cards' rule for the transport side, applied to the migration.

2. VERIFICATION RUNS BEFORE THE MARKER, not after. If the marker were written
   first and verification merely reported afterwards, a failed verification
   would leave a destination that claims to be complete. The marker is the
   assertion "this was checked", so it must not exist until the check passed.

QUIESCENCE IS REQUIRED AND NOT DETECTED. The migration refuses to run unless the
caller states that writers are stopped, and this argument has no default.
scitex-cards ruled on this (2026-07-30) and the reasoning is worth repeating,
because the obvious implementation is a trap: "check whether anything wrote
recently" is a heuristic that passes exactly when it is least safe. They measured
15.5 row-deltas/minute of ordinary traffic on the live store, so a quiet thirty
seconds proves nothing while a busy one proves only that somebody wrote. Such a
check is not weak, it is misleading, so it is deliberately absent here.

The reason quiescence matters at all is subtler than "avoid losing late writes",
and it is scitex-cards' finding: their optimistic lock is
``UPDATE ... WHERE id=? AND revision=?``. Carrying ``revision`` across the
migration verbatim makes that lock FUNCTION on the destination -- but it does not
make it MEAN anything. A writer that read ``revision=5`` from SQLite and writes
to PostgreSQL after cutover finds 5 there and succeeds, while any write that
landed in SQLite after the copy point is silently gone. The lock's premise is
"nothing changed under me since I read", and a store swap violates that premise
in a way a version number cannot express. Only quiescence restores it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from ._plan import TablePlan, exclusions, tables_to_migrate
from ._verify import MigrationVerificationError, VerificationReport, verify_table

__all__ = [
    "MARKER_TABLE",
    "MigrationRefused",
    "Quiescence",
    "MigrationResult",
    "apply_schema_objects",
    "destination_is_usable",
    "read_marker",
]

#: The destination table holding the completion marker. Named so that its
#: absence is legible to a human inspecting the database by hand, not only to
#: this package.
MARKER_TABLE = "scitex_migration_complete"


class MigrationRefused(Exception):
    """Raised when the migration will not start, or will not be marked done."""


@dataclass(frozen=True)
class Quiescence:
    """The caller's statement that no writer can touch the source.

    Deliberately a required object rather than a boolean flag with a default.
    A defaulted ``quiesced: bool = False`` invites ``quiesced=True`` typed
    without thought at a call site; a value that must be constructed, and that
    demands a stated mechanism, does not.

    ``mechanism`` names HOW writes are stopped, and is recorded in the
    completion marker. Two forms exist today:

    * ``"store-mode"`` -- scitex-cards' write path refuses while a store-level
      mode is set. This is the durable answer, and it is only honoured by
      processes running a version that HAS the gate; scitex-cards measured
      agents resident on older versions, so it is necessary and not yet
      sufficient.
    * ``"operator"`` -- the operator has stopped the fleet by hand. This is the
      real mechanism for the FIRST migration, and saying so in the marker is
      better than implying a guarantee the code did not provide.
    """

    mechanism: str
    stated_by: str

    def __post_init__(self) -> None:
        if not self.mechanism.strip():
            raise MigrationRefused(
                "quiescence claimed with no mechanism named. Recording HOW "
                "writes were stopped is the difference between an audit trail "
                "and an assertion; if the answer is 'the operator stopped the "
                "fleet', say `operator` rather than leaving it blank."
            )
        if not self.stated_by.strip():
            raise MigrationRefused(
                "quiescence claimed by nobody. The marker records who "
                "asserted it, because this claim is the one thing the "
                "migration cannot verify for itself."
            )


@dataclass(frozen=True)
class MigrationResult:
    """What the migration did, including what it deliberately did not carry."""

    reports: tuple[VerificationReport, ...]
    excluded: tuple[TablePlan, ...]
    marked_complete: bool

    @property
    def ok(self) -> bool:
        return self.marked_complete and all(r.ok for r in self.reports)

    def summary(self) -> str:
        """Every table's verdict, then the exclusions, then the marker state.

        Exclusions are printed even when there is nothing wrong. A summary that
        lists only what it copied reads as complete, and this migration
        deliberately leaves three tables behind -- that omission has to be
        visible in the same place as the successes, or the next reader will
        assume the destination is a full copy.
        """
        lines = [r.summary() for r in self.reports]
        for plan in self.excluded:
            lines.append(f"{plan.table}: NOT MIGRATED -- {plan.reason}")
        lines.append(
            "marker: written (destination usable)"
            if self.marked_complete
            else "marker: ABSENT (destination NOT usable)"
        )
        return "\n".join(lines)


def read_marker(fetch: Callable[[str], Iterable[Sequence[Any]]]) -> dict | None:
    """The completion marker's payload, or ``None`` if there is none.

    ``fetch`` runs a SQL string against the destination and yields rows; it is
    passed in rather than a connection so this works against any DB-API driver
    without this module choosing one.

    A missing marker table and an empty marker table are both ``None``: neither
    means "complete", and collapsing them here keeps every caller from having
    to remember that a fresh destination has no marker table at all.
    """
    try:
        rows = list(fetch(f'SELECT payload FROM "{MARKER_TABLE}"'))
    except Exception:
        # Any failure to read the marker -- absent table, permission, driver --
        # is treated as "not marked". Guessing optimistically here would defeat
        # the entire purpose of the marker.
        return None
    if not rows:
        return None
    raw = rows[0][0]
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # A marker we cannot parse is not a marker we can trust.
        return None


def destination_is_usable(fetch: Callable[[str], Iterable[Sequence[Any]]]) -> bool:
    """Whether the destination carries a valid completion marker.

    This is the gate an adapter must consult before serving from a migrated
    database. It answers false for a fresh database, a half-copied one, and one
    whose migration failed verification -- all three of which are states where
    connecting and serving would look like success.
    """
    return read_marker(fetch) is not None


def apply_schema_objects(
    objects: Sequence[Any],
    write: Callable[[str, Sequence[Any]], None],
) -> tuple[str, ...]:
    """Create the translated triggers and indexes on the destination.

    ORDER IS LOAD-BEARING AND IS NOT THE SOURCE'S ORDER. Indexes are created
    before triggers, and BOTH are created after the rows have been copied:

    * After the rows, because building an index once over a populated table is
      far cheaper than maintaining it across every insert -- and because a
      guard trigger meant for normal operation has no business adjudicating
      the migration's own writes. A ``BEFORE UPDATE`` immutability guard
      installed early would be evaluating the copier, not the application.
    * Indexes before triggers so that if a trigger body references an index by
      name, the reference resolves.

    Returns the names applied, in order, so the caller can report what it did
    rather than assert that it did something. Nothing is swallowed: a failure
    here propagates, because a destination with some of its triggers is more
    dangerous than one with none -- the missing ones are invisible while the
    present ones make it look protected.
    """
    from ._triggers import translate_schema_object

    applied = []
    ordered = sorted(objects, key=lambda o: (o.kind != "index", o.name))
    for obj in ordered:
        write(translate_schema_object(obj), ())
        applied.append(obj.name)
    return tuple(applied)


def verify_plan(
    plan: Sequence[TablePlan],
    read_source: Callable[[str], Iterable[Mapping[str, Any]]],
    read_destination: Callable[[str], Iterable[Mapping[str, Any]]],
    *,
    key_columns: Mapping[str, Sequence[str]],
    columns: Mapping[str, Sequence[str]],
    empty_tables: Sequence[str] = (),
) -> tuple[VerificationReport, ...]:
    """Verify every migrated table, returning one report per table.

    Raises :class:`MigrationVerificationError` if any table has no key or column
    specification. A table silently skipped for lack of a spec would be an
    unverified table inside a migration that reported success -- the same class
    of hole as a skipped copy.
    """
    reports = []
    for table in tables_to_migrate(plan):
        if table not in key_columns:
            raise MigrationVerificationError(
                f"{table}: no key columns specified, so this table cannot be "
                f"verified. Skipping it would leave it unverified inside a "
                f"migration that reported success."
            )
        if table not in columns:
            raise MigrationVerificationError(
                f"{table}: no comparison columns specified, so this table "
                f"cannot be verified."
            )
        reports.append(
            verify_table(
                table,
                read_source(table),
                read_destination(table),
                key_columns=key_columns[table],
                columns=columns[table],
                allow_empty=table in empty_tables,
            )
        )
    return tuple(reports)


def finalize(
    plan: Sequence[TablePlan],
    reports: Sequence[VerificationReport],
    quiescence: Quiescence,
    write: Callable[[str, Sequence[Any]], None],
    *,
    source_identity: str,
    completed_at: str,
    store_identity: str | None,
    placeholder: str = "?",
    transformations: Any = None,
) -> MigrationResult:
    """Write the completion marker -- ONLY if every report is clean.

    ``completed_at`` is supplied by the caller rather than read from the clock
    here, so the marker a test writes is deterministic and the timestamp comes
    from whoever actually knows what run this was.

    ``store_identity`` IS WHAT LETS A READER ASK "IS THIS *THE* STORE", rather
    than only "is this *a* complete store". Those are different questions and
    only the second was answerable before. A canonical-store guard needs the
    first, and it cannot key on the ADDRESS used to reach a database: the same
    file is reachable by more than one spelling, measured on scitex-cards' live
    store where ``schema_meta.store_path`` says ``/home/agent/...`` while this
    package reaches the identical inode as ``/home/ywatanabe/...``. Both are
    correct; neither is an identity. scitex-cards keys theirs on a ``store_uuid``
    held INSIDE the store, and that is the value this carries across.

    IDENTITY IS NECESSARY AND NOT SUFFICIENT, which is worth stating here
    because this field alone invites the opposite conclusion. After a verified
    copy there are TWO stores carrying the same identity -- the source and the
    destination -- both complete, both legitimately that workspace's store. What
    distinguishes them is a statement of which is CURRENT, and moving that
    statement is what a cutover actually is. That statement lives in the source
    (scitex-cards' ``store_status`` / ``retired_in_favour_of``), not here: this
    marker can say what the destination IS, never that it is the one to use.

    Keyword-only with NO DEFAULT, and may be ``None``. Required-but-nullable so
    a caller must DECIDE rather than forget; ``None`` is the explicit claim
    "this store declares no identity", which a generic store may legitimately
    be. It is recorded as an explicit null rather than by omitting the key,
    because an absent key is ambiguous -- older marker format, erased, or never
    set -- while an explicit null is a fact. This package argues that about
    other people's data often enough that it should hold in its own payload.

    ``placeholder`` is the destination driver's parameter marker: ``"?"`` for
    sqlite3, ``"%s"`` for psycopg2. It is a parameter rather than a hardcoded
    ``"?"`` because the destination of this migration is PostgreSQL, where
    ``?`` is a syntax error -- so hardcoding sqlite3's marker would have made
    the marker write, and therefore every real migration, fail at its final
    step. Found by probing the actual driver rather than by reading the code.

    Raises :class:`MigrationRefused` if any table failed verification, naming
    the tables. The destination is left unmarked and therefore unusable, which
    is the correct outcome: a destination that failed verification must not be
    servable, and an operator who sees no marker knows to investigate rather
    than to trust.
    """
    failed = [r.table for r in reports if not r.ok]
    if failed:
        raise MigrationRefused(
            f"refusing to mark the migration complete: {len(failed)} table(s) "
            f"failed verification ({', '.join(failed)}). The destination is "
            f"left WITHOUT a completion marker, so it will not be treated as "
            f"usable. Details:\n"
            + "\n".join(r.summary() for r in reports if not r.ok)
        )

    payload = {
        "source": source_identity,
        "store_identity": store_identity,
        "completed_at": completed_at,
        "quiescence": {
            "mechanism": quiescence.mechanism,
            "stated_by": quiescence.stated_by,
        },
        "tables": {r.table: r.rows_compared for r in reports},
        "excluded": {p.table: p.reason for p in exclusions(plan)},
        # The manifest of every value this migration changed, with the original
        # bytes as hex. Recorded as an explicit empty list when nothing was
        # transformed, rather than by omitting the key: an absent key is
        # ambiguous (old marker format? nothing declared? not recorded?), while
        # an empty list is the fact "this destination is byte-identical".
        "transformations": (
            transformations.manifest() if transformations is not None else []
        ),
        "transformations_stated_by": (
            transformations.stated_by if transformations is not None else None
        ),
    }
    write(
        f'CREATE TABLE IF NOT EXISTS "{MARKER_TABLE}" (payload TEXT NOT NULL)',
        (),
    )
    write(
        f'INSERT INTO "{MARKER_TABLE}" (payload) VALUES ({placeholder})',
        (json.dumps(payload),),
    )
    return MigrationResult(
        reports=tuple(reports),
        excluded=exclusions(plan),
        marked_complete=True,
    )


# EOF
