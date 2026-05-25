#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._BaseMixins._BaseConnectionMixin.

The abstract base mixin owns the only non-NotImplementedError surface
in the _BaseMixins package: __init__ wires two threading.Lock instances
and the (conn, cursor) pair to None, and __enter__ returns self so the
context-manager protocol works for any concrete subclass.

Real objects only — no mocks. Single-assert / AAA-marked / >=3 word-
tokens after test_ (STX-TQ001/TQ002/TQ003/TQ007 clean).
"""

from __future__ import annotations

import threading

from scitex_db._BaseMixins._BaseConnectionMixin import _BaseConnectionMixin

# ----------------------------------------------------------------------------
# __init__ wires the synchronization + connection slots
# ----------------------------------------------------------------------------


def test_init_creates_lock_attribute_as_thread_lock():
    # Arrange
    sentinel_type = type(threading.Lock())
    # Act
    mixin = _BaseConnectionMixin()
    # Assert
    assert isinstance(mixin.lock, sentinel_type)


def test_init_creates_maintenance_lock_attribute_as_thread_lock():
    # Arrange
    sentinel_type = type(threading.Lock())
    # Act
    mixin = _BaseConnectionMixin()
    # Assert
    assert isinstance(mixin._maintenance_lock, sentinel_type)


def test_init_assigns_distinct_lock_and_maintenance_lock_instances():
    # Arrange
    mixin = _BaseConnectionMixin()
    # Act
    same_object = mixin.lock is mixin._maintenance_lock
    # Assert
    assert same_object is False


def test_init_sets_conn_attribute_to_none():
    # Arrange
    cls = _BaseConnectionMixin
    # Act
    mixin = cls()
    # Assert
    assert mixin.conn is None


def test_init_sets_cursor_attribute_to_none():
    # Arrange
    cls = _BaseConnectionMixin
    # Act
    mixin = cls()
    # Assert
    assert mixin.cursor is None


# ----------------------------------------------------------------------------
# Context-manager protocol
# ----------------------------------------------------------------------------


def test_enter_returns_the_same_mixin_instance():
    # Arrange
    mixin = _BaseConnectionMixin()
    # Act
    entered = mixin.__enter__()
    # Assert
    assert entered is mixin
