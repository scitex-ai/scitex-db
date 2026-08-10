#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _fk_shape: three states, matched on table+column not on name."""

from __future__ import annotations

from scitex_db._schema_change._fk_shape import FKShape, observe_fk


class _Conn:
    """Stand-in connection."""


def _observe(row, intended="task_comments_task_id_fkey"):
    return observe_fk(
        _Conn(),
        table="task_comments",
        column="task_id",
        intended_name=intended,
        fetch_one=lambda c, s: row,
    )


def test_no_row_reports_absent():
    """The live store's shape: three declared FKs are missing from it."""
    # Arrange
    row = None
    # Act
    obs = _observe(row)
    # Assert
    assert obs.shape is FKShape.ABSENT


def test_non_deferrable_row_reports_present_not_deferrable():
    """A fresh store's shape: _SCHEMA_SQL declares the FK, but not deferrable."""
    # Arrange
    row = ("task_comments_task_id_fkey", False)
    # Act
    obs = _observe(row)
    # Assert
    assert obs.shape is FKShape.PRESENT_NOT_DEFERRABLE


def test_deferrable_row_reports_present_deferrable():
    """An already-fixed store. The run must no-op, not fail."""
    # Arrange
    row = ("task_comments_task_id_fkey", True)
    # Act
    obs = _observe(row)
    # Assert
    assert obs.shape is FKShape.PRESENT_DEFERRABLE


def test_constraint_found_under_a_different_name_is_still_present():
    """THE ISOLATING CASE for matching on table+column rather than name.

    PostgreSQL auto-names an inline REFERENCES as <table>_<column>_fkey, which
    is also the name a caller picks by convention -- so they usually coincide
    and a name-matching probe would look correct. It is only wrong when they
    differ, and then it reports ABSENT for a constraint that is plainly there
    and adds a duplicate alongside it.
    """
    # Arrange
    row = ("some_other_name_the_schema_chose", False)
    # Act
    obs = _observe(row, intended="task_comments_task_id_fkey")
    # Assert
    assert obs.shape is FKShape.PRESENT_NOT_DEFERRABLE


def test_the_name_actually_found_is_reported():
    """A caller must be able to see that its intended name was not the one there."""
    # Arrange
    row = ("some_other_name_the_schema_chose", False)
    # Act
    obs = _observe(row, intended="task_comments_task_id_fkey")
    # Assert
    assert obs.name == "some_other_name_the_schema_chose"


def test_absent_reports_the_intended_name():
    """With nothing found, the name a later run will look for is the intended one."""
    # Arrange
    row = None
    # Act
    obs = _observe(row, intended="task_comments_task_id_fkey")
    # Assert
    assert obs.name == "task_comments_task_id_fkey"


def test_shape_is_not_boolean_collapsible():
    """PRESENT_NOT_DEFERRABLE and ABSENT need DIFFERENT statements."""
    # Arrange
    absent = _observe(None).shape
    # Act
    present = _observe(("x", False)).shape
    # Assert
    assert absent is not present
