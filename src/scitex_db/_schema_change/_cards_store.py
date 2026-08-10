#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ready-made checks for the shared scitex-cards store.

WHY A BINDING MODULE RATHER THAN LETTING CALLERS ASSEMBLE CHECKS: the generic
types in this package are correct but unopinionated, and the interesting
knowledge is WHICH artifact answers WHICH question for a particular store. That
knowledge is store-specific and belongs somewhere a second caller can find it,
rather than being re-derived. ``_migrate._plan`` already carries
``CARDS_STORE_DISPOSITIONS`` for the same reason.

THIS MODULE NEVER IMPORTS scitex_cards, not even lazily. It is not a dependency
of this package and must not become one -- scitex-db is imported by tooling that
has no reason to install the card store.

An earlier version resolved the probe with a deferred import and called that
"optional". The PS-140 cross-package auditor rejected it and was right: a lazy
import IS a dependency, it just fails later, in a user's process, which is
precisely the failure PS-140 exists to catch (the ``scitex_io._load_cache``
rename went undetected for weeks exactly that way). The docstring claimed one
thing while the source did another, and the auditor could see the source.

So every binding takes its probe as a REQUIRED callable. The import lives in the
caller, which already depends on the card store. If a caller cannot supply one,
that is a decision it makes explicitly rather than a failure this package
discovers at runtime.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from ._checks import ArtifactProbe, Check, PositiveControl

#: The rung scitex-cards ruled on 2026-08-10 for the row-level write path.
#: Name and version are THEIR contract; this module only consumes it.
#: A trigger, not a column and not a stamp -- see the package docstring.
ROW_LEVEL_WRITE_ARTIFACT = "tasks_row_level_write"
ROW_LEVEL_WRITE_SCHEMA_VERSION = 10


#: How a caller obtains the probe this module needs. NOT imported here.
#:
#: The PS-140 cross-package auditor caught the earlier version of this module
#: importing ``scitex_cards._schema_probe`` lazily, and it was right to: the
#: docstring claimed scitex_cards was not a dependency while the source named
#: it. A lazy import is still a dependency -- it just fails later, in a user's
#: process, which is the exact failure PS-140 exists to prevent (the
#: ``scitex_io._load_cache`` rename went undetected for weeks that way).
#:
#: So the probe is now ALWAYS injected and this package never names the card
#: store. The caller writes:
#:
#:     from scitex_cards._schema_probe import has_trigger
#:     checks = v10_rung_checks(fetch_one_int, has_trigger)
#:
#: which puts the import in the process that already depends on it.
PROBE_IS_INJECTED = (
    "pass has_trigger=scitex_cards._schema_probe.has_trigger from the caller"
)


def row_level_write_landed(
    has_trigger: Callable[[Any, str], bool],
) -> ArtifactProbe:
    """Has scitex-cards' row-level write path landed on this store?

    Returns FAIL (an honest "not landed") until the flip installs the trigger,
    and PASS the moment it does, because installing the artifact IS the flip.
    It cannot go green early and it cannot drift.

    Parameters
    ----------
    has_trigger
        REQUIRED. ``scitex_cards._schema_probe.has_trigger`` or equivalent.
        There is no default and no lazy import: this package must not name the
        card store (see :data:`PROBE_IS_INJECTED`).

    Notes
    -----
    Do NOT be tempted to check ``tasks.revision`` or any other column instead.
    ``revision`` has existed since schema v6 and says nothing about which write
    path is live; a gate keyed on it reported READY four minutes after being
    written, for a migration whose precondition had not been started. The typed
    columns are additionally dual-written on every write today, so no probe over
    column state can distinguish pre-flip from post-flip on this store.
    """
    def exists(conn: Any) -> bool:
        return bool(has_trigger(conn, ROW_LEVEL_WRITE_ARTIFACT))

    return ArtifactProbe(
        name=f"row-level write path landed (rung {ROW_LEVEL_WRITE_ARTIFACT})",
        artifact=ROW_LEVEL_WRITE_ARTIFACT,
        exists=exists,
    )


def tasks_are_readable(
    fetch_one_int: Callable[[Any, str], int],
) -> PositiveControl:
    """Prove the connection reaches live card data.

    ``tasks`` is never empty on a real store -- it held 3608 rows when this was
    written -- so a zero here means the query is not reaching the data.

    NOT SUFFICIENT ON ITS OWN, and the reason is the point of
    :func:`catalogue_is_visible`: this control exercises a TABLE read while the
    verdict comes from a CATALOGUE read. It rules out failures of the mechanism
    the verdict does not use. Keep it because it gives a sharper message when
    the connection itself is the problem, not because it makes the verdict
    trustworthy.
    """
    return PositiveControl(
        name="connection reaches live card data",
        query="SELECT count(*) FROM tasks",
        fetch_one_int=fetch_one_int,
    )


#: The v7 rung. An AFTER UPDATE trigger on ``tasks``, installed by
#: ``_db_migrations.py:107-113`` and hand-ported to PostgreSQL at
#: ``_pg_triggers.py:140-151``. Present on EVERY v9 store, which is what makes
#: it usable as a control.
KNOWN_PRESENT_ARTIFACT = "tasks_bump_revision"


def catalogue_is_visible(
    has_trigger: Callable[[Any, str], bool],
) -> PositiveControl:
    """Prove THIS probe can see an artifact that is known to be there.

    WHY THIS EXISTS, and it is scitex-cards' correction rather than my design.
    The verdict of :func:`row_level_write_landed` comes from a CATALOGUE read
    (``pg_trigger`` / ``sqlite_master``). A table-row control cannot vouch for
    it, because the failure that matters produces a FALSE from the catalogue:

        broken catalogue read / wrong search_path / wrong database
          -> has_trigger returns False
          -> report says "artifact absent"
          -> which is EXACTLY what it says on an honest pre-flip store

    A dead catalogue read and a genuine NOT LANDED are byte-identical in the
    output. This control removes that ambiguity by asking the SAME helper, on
    the SAME table, through the SAME catalogue, for an artifact that must
    already exist. If it answers False, the probe is lying and the run says so
    before publishing a verdict.

    That is the difference between "the connection works" and "an artifact I
    know exists is visible to this exact probe" -- and only the second supports
    the claim the report makes.
    """
    def count(conn: Any, _query: str) -> int:
        return 1 if has_trigger(conn, KNOWN_PRESENT_ARTIFACT) else 0

    # The name is the failure message. When this control fails, the report must
    # not read as though the RUNG failed -- it is a statement about the store
    # being an unexpected shape, or the probe being blind. scitex-cards raised
    # this: the control degrades with the check, and if tasks_bump_revision is
    # ever dropped or renamed this goes FAIL for a reason unrelated to the rung.
    # That is the correct direction to fail in (loud and wrong-looking, so it
    # gets investigated) but only if the wording sends the reader to the right
    # place.
    return PositiveControl(
        name=(
            f"control artifact {KNOWN_PRESENT_ARTIFACT!r} visible to this probe "
            "(if this fails, the store is not the shape this instrument expects "
            "-- it is NOT a verdict about the rung)"
        ),
        query=f"has_trigger({KNOWN_PRESENT_ARTIFACT})",
        fetch_one_int=count,
    )


def v10_rung_checks(
    fetch_one_int: Callable[[Any, str], int],
    has_trigger: Callable[[Any, str], bool],
) -> Sequence[Check]:
    """The set scitex-cards asked for: is this store ready for the v10 rung?

    Controls first, so a reader meets the instrument's own verdict before any
    finding that rests on it. BOTH controls run: the table read localises a
    dead connection, the catalogue read is what makes the FAIL trustworthy.
    """
    return (
        tasks_are_readable(fetch_one_int),
        catalogue_is_visible(has_trigger),
        row_level_write_landed(has_trigger),
    )
