#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _deferrable_fk: the precondition lives inside the transaction."""

from __future__ import annotations

import pytest

from scitex_db.schema_change._deferrable_fk import OrphansFound, add_deferrable_fk


class _Conn:
    """Stand-in connection."""


def _args(**over):
    base = dict(
        child_table="task_comments",
        child_column="task_id",
        parent_table="tasks",
        parent_column="id",
        constraint_name="task_comments_task_id_fkey",
    )
    base.update(over)
    return base


def test_clean_store_commits_the_constraint():
    # Arrange
    calls: list[str] = []
    conn = _Conn()
    # Act
    add_deferrable_fk(
        conn,
        **_args(),
        execute=lambda c, s: calls.append(s.split()[0]),
        count_orphans=lambda c, s: 0,
    )
    # Assert
    assert calls == ["BEGIN", "ALTER", "COMMIT"]


def test_constraint_is_deferrable_initially_deferred():
    """Deferring is the whole point; a plain FK would not fix the ordering bug."""
    # Arrange
    statements: list[str] = []
    # Act
    add_deferrable_fk(
        _Conn(),
        **_args(),
        execute=lambda c, s: statements.append(s),
        count_orphans=lambda c, s: 0,
    )
    # Assert
    assert "DEFERRABLE INITIALLY DEFERRED" in statements[1]


def test_orphans_raise_rather_than_return():
    """A returned count could be ignored; a raise cannot."""
    # Arrange
    conn = _Conn()
    # Act
    # Assert
    with pytest.raises(OrphansFound):
        add_deferrable_fk(
            conn,
            **_args(),
            execute=lambda c, s: None,
            count_orphans=lambda c, s: 3,
        )


def test_orphans_leave_no_constraint_and_roll_back():
    """THE ISOLATING CASE. If the check ran outside the transaction, or after
    the ALTER, this sequence would contain an ALTER. It must not."""
    # Arrange
    calls: list[str] = []
    try:
        add_deferrable_fk(
            _Conn(),
            **_args(),
            execute=lambda c, s: calls.append(s.split()[0]),
            count_orphans=lambda c, s: 3,
        )
    except OrphansFound:
        pass
    # Act
    sequence = list(calls)
    # Assert
    assert sequence == ["BEGIN", "ROLLBACK"]


def test_orphan_check_runs_after_begin():
    """The check must share the transaction's snapshot, not precede it."""
    # Arrange
    order: list[str] = []

    def counting(c, s):
        order.append("count")
        return 0

    # Act
    add_deferrable_fk(
        _Conn(),
        **_args(),
        execute=lambda c, s: order.append(s.split()[0]),
        count_orphans=counting,
    )
    # Assert
    assert order[:2] == ["BEGIN", "count"]


def test_orphan_error_names_the_count():
    # Arrange
    err = OrphansFound(child_table="task_comments", parent_table="tasks", count=7)
    # Act
    text = str(err)
    # Assert
    assert "7 row(s)" in text


def test_orphan_error_says_nothing_was_added():
    """A caller must not have to guess whether the store changed."""
    # Arrange
    err = OrphansFound(child_table="task_comments", parent_table="tasks", count=1)
    # Act
    text = str(err)
    # Assert
    assert "NOT added" in text


def test_a_failing_alter_still_rolls_back():
    """A DDL error must not leave the transaction open holding its lock."""
    # Arrange
    calls: list[str] = []

    def execute(c, s):
        calls.append(s.split()[0])
        if s.startswith("ALTER"):
            raise RuntimeError("duplicate constraint name")

    try:
        add_deferrable_fk(
            _Conn(), **_args(), execute=execute, count_orphans=lambda c, s: 0
        )
    except RuntimeError:
        pass
    # Act
    sequence = list(calls)
    # Assert
    assert sequence == ["BEGIN", "ALTER", "ROLLBACK"]
