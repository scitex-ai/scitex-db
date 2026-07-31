#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The one exception every refusal in this package raises.

Its own module because both ``_copy`` and ``_provenance`` raise it and
``_provenance`` is imported BY ``_copy`` -- keeping it in either would make the
import circular. A shared exception is exactly the kind of leaf that belongs at
the bottom of the graph.
"""

from __future__ import annotations

__all__ = ["MigrationRefused"]


class MigrationRefused(Exception):
    """Raised when the migration will not start, or will not be marked done."""

# EOF
