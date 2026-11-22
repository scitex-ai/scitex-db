#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Neutral post-save / post-load hook registry for scitex-db.

This registry does not intercept database access. SQLite's _QueryMixin calls
it explicitly; direct driver calls and helpers bypassing that dispatcher are
not automatically observed. Comprehensive cross-backend observation remains
an unmet capability, not a property of this registry. Notifications alone do
not prove commit or durable storage.

Public extension API. Observer packages (scitex-clew, future audit or
notification observers) register callbacks here on their own import;
scitex-db itself never names any observer.

Per SOC.md R6: producer packages don't know observer packages. The
arrow runs observer -> producer. scitex-db owns this registry;
observers self-register.

This mirrors ``scitex_io._observers`` deliberately, so an observer that
already knows the scitex-io shape needs no new concepts. The one
difference is the payload: scitex-io hooks describe a *file*
(``path, obj, kwargs``), whereas scitex-db hooks describe a *statement
against a database* (``db_path, query, parameters/result``).

Usage from an observer
----------------------

>>> from scitex_db import register_post_save_hook
>>> def on_write(db_path, query, parameters):
...     # Exception subclasses are isolated; BaseException propagates
...     ...
>>> register_post_save_hook(on_write)
"""

from __future__ import annotations

import scitex_logging as slogging
from pathlib import Path
from typing import Any, Callable, List

logger = slogging.getLogger(__name__)


PostSaveHook = Callable[[Path, str, Any], None]
"""Signature: ``(db_path, query, parameters) -> None``.

SQLite execute/executemany dispatch according to the wrapper's SQL
classification. Batch calls and scripts classified as writes emit one event,
not one per row or statement. With autocommit=False, execute can notify before a later rollback;
executemany and executescript perform their own commit call before dispatch.
"""

PostLoadHook = Callable[[Path, str, Any], None]
"""Signature: ``(db_path, query, result) -> None``.

SQLite execute/executemany read dispatch supplies a live caller-owned
cursor, not materialized rows or a stable snapshot. Fetching in a hook can
consume rows before the caller. Scripts classified as reads do not emit
post-load notifications.
"""


_post_save_hooks: List[PostSaveHook] = []
_post_load_hooks: List[PostLoadHook] = []


def register_post_save_hook(fn: PostSaveHook) -> None:
    """Append a callback for explicit post-save dispatch in this process.

    Hooks run synchronously in registration order. Callback Exception
    subclasses are caught and logged at debug level, allowing later hooks
    to run. BaseException subclasses propagate and can stop later hooks,
    after SQL may already have executed. Callbacks are not sandboxed.
    """
    _post_save_hooks.append(fn)


def register_post_load_hook(fn: PostLoadHook) -> None:
    """Append a post-load callback with the same isolation rules as post-save."""
    _post_load_hooks.append(fn)


def fire_post_save(db_path: Path, query: str, parameters: Any) -> None:
    """Invoke post-save hooks; catch callback Exception, propagate BaseException."""
    for fn in _post_save_hooks:
        try:
            fn(db_path, query, parameters)
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "post-save hook %r failed for %s: %s", fn, db_path, e
            )


def fire_post_load(db_path: Path, query: str, result: Any) -> None:
    """Invoke post-load hooks; catch callback Exception, propagate BaseException."""
    for fn in _post_load_hooks:
        try:
            fn(db_path, query, result)
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "post-load hook %r failed for %s: %s", fn, db_path, e
            )


__all__ = [
    "PostSaveHook",
    "PostLoadHook",
    "register_post_save_hook",
    "register_post_load_hook",
    "fire_post_save",
    "fire_post_load",
]

# EOF
