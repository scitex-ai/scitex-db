#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ready-made checks for the shared scitex-cards store.

WHY A BINDING MODULE RATHER THAN LETTING CALLERS ASSEMBLE CHECKS: the generic
types in this package are correct but unopinionated, and the interesting
knowledge is WHICH artifact answers WHICH question for a particular store. That
knowledge is store-specific and belongs somewhere a second caller can find it,
rather than being re-derived. ``_migrate._plan`` already carries
``CARDS_STORE_DISPOSITIONS`` for the same reason.

IMPORTS ARE DEFERRED AND OPTIONAL. ``scitex_cards`` is not a dependency of this
package and must not become one -- scitex-db is imported by tooling that has no
reason to install the card store. Every binding here takes its probe as a
callable, or resolves it lazily and reports UNKNOWN if the package is absent.
An absent package is not evidence about a store.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from ._checks import ArtifactProbe, Check, PositiveControl

#: The rung scitex-cards ruled on 2026-08-10 for the row-level write path.
#: Name and version are THEIR contract; this module only consumes it.
#: A trigger, not a column and not a stamp -- see the package docstring.
ROW_LEVEL_WRITE_ARTIFACT = "tasks_row_level_write"
ROW_LEVEL_WRITE_SCHEMA_VERSION = 10


def _resolve_has_trigger() -> Callable[[Any, str], bool]:
    """Return scitex-cards' own trigger probe, or raise if it is unavailable.

    Deliberately NOT caught here: the caller wraps this in an
    :class:`~scitex_db._schema_change._checks.ArtifactProbe`, whose contract is
    that a probe which cannot run yields UNKNOWN rather than FAIL. Swallowing
    the ImportError here would turn "I cannot tell" into "it is absent", which
    is the error this whole package exists to make unavailable.
    """
    from scitex_cards._schema_probe import has_trigger  # noqa: PLC0415 - optional dep

    return has_trigger


def row_level_write_landed(
    has_trigger: Callable[[Any, str], bool] | None = None,
) -> ArtifactProbe:
    """Has scitex-cards' row-level write path landed on this store?

    Returns FAIL (an honest "not landed") until the flip installs the trigger,
    and PASS the moment it does, because installing the artifact IS the flip.
    It cannot go green early and it cannot drift.

    Parameters
    ----------
    has_trigger
        Injected for testing. Defaults to scitex-cards' own
        ``_schema_probe.has_trigger``, resolved lazily so this module imports
        cleanly without the card store installed.

    Notes
    -----
    Do NOT be tempted to check ``tasks.revision`` or any other column instead.
    ``revision`` has existed since schema v6 and says nothing about which write
    path is live; a gate keyed on it reported READY four minutes after being
    written, for a migration whose precondition had not been started. The typed
    columns are additionally dual-written on every write today, so no probe over
    column state can distinguish pre-flip from post-flip on this store.
    """
    probe = has_trigger

    def exists(conn: Any) -> bool:
        fn = probe if probe is not None else _resolve_has_trigger()
        return bool(fn(conn, ROW_LEVEL_WRITE_ARTIFACT))

    return ArtifactProbe(
        name=f"row-level write path landed (rung {ROW_LEVEL_WRITE_ARTIFACT})",
        artifact=ROW_LEVEL_WRITE_ARTIFACT,
        exists=exists,
    )


def tasks_are_readable(
    fetch_one_int: Callable[[Any, str], int],
) -> PositiveControl:
    """Prove the instrument reaches live card data before trusting any zero.

    ``tasks`` is never empty on a real store -- it held 3569 rows when this was
    written -- so a zero here means the query is not reaching the data, not that
    the store is clean. Without this control every other zero in the run is
    uninformative.
    """
    return PositiveControl(
        name="instrument reaches live card data",
        query="SELECT count(*) FROM tasks",
        fetch_one_int=fetch_one_int,
    )


def v10_rung_checks(
    fetch_one_int: Callable[[Any, str], int],
    has_trigger: Callable[[Any, str], bool] | None = None,
) -> Sequence[Check]:
    """The set scitex-cards asked for: is this store ready for the v10 rung?

    Ordered control-first so a reader of the report meets the instrument's own
    verdict before any finding that depends on it.
    """
    return (
        tasks_are_readable(fetch_one_int),
        row_level_write_landed(has_trigger),
    )
