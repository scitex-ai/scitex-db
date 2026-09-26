#!/usr/bin/env python3
"""
Inline utilities to avoid external dependencies.
"""

import scitex_logging as slogging

log = slogging.getLogger(__name__)


def printc(message: str, c: str = "blue", **kwargs):
    """Report a status message via scitex-logging.

    Kept under the historic ``printc`` name so existing callers
    (``SQLite3``/``PostgreSQL`` display helpers) keep working. The
    ``c`` colour and extra ``kwargs`` are accepted and ignored:
    level-aware scitex-logging output carries its own aligned
    ``INFO:``/``WARN:``/``ERRO:``/``SUCC:`` prefix (PS-220).
    """
    log.info(message)
