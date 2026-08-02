#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read a store's config value and say what it is, or refuse.

The hazard this closes, measured in scitex-cards on 2026-08-01/02 and
recorded in its ``docs/design/sqlite-to-postgres-migration-hazards.md``:
a PostgreSQL DSN reaching ``Path()`` does not raise. ::

    >>> Path("postgresql://host/db")
    PosixPath('postgresql:/host/db')

One slash is eaten and the result is a *relative path*. SQLite then
creates that file, serves it empty, and reports healthy. Nothing fails.
Two separate silent successes came from this in a single day, and both
happened BEFORE any parsing — the raw string went from the environment
straight into ``Path()``.

So this module owns three things, and the third is the one that was
missing:

1. :func:`parse_store_url` is TOTAL. Every input becomes a validated
   :class:`StoreLocation` or raises. There is no branch returning
   ``None``, a bare string, or "probably a path" — that branch is where
   both incidents lived.
2. A postgresql location carries ``path=None``, validator-enforced. A
   caller who ignores ``dialect`` and reaches for ``.path`` gets
   ``Path(None)`` → ``TypeError``: loud, at the call site, on the first
   run, instead of an empty file at a mangled relative path.
3. :func:`resolve_store` READS the config value. A parser that only
   refuses what is handed to it cannot refuse what was never handed to
   it, and neither incident ever called a parser.

What none of that can do is reach a caller who never calls it.
``Path(os.environ["SCITEX_CARDS_DB"])``, written by someone who has not
heard of this module, is invisible to all three. That is the linter's
job (``STX-DB002``), not the type's. The type refuses; the rule catches
the bypass. Neither alone closes the class.

stdlib only, by contract — see ``docs/portable-store-seam-surface.md``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

__all__ = [
    "StoreLocation",
    "UnknownStoreScheme",
    "parse_store_url",
    "resolve_store",
]

SQLITE = "sqlite"
POSTGRESQL = "postgresql"

# Spellings accepted for each dialect. `postgres://` is included because
# libpq accepts it and real config files carry it; normalising it here
# means a consumer never has to care which spelling it was handed.
_SQLITE_SCHEMES = frozenset({"sqlite", "sqlite3"})
_POSTGRESQL_SCHEMES = frozenset({"postgresql", "postgres"})


class UnknownStoreScheme(ValueError):
    """A store value carried a URL scheme this seam does not recognise.

    Deliberately NOT a fallback to "probably a path": an unrecognised
    scheme reaching ``Path()`` is the exact shape of the incident this
    module exists to prevent.
    """


@dataclass(frozen=True)
class StoreLocation:
    """Where a store lives, and which dialect speaks to it.

    ``path`` and ``dsn`` are mutually exclusive and each is tied to its
    dialect, so the wrong one is always ``None`` rather than a plausible
    string. Reaching for it fails immediately instead of quietly
    producing a second, empty database.
    """

    dialect: str
    path: Path | None = None
    dsn: str | None = None

    def __post_init__(self) -> None:
        if self.dialect == SQLITE:
            if self.path is None:
                raise ValueError("sqlite StoreLocation requires a path")
            if self.dsn is not None:
                raise ValueError(
                    "sqlite StoreLocation must not carry a dsn "
                    f"(got {self.dsn!r})"
                )
        elif self.dialect == POSTGRESQL:
            if self.dsn is None:
                raise ValueError("postgresql StoreLocation requires a dsn")
            if self.path is not None:
                raise ValueError(
                    "postgresql StoreLocation must not carry a path "
                    f"(got {self.path!r}); a DSN is not a filesystem path"
                )
        else:
            raise ValueError(
                f"unknown dialect {self.dialect!r}; "
                f"expected {SQLITE!r} or {POSTGRESQL!r}"
            )


def _scheme_of(value: str) -> str:
    """The URL scheme, or "" when the value is a plain filesystem path.

    A single-character scheme is treated as NO scheme, because that is a
    Windows drive letter (``C:\\store.db``) and urlsplit reports it as
    ``c``. Guessing wrong here sends a real path down the DSN branch.
    """
    scheme = urlsplit(value).scheme
    if len(scheme) < 2:
        return ""
    return scheme.lower()


def parse_store_url(value: str) -> StoreLocation:
    """Classify a store config value. Total: returns or raises.

    Accepts a bare filesystem path, ``sqlite://``/``sqlite3://``, or
    ``postgresql://``/``postgres://``. Anything else raises
    :class:`UnknownStoreScheme` rather than being coerced to a path.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"store value must be str, got {type(value).__name__}"
        )
    if not value.strip():
        raise ValueError("store value is empty")

    scheme = _scheme_of(value)

    if scheme == "":
        return StoreLocation(dialect=SQLITE, path=Path(value))

    if scheme in _POSTGRESQL_SCHEMES:
        return StoreLocation(dialect=POSTGRESQL, dsn=value)

    if scheme in _SQLITE_SCHEMES:
        # sqlite:///abs/path -> /abs/path ; sqlite://rel -> rel
        remainder = value.split("://", 1)[1] if "://" in value else ""
        if not remainder:
            raise ValueError(
                f"sqlite URL carries no path: {value!r}"
            )
        return StoreLocation(dialect=SQLITE, path=Path(remainder))

    raise UnknownStoreScheme(
        f"unrecognised store scheme {scheme!r} in {value!r}. "
        f"Expected one of {sorted(_SQLITE_SCHEMES | _POSTGRESQL_SCHEMES)}, "
        "or a bare filesystem path. Refusing to treat it as a path: a URL "
        "reaching Path() becomes a relative path, which SQLite will create "
        "and serve empty."
    )


def resolve_store(
    *,
    env: str,
    default: str | None = None,
) -> StoreLocation:
    """Read the store value from the environment and classify it.

    This exists so no consuming package ever holds the raw string. Both
    2026-08-01 incidents happened before any parse, so a parser that is
    only handed values cannot be the whole guard.

    Raises when the variable is unset and no ``default`` is given —
    there is no silent fallback, because an unset store variable that
    quietly becomes a local file is the same failure in a new costume.
    """
    raw = os.environ.get(env)
    if raw is None or not raw.strip():
        if default is None:
            raise ValueError(
                f"environment variable {env!r} is unset or empty and no "
                "default was given; refusing to guess a store location"
            )
        raw = default
    return parse_store_url(raw)


# EOF
