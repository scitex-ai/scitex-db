#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Timestamp: "2025-09-11 05:49:14 (ywatanabe)"
# File: /ssh:sp:/home/ywatanabe/proj/scitex_repo/src/scitex/db/_sqlite3/_SQLite3Mixins/_QueryMixin.py
# ----------------------------------------
from __future__ import annotations

import os

__FILE__ = __file__
__DIR__ = os.path.dirname(__FILE__)
# ----------------------------------------

import sqlite3
from typing import List, Tuple

import pandas as pd

from ..._observers import fire_post_load, fire_post_save

_WRITE_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
)


def _is_write_query(sql: str) -> bool:
    """Whether ``sql`` mutates the database.

    Single source of truth for the write/read split: it gates both the
    read-only guard (``_check_writable``) and observer dispatch, so the
    two can never disagree about what counts as a write.
    """
    upper = sql.upper()
    return any(keyword in upper for keyword in _WRITE_KEYWORDS)


class _QueryMixin:
    """Query execution functionality"""

    def _sanitize_parameters(self, parameters):
        """Convert pandas Timestamp objects to strings"""
        if isinstance(parameters, (list, tuple)):
            return [str(p) if isinstance(p, pd.Timestamp) else p for p in parameters]
        return parameters

    def execute(self, query: str, parameters: Tuple = ()) -> None:
        self.ensure_connection()
        self._check_context_manager()

        if not self.cursor:
            raise ConnectionError("Database not connected")

        is_write = _is_write_query(query)
        if is_write:
            self._check_writable()

        try:
            parameters = self._sanitize_parameters(parameters)
            self.cursor.execute(query, parameters)
            if self.autocommit:
                self.conn.commit()
                self.cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
                # self.cursor.execute("PRAGMA wal_checkpoint(FULL)")
            if is_write:
                fire_post_save(self.db_path, query, parameters)
            else:
                fire_post_load(self.db_path, query, self.cursor)
            return self.cursor
        except sqlite3.IntegrityError:
            # Preserve IntegrityError so callers can catch it specifically
            # (e.g. UNIQUE/FOREIGN KEY constraint violations).
            raise
        except sqlite3.Error as err:
            raise sqlite3.Error(f"Query execution failed: {err}")

    def executemany(self, query: str, parameters: List[Tuple]) -> None:
        self.ensure_connection()
        if not self.cursor:
            raise ConnectionError("Database not connected")

        is_write = _is_write_query(query)
        if is_write:
            self._check_writable()

        try:
            parameters = [self._sanitize_parameters(p) for p in parameters]
            self.cursor.executemany(query, parameters)
            self.conn.commit()
            if is_write:
                fire_post_save(self.db_path, query, parameters)
            else:
                fire_post_load(self.db_path, query, self.cursor)
        except sqlite3.IntegrityError:
            raise
        except sqlite3.Error as err:
            raise sqlite3.Error(f"Batch query execution failed: {err}")

    def executescript(self, script: str) -> None:
        self.ensure_connection()
        if not self.cursor:
            raise ConnectionError("Database not connected")

        is_write = _is_write_query(script)
        if is_write:
            self._check_writable()

        try:
            self.cursor.executescript(script)
            self.conn.commit()
            if is_write:
                fire_post_save(self.db_path, script, None)
        except sqlite3.IntegrityError:
            raise
        except sqlite3.Error as err:
            raise sqlite3.Error(f"Script execution failed: {err}")


# EOF
