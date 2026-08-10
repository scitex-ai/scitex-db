#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How long does one statement hold its lock?

NOT PART OF :func:`~scitex_db._schema_change._preflight.preflight`, and the
separation is the safety property. ``preflight`` accepts no DDL and therefore
cannot write; this module EXECUTES the statement in order to time it. Putting
them behind one entry point with a flag is exactly the shape ``_migrate``
refused ("a dry_run=False default makes the destructive path the one you get by
forgetting an argument"), so they are different functions with different names.

WHAT A CALLER ACTUALLY NEEDS, and why a total-migration figure does not answer
it. The measured cost of the whole tenant migration was 2.2s of held-lock work
on 3497 tasks / 7651 comments. That is a BUDGET -- useful for deciding whether a
change is affordable at all. It is not what you size a quiesce against, because
a quiesce has to cover the LONGEST SINGLE STATEMENT, not the sum. ~90 agent
containers call ``init_schema`` on every ``open_db``; each one blocks for the
duration of whichever statement is holding ACCESS EXCLUSIVE when it arrives.

THIS TAKES THE REAL LOCK. There is no simulation. ``CREATE TRIGGER`` and
``ALTER TABLE`` acquire ACCESS EXCLUSIVE on PostgreSQL, which blocks every
reader and writer of that table for the duration -- including the board every
agent is looking at. The transaction is rolled back, so nothing persists, but
THE FREEZE IS REAL WHILE IT RUNS. Run it against a scratch copy unless you
intend to freeze production, and :func:`measure_lock_cost` refuses by default on
anything it cannot confirm is scratch.

WHY ROLLBACK IS NOT ENOUGH ON ITS OWN: a rolled-back DDL still held the lock for
its full duration. "Nothing was written" and "nothing was disrupted" are
different claims, and only the first is true here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class LockCost:
    """One statement's measured lock-held window.

    ``seconds`` is wall-clock around the statement's execution inside an open
    transaction -- i.e. the window during which other sessions wanting the same
    table were blocked. It is deliberately NOT the transaction's total lifetime,
    which includes the caller's own bookkeeping and would overstate the freeze.

    ``rolled_back`` records that the change did not persist. It does NOT mean
    the store was undisturbed; see the module docstring.
    """

    statement: str
    seconds: float
    rolled_back: bool

    def summary(self) -> str:
        persisted = "rolled back" if self.rolled_back else "COMMITTED"
        head = self.statement.strip().splitlines()[0][:60]
        return f"{self.seconds:.4f}s lock held ({persisted}) - {head}"


class RefusedToLockLiveStore(RuntimeError):
    """Raised rather than freezing a store the caller did not vouch for.

    An exported TYPE, not a message match: callers catch the refusal by type,
    and adding a second refusal reason later cannot break their except clause.
    """


def measure_lock_cost(
    conn: Any,
    statement: str,
    *,
    scratch: bool,
    execute: Callable[[Any, str], None] | None = None,
    begin: Callable[[Any], None] | None = None,
    rollback: Callable[[Any], None] | None = None,
) -> LockCost:
    """Time how long ``statement`` holds its lock. Rolls back; never commits.

    Parameters
    ----------
    conn
        A connection with an idle transaction state.
    statement
        One DDL statement. Pass them ONE AT A TIME: a caller sizing a quiesce
        needs the longest single window, and a batch would report their sum.
    scratch
        The caller's explicit assertion that this connection points at a store
        it is acceptable to freeze. There is NO default. ``scratch=False``
        raises :class:`RefusedToLockLiveStore` rather than proceeding, because
        the lock is taken even though the write is rolled back, and a keyword
        that could be forgotten would make the disruptive path the accidental
        one.
    execute, begin, rollback
        Injected for testing. Default to the DB-API operations on ``conn``.

    Raises
    ------
    RefusedToLockLiveStore
        When ``scratch`` is False.

    Notes
    -----
    A statement that RAISES is still timed and the timing is discarded -- a
    failed statement's lock window says nothing about the successful one's, and
    reporting it would be a number that looks like an answer.
    """
    if not scratch:
        raise RefusedToLockLiveStore(
            "measure_lock_cost takes a REAL lock (ACCESS EXCLUSIVE for DDL on "
            "PostgreSQL) and blocks every reader and writer of the table while "
            "it runs, even though the transaction is rolled back. Pass "
            "scratch=True only for a store you are willing to freeze -- "
            "typically a copy. To size a production window, measure on the copy "
            "and apply the result there."
        )

    _execute = execute or (lambda c, sql: c.execute(sql))
    _begin = begin or (lambda c: c.execute("BEGIN"))
    _rollback = rollback or (lambda c: c.execute("ROLLBACK"))

    _begin(conn)
    started = time.monotonic()
    try:
        _execute(conn, statement)
    finally:
        elapsed = time.monotonic() - started
        _rollback(conn)

    return LockCost(statement=statement, seconds=elapsed, rolled_back=True)
