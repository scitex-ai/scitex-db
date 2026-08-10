#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _lock_cost: the lock is taken even though the write is rolled back."""

from __future__ import annotations

import pytest

from scitex_db._schema_change import LockCost, RefusedToLockLiveStore, measure_lock_cost


def test_measuring_without_asserting_scratch_is_refused(conn):
    """The lock is taken even though the write is rolled back."""
    # Arrange
    stmt = "CREATE TRIGGER t AFTER UPDATE ON tasks BEGIN SELECT 1; END"
    # Act
    # Assert
    with pytest.raises(RefusedToLockLiveStore):
        measure_lock_cost(conn, stmt, scratch=False)


def _refusal_message(conn) -> str:
    """Capture the refusal text without a raises block.

    Using try/except rather than pytest.raises keeps this to ONE assertion:
    STX-TQ007 counts a raises block as an assertion, so pairing it with a
    content check would test two things in one function and hide the second
    whenever the first fails.
    """
    try:
        measure_lock_cost(conn, "ALTER TABLE tasks ADD COLUMN x INTEGER", scratch=False)
    except RefusedToLockLiveStore as exc:
        return str(exc)
    return ""


def test_refusal_names_the_lock_not_the_write(conn):
    """A caller who reads 'rolled back' must not conclude 'undisruptive'."""
    # Arrange
    message = _refusal_message(conn)
    # Act
    mentions_the_lock = "blocks every reader and writer" in message
    # Assert
    assert mentions_the_lock is True


def test_scratch_measurement_rolls_back(conn):
    # Arrange
    calls: list[str] = []
    # Act
    result = measure_lock_cost(
        conn,
        "CREATE TRIGGER t",
        scratch=True,
        execute=lambda c, s: calls.append("execute"),
        begin=lambda c: calls.append("begin"),
        rollback=lambda c: calls.append("rollback"),
    )
    # Assert
    assert result.rolled_back is True


def test_scratch_measurement_never_commits(conn):
    """There is no commit path; the sequence must end in rollback."""
    # Arrange
    calls: list[str] = []
    # Act
    measure_lock_cost(
        conn,
        "CREATE TRIGGER t",
        scratch=True,
        execute=lambda c, s: calls.append("execute"),
        begin=lambda c: calls.append("begin"),
        rollback=lambda c: calls.append("rollback"),
    )
    # Assert
    assert calls == ["begin", "execute", "rollback"]


def _raising_measure(conn, calls):
    def boom(c, s):
        raise RuntimeError("syntax error")

    return measure_lock_cost(
        conn,
        "CREATE TRIGGR t",
        scratch=True,
        execute=boom,
        begin=lambda c: calls.append("begin"),
        rollback=lambda c: calls.append("rollback"),
    )


def test_a_raising_statement_propagates(conn):
    # Arrange
    calls: list[str] = []
    # Act
    # Assert
    with pytest.raises(RuntimeError):
        _raising_measure(conn, calls)


def test_a_raising_statement_still_rolls_back(conn):
    """A failed DDL must not leave the transaction open holding its lock."""
    # Arrange
    calls: list[str] = []
    try:
        _raising_measure(conn, calls)
    except RuntimeError:
        pass
    # Act
    sequence = list(calls)
    # Assert
    assert sequence == ["begin", "rollback"]


def test_summary_names_a_committed_result_loudly():
    """rolled_back=False must be visibly alarming in the summary."""
    # Arrange
    cost = LockCost(statement="ALTER TABLE tasks ...", seconds=0.5, rolled_back=False)
    # Act
    text = cost.summary()
    # Assert
    assert "COMMITTED" in text
