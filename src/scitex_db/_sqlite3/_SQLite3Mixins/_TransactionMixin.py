#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Time-stamp: "2024-11-29 04:32:42 (ywatanabe)"
# File: ./scitex_repo/src/scitex/db/_SQLite3Mixins/_TransactionMixin.py

THIS_FILE = (
    "/home/ywatanabe/proj/scitex_repo/src/scitex/db/_SQLite3Mixins/_TransactionMixin.py"
)

import contextlib
import sqlite3


class _TransactionMixin:
    """Transaction management functionality"""

    @contextlib.contextmanager
    def transaction(self):
        with self.lock:
            self.begin()
            try:
                yield
                self.commit()
            except Exception as e:
                self.rollback()
                raise e

    def begin(self) -> None:
        # Python's sqlite3 module opens an implicit transaction before any
        # DML statement when isolation_level is not None. Commit any such
        # pending implicit transaction before starting a new explicit one,
        # otherwise SQLite raises "cannot start a transaction within a
        # transaction".
        if self.conn is not None and self.conn.in_transaction:
            self.conn.commit()
        self.execute("BEGIN TRANSACTION")

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def enable_foreign_keys(self) -> None:
        self.execute("PRAGMA foreign_keys = ON")

    def disable_foreign_keys(self) -> None:
        self.execute("PRAGMA foreign_keys = OFF")

    @property
    def writable(self) -> bool:
        try:
            self.cursor.execute("SELECT value FROM _db_state WHERE key = 'writable'")
            result = self.cursor.fetchone()
            return result[0].lower() == "true" if result else True
        except sqlite3.Error:
            return True

    @writable.setter
    def writable(self, state: bool) -> None:
        try:
            self.execute("UPDATE _db_state SET protected = 0 WHERE key = 'writable'")
            self.execute(
                "UPDATE _db_state SET value = ? WHERE key = 'writable'",
                (str(state).lower(),),
            )
            self.execute("UPDATE _db_state SET protected = 1 WHERE key = 'writable'")
            self.execute("PRAGMA query_only = ?", (not state,))
        except sqlite3.Error as err:
            raise ValueError(f"Failed to set writable state: {err}")

    def _check_writable(self) -> None:
        if not self.writable:
            raise ValueError("Database is in read-only mode")


# EOF
