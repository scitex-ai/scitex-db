#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Report which engine is actually live, or say it does not know.

The hazard: a health check that asserts the literal string "SQLite"
reports the wrong engine on every PostgreSQL deployment *while passing*.
It is a report about the code's assumption, not about the running
system, and it is green either way. scitex-cards' migration produced
twelve defects of which nine raised nothing at all; "reported a version
string that matched" was one of the shapes.

So this module interrogates the LIVE CONNECTION rather than trusting a
config value, a type name, or a constant. The engine answers for
itself.

Three-valued by contract: ``dialect=None`` means UNKNOWN. It is never
filled in by inference. An unidentifiable connection must read as
unknown, because "probably SQLite" is exactly the assumption that
survives a backend port and then quietly lies.

**Probing PostgreSQL costs a rollback.** A failed statement aborts the
current transaction on PostgreSQL — every subsequent statement then
fails with ``current transaction is aborted`` until rollback. So a
SQLite probe run against a PostgreSQL connection does not merely fail;
without cleanup it *poisons the caller's connection*. Every failed
probe here is followed by a rollback attempt for that reason. A
diagnostic that breaks the thing it is diagnosing is worse than no
diagnostic.

stdlib only, by contract — see ``docs/portable-store-seam-surface.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._url import POSTGRESQL, SQLITE, StoreLocation

__all__ = ["BackendReport", "describe_backend"]


@dataclass(frozen=True)
class BackendReport:
    """What engine is live, what version, and what selected it.

    Every field is three-valued: a real value, or ``None`` meaning
    UNKNOWN. None is never a stand-in for a default.
    """

    dialect: str | None = None
    server_version: str | None = None
    config_source: str | None = None

    def __post_init__(self) -> None:
        if self.dialect is not None and self.dialect not in (
            SQLITE,
            POSTGRESQL,
        ):
            raise ValueError(
                f"unknown dialect {self.dialect!r}; expected "
                f"{SQLITE!r}, {POSTGRESQL!r}, or None for unknown"
            )
        if self.dialect is None and self.server_version is not None:
            raise ValueError(
                "server_version cannot be known while dialect is unknown "
                f"(got {self.server_version!r}); reporting a version for an "
                "unidentified engine is the guess this type exists to refuse"
            )


# (dialect, probe) pairs. Each probe answers ONLY on its own engine, so
# the engine identifies itself instead of being inferred from a driver
# module name -- a wrapped or proxied connection has the wrong module and
# the right answers.
_PROBES = (
    (SQLITE, "SELECT sqlite_version()"),
    (POSTGRESQL, "SHOW server_version"),
)


def _rollback_quietly(conn: object) -> None:
    """Undo a failed probe's effect on the caller's transaction.

    On PostgreSQL a failed statement aborts the transaction and every
    later statement fails until rollback. Probing must not leave the
    caller worse off than it found them.
    """
    rollback = getattr(conn, "rollback", None)
    if rollback is None:
        return
    try:
        rollback()
    except Exception:
        # A connection too broken to roll back is already the caller's
        # problem; masking it behind a diagnostic helps nobody.
        pass


def _interrogate(conn: object) -> tuple[str | None, str | None]:
    """Ask the connection what it is. Returns (None, None) if it will not say."""
    for dialect, sql in _PROBES:
        try:
            cursor = conn.cursor()
        except Exception:
            return None, None
        try:
            cursor.execute(sql)
            row = cursor.fetchone()
        except Exception:
            _rollback_quietly(conn)
            continue
        finally:
            try:
                cursor.close()
            except Exception:
                pass
        if row:
            return dialect, str(row[0])
    return None, None


def describe_backend(
    source: object,
    *,
    config_source: str | None = None,
) -> BackendReport:
    """Report the live engine behind ``source``.

    ``source`` is either a live DB-API connection — which is
    interrogated — or a :class:`StoreLocation`, which can only say which
    dialect was *selected*, never which is running, so its
    ``server_version`` stays ``None``.

    ``config_source`` is the caller's note about what chose this store
    (an env var name, a config tier). It is recorded verbatim and never
    inferred; ``None`` means the caller did not say.
    """
    if isinstance(source, StoreLocation):
        return BackendReport(
            dialect=source.dialect,
            server_version=None,
            config_source=config_source,
        )

    dialect, server_version = _interrogate(source)
    return BackendReport(
        dialect=dialect,
        server_version=server_version,
        config_source=config_source,
    )


# EOF
