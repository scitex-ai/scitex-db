#!/usr/bin/env python3
"""Smoke: scitex-db CLI happy path via subprocess (<60s, no side effects)."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke


def test_cli_help_lists_inspect_db():
    # Arrange
    cmd = [sys.executable, "-m", "scitex_db", "--help"]
    # Act
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    # Assert
    assert proc.returncode == 0 and "inspect-db" in proc.stdout
