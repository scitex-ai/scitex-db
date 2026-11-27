"""Pytest fixtures and rootdir marker for this package.

An empty conftest.py at tests/ is the canonical SciTeX
convention (audit-project PS208) — it pins the pytest
rootdir and gives downstream fixtures a home.

Subprocess coverage is configured in pyproject.toml via coverage.py's subprocess patch; test collection must not install .pth files or overwrite caller-owned coverage environment variables.
"""
from __future__ import annotations

import os

# PS-220: status/diagnostic output goes through scitex-logging, which
# defaults to WARN (log.info is silent). Tests assert on that output, so
# opt into INFO here — mirrors the pilot playbook (scitex-genai).
os.environ.setdefault("SCITEX_LOGGING_LEVEL", "INFO")
try:
    import scitex_logging as _slogging

    _slogging.set_level("INFO")
except Exception:
    pass
