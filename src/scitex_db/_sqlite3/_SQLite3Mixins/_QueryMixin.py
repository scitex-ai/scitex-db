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
    """Replace comments and quoted text with spaces, preserving length.

    A keyword search over raw SQL matches PROSE: a column named ``created_at``
    contains ``CREATE``, and ``WHERE note LIKE '%dropped%'`` contains ``DROP``.
    Blanking the parts that can hold arbitrary text leaves only syntax, which
    the user does not control -- the same principle as anchoring a test on
    something prose cannot produce.

    Spaces rather than removal so offsets and token boundaries survive.
    """
    return _COMMENT_OR_LITERAL.sub(lambda m: " " * len(m.group(0)), sql)


def _leading_keyword(sql: str) -> str:
    """The statement's first bare word, upper-cased, or ``""`` if there is none."""
    match = _WORD.search(_blank_noise(sql).lstrip().lstrip("("))
    return match.group(0).upper() if match else ""


def _is_write_query(sql: str) -> bool:
    """Whether ``sql`` mutates the database.

    Single source of truth for the write/read split: it gates both the
    read-only guard (``_check_writable``) and observer dispatch, so the two can
    never disagree about what counts as a write.

    DECIDED BY THE LEADING KEYWORD, NOT BY SCANNING THE BODY. The previous
    implementation asked ``any(keyword in sql.upper())``, which classifies
    ordinary reads as writes because a column name is text too. Measured on the
    live scitex-cards schema:

        SELECT created_at FROM tasks                  -> matched CREATE
        SELECT id, updated_at ... WHERE deleted_at    -> matched UPDATE, DELETE
        SELECT * FROM t WHERE note LIKE '%dropped%'   -> matched DROP

    That is not a rare edge: scitex-cards has 171 occurrences of
    ``created_at``/``updated_at``/``deleted_at``, so a large fraction of their
    reads were refused on a read-only connection -- and, because this same
    function routes observer dispatch, a misclassified SELECT also fired
    ``post_save`` observers announcing a write that never happened.

    ``WITH`` is resolved rather than guessed: a CTE may precede either a SELECT
    or an INSERT, so the first write keyword appearing at paren depth 0 decides
    it. Blanked literals mean a CTE body containing the word INSERT cannot vote.

    AN UNRECOGNISED LEADING KEYWORD COUNTS AS A WRITE. The two possible errors
    are not symmetric: treating an unknown statement as a read would let it past
    the read-only guard and fire the wrong observer, while treating it as a
    write costs an unnecessary refusal on a read-only connection. Unknown
    collapses toward the safe pole, and it collapses deliberately.
    """
    keyword = _leading_keyword(sql)
    if keyword == "WITH":
        return _cte_leads_to_write(sql)
    if keyword in _READ_KEYWORDS:
        return False
    if keyword in _WRITE_KEYWORDS:
        return True
    return True


def _split_statements(script: str) -> list[str]:
    """Split ``script`` on statement-terminating semicolons.

    Only depth-0 semicolons outside literals terminate a statement, so a
    semicolon inside a string or a trigger body does not split it -- which
    matters here because trigger bodies are exactly where this store keeps its
    ``BEGIN ... END`` guards.
    """
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
    """Whether ANY statement in a multi-statement script mutates the database.

    `executescript` takes a script, and the leading keyword only describes its
    FIRST statement -- ``SELECT 1; DROP TABLE t;`` leads with a read. Asking
    each statement separately is what keeps the leading-keyword fix from making
    scripts less safe than the substring check it replaced.
    """
    return any(_is_write_query(statement) for statement in _split_statements(script))


def _cte_leads_to_write(sql: str) -> bool:
    """Whether a ``WITH`` statement ends in a write, by depth-0 keyword.

    ``WITH x AS (SELECT ...) INSERT INTO t ...`` writes; the same CTE followed
    by ``SELECT`` does not. Only depth 0 is consulted, so a subquery cannot
    decide the outer statement's kind.
    """
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
