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
# Re-exported below rather than moved out of the public surface: `from ._copy
# import Quiescence` appears in tests and in callers outside this repo, and a
# migration's public surface should not churn for an internal file split.
from ._provenance import Quiescence, StoreScope
from ._refusal import MigrationRefused
from ._verify import MigrationVerificationError, VerificationReport, verify_table

__all__ = [
    "MARKER_TABLE",
    "MigrationRefused",
    "Quiescence",
    "MigrationResult",
    "StoreScope",
    "apply_schema_objects",
    "destination_is_usable",
    "destination_is_whole_store",
    "read_marker",
]

#: The destination table holding the completion marker. Named so that its
#: absence is legible to a human inspecting the database by hand, not only to
#: this package.
MARKER_TABLE = "scitex_migration_complete"



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


def destination_is_whole_store(fetch: Callable[[str], Iterable[Sequence[Any]]]) -> bool:
    """Whether the copied database was the WHOLE store, per the run's marker.

    A SECOND question, deliberately not folded into
    :func:`destination_is_usable`. That one answers "was this migration
    completed and verified"; this one answers "is this everything". Both were
    true of the same destination on 2026-07-30 while 2,536 DM messages sat in a
    file beside the source, and the reason nobody noticed is that only the first
    question was ever asked.

    A cutover must consult BOTH. Serving from a verified-but-partial copy is
    precisely the failure that a completion marker looks like it prevents.

    Returns False for an absent or unparseable marker, and False for a marker
    written before this field existed -- "I could not tell" is not "yes".
    """
    marker = read_marker(fetch)
    if marker is None:
        return False
    return marker.get("database_is_whole_store") is True


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
    predecessor_identity: str | None,
    store_scope: "StoreScope",
    declined_objects: Any = (),
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

    THE DESTINATION MUST GET A **NEW** IDENTITY, AND THIS PARAGRAPH USED TO SAY
    THE OPPOSITE. It read: "after a verified copy there are TWO stores carrying
    the same identity ... what distinguishes them is a statement of which is
    CURRENT". The second half is still true. The first half shipped a twin, and
    the twin broke the very guard identity exists for.

    Measured on the live cutover, 2026-07-31:

        retired SQLite   store_uuid            = 0bb1395b-...
                         retired_in_favour_of  = 0bb1395b-...   <- itself
        PostgreSQL       store_uuid            = 0bb1395b-...   <- twin

    ``retired_in_favour_of`` is a uuid-shaped POINTER, so against twins it names
    both stores and identifies neither, and ``expected_uuid`` -- whose entire job
    is answering "am I on the right store?" -- passes on the RETIRED one. A gate
    that cannot fail.

    The old paragraph conflated two questions that only look alike:

        which WORKSPACE is this?   answered by carrying the identity forward
        which STORE is this?       answered only by them being DIFFERENT

    A cutover needs the second. So the destination is a NEW store that RECORDS
    its predecessor, and the workspace question is answered by walking that
    lineage backward -- the direction that still works once the source is
    retired and the forward pointer is the thing under test.

    ``predecessor_identity`` carries that link, on the SUCCESSOR. Keeping it here
    rather than only in the source's ``retired_in_favour_of`` is deliberate: the
    source may never be retired at all (this run was reversed), and a lineage
    that exists only in the store you are moving away from is not lineage.

    PASSING THE SOURCE'S OWN IDENTITY IS REFUSED. It is the one value that is
    always wrong and the one most likely to be passed, because it is the value
    sitting in front of the caller -- which is exactly how it was passed here.
    Requiring a decision was not enough; a required question can still be
    answered wrong, so the answer that is always wrong is now rejected by name.

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
    # Refused BEFORE the verification check, because this is a defect in what the
    # caller ASKED FOR rather than in what the copy achieved -- and a clean run
    # must not be able to talk you past it.
    if (
        store_identity is not None
        and predecessor_identity is not None
        and store_identity == predecessor_identity
    ):
        raise MigrationRefused(
            f"refusing to mark the migration complete: store_identity and "
            f"predecessor_identity are both {store_identity!r}, so the "
            f"destination would be an identity TWIN of its source. Nothing "
            f"could then tell the two apart -- a uuid-shaped 'retired in favour "
            f"of' pointer names both and identifies neither, and an 'am I on "
            f"the right store?' check passes against the RETIRED one. Mint a "
            f"NEW identity for the destination and pass the source's here; the "
            f"lineage is what preserves the link, not the sameness. Measured on "
            f"the live scitex-cards cutover, where this exact value was passed "
            f"because it was the one sitting in front of the caller."
        )

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
        # Lineage, recorded on the SUCCESSOR and pointing BACKWARD. The forward
        # pointer (`retired_in_favour_of` in the source) is the one that breaks:
        # it only exists if the source is ever retired, and this run was
        # reversed. A lineage that lives only in the store you are moving away
        # from is not lineage.
        "predecessor_identity": predecessor_identity,
        "completed_at": completed_at,
        "quiescence": {
            "mechanism": quiescence.mechanism,
            "stated_by": quiescence.stated_by,
        },
        # Whether this database was the whole store. Recorded because
        # `destination_is_usable` answers "was this migration completed and
        # verified", which is NOT the same question as "is this everything" --
        # and collapsing the two is exactly how 2,536 messages nearly went
        # missing behind a green report.
        "database_is_whole_store": store_scope.database_is_whole_store,
        "outside_the_database": list(store_scope.outside_the_database),
        "store_scope_stated_by": store_scope.stated_by,
        # Objects the caller DECLINED, with reasons. Recorded so the
        # destination carries its own account of what was deliberately not
        # translated -- an absent trigger with no explanation is
        # indistinguishable from one that was lost.
        "declined_objects": [
            {"name": o.name, "kind": o.kind, "table": o.table, "reason": r}
            for o, r in (declined_objects or ())
        ],
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
