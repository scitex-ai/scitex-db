#!/usr/bin/env python3
"""E2E: SQLite3 CRUD round-trip against a real database file.

Loopback only (tmp file, no network). Skipped unless RUN_E2E=1.
"""

from __future__ import annotations

import os

import pytest

from scitex_db._sqlite3._SQLite3 import SQLite3

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("RUN_E2E") != "1", reason="e2e runs only with RUN_E2E=1"
    ),
]


def test_sqlite3_insert_many_round_trip(tmp_path):
    # Arrange
    db_path = str(tmp_path / "e2e.db")
    # Act
    with SQLite3(db_path) as db:
        db.create_table("t", {"id": "INTEGER PRIMARY KEY", "v": "TEXT"})
        db.insert_many("t", [{"id": 1, "v": "a"}])
        result = db.get_rows("t", where="v='a'")
    # Assert
    assert len(result) == 1
