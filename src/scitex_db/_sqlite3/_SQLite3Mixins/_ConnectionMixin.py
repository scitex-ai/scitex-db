#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Timestamp: "2025-09-11 05:43:10 (ywatanabe)"
# File: /ssh:sp:/home/ywatanabe/proj/scitex_repo/src/scitex/db/_sqlite3/_SQLite3Mixins/_ConnectionMixin.py
# ----------------------------------------
from __future__ import annotations
import os
__FILE__ = __file__
__DIR__ = os.path.dirname(__FILE__)
# ----------------------------------------

# Time-stamp: "2024-11-29 04:33:58 (ywatanabe)"

THIS_FILE = "/home/ywatanabe/proj/scitex_repo/src/scitex/db/_SQLite3Mixins/_ConnectionMixin.py"

"""
1. Functionality:
   - Manages SQLite database connections with thread-safe operations
   - Handles database journal files and transaction states
2. Input:
   - Database file path
3. Output:
   - Managed SQLite connection and cursor objects
4. Prerequisites:
   - sqlite3
   - threading
"""

import shutil
import sqlite3
import tempfile
import threading


class _ConnectionMixin:
    """Connection management functionality"""

    def __init__(
        self,
        db_path: str,
        use_temp_db: bool = False,
        *,
        mode: str = "rwc",
        timeout: float = 60.0,
    ):
        self.lock = threading.Lock()
        self._maintenance_lock = threading.Lock()
        self.db_path = db_path
        self.mode = mode
        self.timeout = timeout
        self.conn = None
        self.cursor = None
        self.temp_path = None  # Initialize temp_path attribute
        if db_path:
            self.connect(db_path, use_temp_db, mode=mode, timeout=timeout)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _create_temp_copy(self, db_path: str) -> str:
        """Creates temporary copy of database."""
        temp_dir = tempfile.gettempdir()
        self.temp_path = os.path.join(
            temp_dir, f"temp_{os.path.basename(db_path)}"
        )
        shutil.copy2(db_path, self.temp_path)
        return self.temp_path

    def connect(
        self,
        db_path: str,
        use_temp_db: bool = False,
        *,
        mode: str = "rwc",
        timeout: float = 60.0,
    ) -> None:
        if self.conn:
            self.close()

        path_to_connect = (
            self._create_temp_copy(db_path) if use_temp_db else db_path
        )

        # Always go through SQLite's URI form so the open mode is explicit.
        # ``mode='rwc'`` (default) matches the previous ``sqlite3.connect(path)``
        # behaviour of opening read-write and creating the file if missing.
        uri = f"file:{path_to_connect}?mode={mode}"
        self.conn = sqlite3.connect(uri, uri=True, timeout=timeout)
        self.cursor = self.conn.cursor()

        # PRAGMA tuning. ``ro`` is read-only so the journal-mode write and the
        # ``commit()`` at the bottom would error — skip them in that branch.
        # WAL also requires write access, so we only set it for rw/rwc.
        with self.lock:
            if mode != "ro":
                # WAL mode settings (write-only)
                self.cursor.execute("PRAGMA journal_mode = WAL")
                self.cursor.execute("PRAGMA synchronous = NORMAL")
                self.cursor.execute("PRAGMA busy_timeout = 300000")  # 5 minutes
                self.cursor.execute("PRAGMA mmap_size = 30000000000")
                self.cursor.execute("PRAGMA temp_store = MEMORY")
                self.cursor.execute("PRAGMA cache_size = -2000")
                self.cursor.execute(
                    "PRAGMA wal_autocheckpoint = 1000"
                )  # Auto-checkpoint
                self.conn.commit()
            else:
                # Read-only: only set tunings safe under query_only.
                self.cursor.execute("PRAGMA query_only = ON")
                self.cursor.execute("PRAGMA temp_store = MEMORY")
                self.cursor.execute("PRAGMA cache_size = -2000")

    def close(self) -> None:
        """Release the handles. Always leaves the object clean, even on failure.

        EVERY STEP IS GUARDED AND THE NULLING IS UNCONDITIONAL, because it used
        not to be: ``self.cursor.close()`` sat outside the try, so a raising
        cursor teardown aborted the method before ``self.cursor``/``self.conn``
        were cleared. The object was then left holding a DEAD connection --
        ``conn is None`` was False against an already-closed database -- and
        ``__del__`` called ``close()`` again and raised again, surfacing as
        "Exception ignored in ``SQLite3.__del__``".

        Measured 2026-07-31, reachable through the commit that ``__exit__`` now
        performs on a clean exit:

            with SQLite3(p) as db:
                db.execute("INSERT INTO t VALUES (1)")
                db.conn.close()          # makes the exit-commit fail
            -> exit raised, correctly
            -> conn is None: False, cursor is None: False   <- the defect

        SWALLOWING HERE IS CORRECT, and it is the one place in this package
        where it is. Teardown's job is to release resources; the caller has
        already been told what actually went wrong, because ``__exit__`` raises
        the commit failure itself. A secondary error from closing a handle that
        is already dead adds nothing and would mask the real one.

        Found by scitex-cards asking whether a failing COMMIT could leave state
        the next context inherits. It could.

        THE HANDLES ARE READ WITH ``getattr``, NOT ``self.cursor``, because
        teardown must also survive never having been SET UP. ``__init__`` can
        raise before ``_ConnectionMixin.__init__`` ever assigns them -- a
        mistyped ``mode=`` is enough -- and ``__del__`` then calls ``close()``
        on a half-built object. Measured 2026-07-31:

            SQLite3("/tmp/x.db", mode="nope")
            -> ValueError: mode must be one of 'ro', 'rw', 'rwc'   correct
            -> Exception ignored in SQLite3.__del__:
                 AttributeError: 'SQLite3' object has no attribute 'cursor'

        The second traceback is the damage. The caller made one mistake and is
        shown two, the louder of which points at an attribute they have never
        heard of instead of at the argument they mistyped. Teardown must not
        editorialise over the failure that caused it.

        Note this is a DIFFERENT precondition from the one above, which is why
        the earlier fix did not cover it: that one made teardown survive its own
        failures, this one makes it survive never having run its setup.
        """
        cursor = getattr(self, "cursor", None)
        conn = getattr(self, "conn", None)
        try:
            if cursor:
                try:
                    cursor.close()
                except sqlite3.Error:
                    pass
            if conn:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
        finally:
            # Unconditional: no teardown failure may leave a dead handle set.
            self.cursor = None
            self.conn = None

        if getattr(self, "temp_path", None) and os.path.exists(self.temp_path):
            try:
                os.remove(self.temp_path)
                self.temp_path = None
            except OSError:
                pass

    def reconnect(self, use_temp_db: bool = False) -> None:
        if self.db_path:
            self.connect(self.db_path, use_temp_db)
        else:
            raise ValueError("No database path specified for reconnection")

    def ensure_connection(self):
        """
        Ensure connection when used in context manager (with statement).
        All methods that use `self.cursor` or `self.conn` should call this first.
        """
        if not self.cursor or not self.conn:
            self.reconnect()

# EOF
