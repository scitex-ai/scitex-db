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

import re
import sqlite3
from typing import List, Optional, Tuple

import pandas as pd

from ..._observers import fire_post_load, fire_post_save

#: Statements that mutate the database. Matched as a leading KEYWORD, never as
#: a substring -- see :func:`_is_write_query`.
_WRITE_KEYWORDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        "DROP",
        "CREATE",
        "ALTER",
        "TRUNCATE",
        "VACUUM",
        "REINDEX",
        "ANALYZE",
    }
)

#: Statements that only read. Everything not in either set is treated as a
#: write, deliberately -- see :func:`_is_write_query`.
_READ_KEYWORDS = frozenset({"SELECT", "EXPLAIN", "VALUES", "PRAGMA", "WITH"})

_COMMENT_OR_LITERAL = re.compile(
    r"""
      --[^\n]*                 # line comment
    | /\*.*?\*/                # block comment
    | '(?:[^']|'')*'           # string literal, '' escape
    | "(?:[^"]|"")*"           # quoted identifier
    | \[[^\]]*\]               # bracketed identifier
    | `[^`]*`                  # backtick identifier
    """,
    re.VERBOSE | re.DOTALL,
)

_WORD = re.compile(r"[A-Za-z_]+")


def _blank_noise(sql: str) -> str:
    """Replace recognized comments and quoted text with equal-length spaces.

    This regex supports the forms below for keyword classification. It is
    not a SQLite tokenizer or a validator for arbitrary SQL."""
    return _COMMENT_OR_LITERAL.sub(lambda m: " " * len(m.group(0)), sql)


def _leading_keyword(sql: str) -> str:
    """The statement's first bare word, upper-cased, or ``""`` if there is none."""
    match = _WORD.search(_blank_noise(sql).lstrip().lstrip("("))
    return match.group(0).upper() if match else ""


def _is_write_query(sql: str) -> bool:
    """Classify SQL for this wrapper's writable check and observer dispatch.

    Ordinary statements use a leading keyword; WITH uses the depth-based
    helper below. Recognized comments and quoted text are blanked first, so
    SELECT columns such as created_at and literals containing DROP do not
    count as writes. Unknown leading keywords count as writes.

    This is a routing heuristic, not proof of SQLite side effects or an
    authorization boundary. Every PRAGMA is read-classified, including
    assignments such as PRAGMA user_version = 7 that can change the database.
    SQLite's native read-only connection and query_only policy remain separate
    controls. Comprehensive SQL classification remains an unresolved gap."""
    keyword = _leading_keyword(sql)
    if keyword == "WITH":
        return _cte_leads_to_write(sql)
    if keyword in _READ_KEYWORDS:
        return False
    if keyword in _WRITE_KEYWORDS:
        return True
    return True


def _split_statements(script: str) -> list[str]:
    """Split SQL into classification fragments at depth-zero semicolons.

    Recognized quotes/comments and parentheses protect their semicolons.
    BEGIN ... END trigger bodies are not tracked and can produce multiple
    fragments. The result is not a sequence of complete SQLite statements;
    it is used only by the script classification heuristic."""
    blanked = _blank_noise(script)
    statements, start, depth = [], 0, 0
    for index, char in enumerate(blanked):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            statements.append(script[start:index])
            start = index + 1
    statements.append(script[start:])
    return [s for s in statements if s.strip()]


def _script_is_write(script: str) -> bool:
    """Whether any classification fragment is write-classified.

    This detects SELECT 1; DROP TABLE t even though the first fragment reads.
    It inherits the classifier's limits: PRAGMA assignments remain read-
    classified, and trigger fragments are not complete parsed statements."""
    return any(_is_write_query(statement) for statement in _split_statements(script))


def _cte_leads_to_write(sql: str) -> bool:
    """Classify WITH by its first recognized depth-zero write word or SELECT.

    Blanked quoted text and parenthesized CTE bodies do not vote. This is a
    depth-based heuristic, not a complete parser for SQLite's WITH grammar."""
    blanked = _blank_noise(sql)
    depth = 0
    token = ""
    for char in blanked + " ":
        if char == "(":
            depth += 1
            token = ""
        elif char == ")":
            depth -= 1
            token = ""
        elif char.isalpha() or char == "_":
            token += char
        else:
            if depth == 0 and token:
                word = token.upper()
                if word in _WRITE_KEYWORDS:
                    return True
                if word == "SELECT":
                    return False
            token = ""
    return False


class _QueryMixin:
    """Query execution functionality"""

    def _sanitize_parameters(self, parameters):
        """Convert pandas Timestamp objects to strings"""
        if isinstance(parameters, (list, tuple)):
            return [str(p) if isinstance(p, pd.Timestamp) else p for p in parameters]
        return parameters

    def execute(
        self, query: str, parameters: Tuple = ()
    ) -> Optional[sqlite3.Cursor]:
        """Execute ``query`` and return the cursor, so reads can be fetched.

        The annotation used to say ``-> None`` while the body returned
        ``self.cursor``, which made ordinary DB-API usage
        (``conn.execute(sql).fetchone()``) look unsupported to anyone reading
        the signature. The behaviour was right; the declaration was not.
        """
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
        except sqlite3.Error:
            # RE-RAISED UNCHANGED, class and traceback intact. This used to
            # wrap every non-Integrity error in a bare `sqlite3.Error`, which
            # collapsed the subclass callers actually branch on -- scitex-cards
            # catches `OperationalError` to mean "this store has no schema_meta
            # yet", and after the wrap that catch stopped matching, turning a
            # routine absent-table case into an unhandled error.
            #
            # The old message added the prefix "Query execution failed" and
            # nothing else: no query, no parameters. It cost the exception type
            # and bought a string the traceback already implied.
            raise

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
        except sqlite3.Error:
            # Same reasoning as `execute`: preserve the subclass.
            raise

    def executescript(self, script: str) -> None:
        self.ensure_connection()
        if not self.cursor:
            raise ConnectionError("Database not connected")

        # A SCRIPT, not a statement: `_is_write_query` reads the leading
        # keyword, which for "SELECT 1; DROP TABLE t;" would say "read". Any
        # statement in the script writing makes the whole script a write.
        is_write = _script_is_write(script)
        if is_write:
            self._check_writable()

        try:
            self.cursor.executescript(script)
            self.conn.commit()
            if is_write:
                fire_post_save(self.db_path, script, None)
        except sqlite3.Error:
            # Same reasoning as `execute`: preserve the subclass.
            raise


# EOF
