#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the CALLER must declare about a migration run.

Split out of ``_copy`` because these two types are the odd ones out there: pure
caller-supplied declarations with no behaviour of their own, sitting beside the
code that actually moves rows. They are also where this package's
"required-but-nullable, constructed-not-flagged" doctrine lives, and each one
carries a long docstring for the same reason -- it exists to make a caller STOP
AND DECIDE rather than accept a default.

What they have in common is the property that makes them necessary: each states
something the migration DEPENDS ON and CANNOT VERIFY FOR ITSELF. That is why
both record who said it. A claim the tool cannot check must be attributed, not
assumed.

Re-exported from ``._copy`` so existing imports keep working.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._refusal import MigrationRefused

__all__ = ["Quiescence", "StoreScope"]


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
class StoreScope:
    """The caller's statement of whether this DATABASE is the whole STORE.

    THIS EXISTS BECAUSE THE TOOL CANNOT ANSWER IT, and on 2026-07-30 it reported
    an answer anyway. A migration of the scitex-cards store copied 12 tables,
    verified every row, and reported success -- while 2,536 of 3,446 DM messages
    and 47 attachments sat in ``threads.json`` and ``attachments/`` NEXT TO the
    database. The copy was faithful. The claim "the entire store" was not, and
    both were said in the same sentence.

    The blind spot is structural rather than careless: :func:`._preflight.preflight`
    enumerates tables from ``sqlite_master``, so it cannot see a file beside the
    database. Every exclusion this package prints is a TABLE. There was no line
    it could emit that would have said "and three quarters of the DM history is
    in a JSON file next to this one."

    So the question is moved to whoever can answer it. ``database_is_whole_store``
    is a claim the caller makes and the marker records, exactly like
    :class:`Quiescence` -- a thing the migration depends on, cannot verify, and
    must therefore attribute rather than assume.

    ``outside_the_database`` NAMES what is not being carried when the answer is
    no. Required in that case, because "this is partial" without saying what is
    missing is a warning nobody can act on -- and because naming them is what
    turns a vague doubt into scitex-cards' next card.
    """

    database_is_whole_store: bool
    stated_by: str
    outside_the_database: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.stated_by.strip():
            raise MigrationRefused(
                "store scope claimed by nobody. Whether this database is the "
                "whole store is something the migration cannot check, so the "
                "marker records who said it."
            )
        if self.database_is_whole_store and self.outside_the_database:
            raise MigrationRefused(
                f"contradictory store scope: the database is claimed to be the "
                f"whole store, yet {list(self.outside_the_database)} are named "
                f"as living outside it. One of the two is wrong."
            )
        if not self.database_is_whole_store and not self.outside_the_database:
            raise MigrationRefused(
                "the database is claimed NOT to be the whole store, but "
                "nothing is named as living outside it. 'Partial' without "
                "saying what is missing is a warning nobody can act on -- name "
                "the files, directories or sidecar stores that are not being "
                "carried."
            )

    def summary(self) -> str:
        if self.database_is_whole_store:
            return (
                f"store scope: this database IS the whole store "
                f"(stated by {self.stated_by})"
            )
        return (
            f"store scope: PARTIAL -- this database is NOT the whole store "
            f"(stated by {self.stated_by}). NOT CARRIED BY THIS MIGRATION: "
            f"{', '.join(self.outside_the_database)}"
        )

# EOF
