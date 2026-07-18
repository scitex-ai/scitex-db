#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the scitex-db post-save / post-load observer registry.

Real-collaborator tests against an on-disk SQLite database — no mocks.
Hooks are recorded into plain lists, so what is asserted is the actual
dispatch scitex-db performs, not a stubbed stand-in.

Each test exercises a single behaviour with one assertion in the
AAA-marker shape required by STX-TQ001/TQ002/TQ003/TQ007.
"""

import os
import shutil
import sys
import tempfile

import pytest

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from scitex_db import SQLite3  # noqa: E402
from scitex_db import _observers  # noqa: E402


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases."""
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)


@pytest.fixture
def db_path(temp_dir):
    """Get a temporary database path."""
    return os.path.join(temp_dir, "test.db")


@pytest.fixture(autouse=True)
def clean_registry():
    """Isolate each test from the module-global hook registry.

    The registry is process-wide by design (observers self-register on
    import), so without this a leaked hook would silently contaminate
    every later test.
    """
    saved_save = list(_observers._post_save_hooks)
    saved_load = list(_observers._post_load_hooks)
    _observers._post_save_hooks.clear()
    _observers._post_load_hooks.clear()
    yield
    _observers._post_save_hooks[:] = saved_save
    _observers._post_load_hooks[:] = saved_load


# ----------------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------------


def test_register_post_save_hook_appends_to_registry():
    # Arrange
    def hook(db_path, query, parameters):
        pass

    # Act
    _observers.register_post_save_hook(hook)

    # Assert
    assert _observers._post_save_hooks == [hook]


def test_register_post_load_hook_appends_to_registry():
    # Arrange
    def hook(db_path, query, result):
        pass

    # Act
    _observers.register_post_load_hook(hook)

    # Assert
    assert _observers._post_load_hooks == [hook]


def test_hooks_are_exposed_on_the_package_root():
    # Arrange
    import scitex_db

    # Act
    exported = hasattr(scitex_db, "register_post_save_hook") and hasattr(
        scitex_db, "register_post_load_hook"
    )

    # Assert
    assert exported


# ----------------------------------------------------------------------------
# Write dispatch
# ----------------------------------------------------------------------------


def test_insert_fires_post_save_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("a",))

    # Assert
    assert any(q.startswith("INSERT") for q in seen)


def test_post_save_hook_receives_the_db_path(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(path)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    # Assert
    assert seen[0] == db_path


def test_post_save_hook_receives_the_parameters(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(params)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("payload",))

    # Assert
    assert list(seen[-1]) == ["payload"]


def test_executemany_fires_post_save_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.executemany(
            "INSERT INTO t (v) VALUES (?)", [("a",), ("b",)]
        )

    # Assert
    assert any(q.startswith("INSERT") for q in seen)


def test_executescript_fires_post_save_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY);")

    # Assert
    assert len(seen) == 1


# ----------------------------------------------------------------------------
# Read dispatch
# ----------------------------------------------------------------------------


def test_select_fires_post_load_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_load_hook(
        lambda path, query, result: seen.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        db.execute("SELECT * FROM t")

    # Assert
    assert any(q.startswith("SELECT") for q in seen)


def test_select_does_not_fire_post_save_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        seen.clear()
        db.execute("SELECT * FROM t")

    # Assert
    assert seen == []


def test_get_rows_fires_post_load_hook(db_path):
    """get_rows historically bypassed the dispatch point via
    self.cursor.execute; it must now be observable."""
    # Arrange
    seen = []
    _observers.register_post_load_hook(
        lambda path, query, result: seen.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("a",))
        db.get_rows("t")

    # Assert
    assert any("SELECT" in q for q in seen)


def test_get_rows_still_returns_its_data_after_routing_change(db_path):
    """Routing get_rows through self.execute must not consume the cursor."""
    # Arrange
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("a",))

        # Act
        rows = db.get_rows("t", return_as="list")

    # Assert
    assert len(rows) == 1


# ----------------------------------------------------------------------------
# Isolation: a bad observer must never break the host
# ----------------------------------------------------------------------------


def test_raising_post_save_hook_does_not_break_the_write(db_path):
    # Arrange
    def bad_hook(path, query, params):
        raise RuntimeError("observer is broken")

    _observers.register_post_save_hook(bad_hook)

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("a",))
        rows = db.get_rows("t", return_as="list")

    # Assert
    assert len(rows) == 1


def test_raising_post_load_hook_does_not_break_the_read(db_path):
    # Arrange
    def bad_hook(path, query, result):
        raise RuntimeError("observer is broken")

    _observers.register_post_load_hook(bad_hook)

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("a",))
        rows = db.get_rows("t", return_as="list")

    # Assert
    assert len(rows) == 1


def test_hooks_fire_in_registration_order(db_path):
    # Arrange
    order = []
    _observers.register_post_save_hook(
        lambda path, query, params: order.append("first")
    )
    _observers.register_post_save_hook(
        lambda path, query, params: order.append("second")
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    # Assert
    assert order == ["first", "second"]


def test_a_failing_hook_does_not_stop_later_hooks(db_path):
    # Arrange
    reached = []

    def bad_hook(path, query, params):
        raise RuntimeError("observer is broken")

    _observers.register_post_save_hook(bad_hook)
    _observers.register_post_save_hook(
        lambda path, query, params: reached.append(query)
    )

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

    # Assert
    assert len(reached) == 1


def test_no_registered_hooks_leaves_writes_working(db_path):
    # Arrange
    assert _observers._post_save_hooks == []

    # Act
    with SQLite3(db_path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        db.execute("INSERT INTO t (v) VALUES (?)", ("a",))
        rows = db.get_rows("t", return_as="list")

    # Assert
    assert len(rows) == 1


# EOF
