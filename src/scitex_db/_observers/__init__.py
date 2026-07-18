#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Neutral post-save / post-load hook registry for scitex-db.

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
...     # never raise; hooks fail silently
...     ...
>>> register_post_save_hook(on_write)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


PostSaveHook = Callable[[Path, str, Any], None]
"""Signature: ``(db_path, query, parameters) -> None``.

Fires after every successful write statement (INSERT / UPDATE / DELETE /
DROP / CREATE / ALTER).
"""

PostLoadHook = Callable[[Path, str, Any], None]
"""Signature: ``(db_path, query, result) -> None``.

Fires after every successful read statement. ``result`` is the live
cursor, NOT materialized rows — fetching is the caller's job, and a hook
must not consume it. Fetch from a hook only if you know you own the
cursor.
"""


_post_save_hooks: List[PostSaveHook] = []
_post_load_hooks: List[PostLoadHook] = []


def register_post_save_hook(fn: PostSaveHook) -> None:
    """Register a function to run after every successful scitex-db write.

    Hooks fire in registration order. They MUST NOT raise — exceptions
    are swallowed with ``logger.debug``. A misbehaving observer must
    never break the host's database access.
    """
    _post_save_hooks.append(fn)


def register_post_load_hook(fn: PostLoadHook) -> None:
    """Register a function to run after every successful scitex-db read."""
    _post_load_hooks.append(fn)


def fire_post_save(db_path: Path, query: str, parameters: Any) -> None:
    """Internal: invoke registered post-save hooks. Never raises."""
    for fn in _post_save_hooks:
        try:
            fn(db_path, query, parameters)
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "post-save hook %r failed for %s: %s", fn, db_path, e
            )


def fire_post_load(db_path: Path, query: str, result: Any) -> None:
    """Internal: invoke registered post-load hooks. Never raises."""
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
