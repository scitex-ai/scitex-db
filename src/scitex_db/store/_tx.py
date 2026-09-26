#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Begin a write transaction that actually excludes other writers.

The two engines exclude writers by different mechanisms, and the
DEFAULT on each is the one that does not exclude anything yet:

* SQLite's plain ``BEGIN`` is DEFERRED. No lock is taken until the
  first write, so two writers both "begin" happily and one discovers
  the conflict later — at its first statement, or at COMMIT.
  ``BEGIN IMMEDIATE`` takes the reserved lock now, so the loser fails
  immediately and visibly instead of after doing work.
* PostgreSQL has no equivalent statement. Exclusion comes from
  ``pg_advisory_xact_lock(key)``, which blocks until the holder's
  transaction ends. It is released at COMMIT or ROLLBACK — not at
  statement end — which is what makes it a transaction-scoped mutex
  rather than a statement-scoped one.

**``lock_key`` is keyword-only with no default, deliberately.**
PostgreSQL needs one; SQLite does not. A default would let a caller who
never thought about lock scope inherit one chosen by this library, and
two subsystems sharing an accidental default key would serialise
against each other for no stated reason. Being made to name the key is
the point.

**Why the dialect is passed rather than detected.** Detecting it means
probing the connection, and a probe costs a failed statement plus a
rollback on PostgreSQL (see ``_backend``). Doing that immediately
before opening a write transaction is exactly the wrong moment. The
caller already knows — it opened the connection.

**Scope, measured rather than assumed.** scitex-cards recorded
(``cards-postgres-write-path-port-plan-20260731``, step D) that
``pg_advisory_xact_lock`` is a MULTI-HOST prerequisite, not a
single-host one: on their deployment ``flock`` is on the inode and both
HOME views reached ``ino 3417791``, so file-lock exclusion already held
across containers on one host. The advisory lock earns its keep when
writers live on different machines.

Note also that ``SERIALIZABLE`` is not a substitute. It aborts the
loser at commit time where an advisory lock blocks it at the start;
"retry your whole transaction" and "wait your turn" are different
contracts, and only one of them is safe to wrap around side effects.

stdlib only, by contract — see ``docs/portable-store-seam-surface.md``.
"""

from __future__ import annotations

from ._url import POSTGRESQL, SQLITE

__all__ = ["begin_write"]

#: SQLite: take the reserved lock NOW rather than at first write.
SQLITE_BEGIN = "BEGIN IMMEDIATE"

#: PostgreSQL: block until the holding transaction commits or rolls back.
POSTGRESQL_LOCK = "SELECT pg_advisory_xact_lock(%s)"


def begin_write(conn: object, *, lock_key: int, dialect: str) -> None:
    """Open a write transaction on ``conn`` that excludes other writers.

    ``lock_key`` is required even on SQLite, where it is unused: the
    caller must have decided what it is serialising, and a signature
    that lets them skip that decision on one backend hides it on the
    other.
    """
    if not isinstance(lock_key, int) or isinstance(lock_key, bool):
        raise TypeError(
            f"lock_key must be an int, got {lock_key!r}. PostgreSQL "
            "advisory locks are keyed by bigint; a string or bool here "
            "would either raise at the server or, worse, coerce."
        )

    if dialect == SQLITE:
        conn.execute(SQLITE_BEGIN)
        return

    if dialect == POSTGRESQL:
        cursor = conn.cursor()
        try:
            cursor.execute(POSTGRESQL_LOCK, (lock_key,))
        finally:
            try:
                cursor.close()
            except Exception:
                pass
        return

    raise ValueError(
        f"unknown dialect {dialect!r}; expected {SQLITE!r} or "
        f"{POSTGRESQL!r}. Refusing to guess: the two engines exclude "
        "writers by different mechanisms and neither default excludes "
        "anything."
    )


# EOF
