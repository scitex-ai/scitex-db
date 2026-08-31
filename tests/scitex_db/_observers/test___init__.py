#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the scitex-db post-save / post-load observer registry.

Real-collaborator tests against the registry itself — no mocks. Hooks
are plain functions recording into plain lists, and the dispatch under
test is the module's own ``fire_post_save`` / ``fire_post_load``, so
what is asserted is the actual dispatch scitex-db performs rather than
a stubbed stand-in.

Each test exercises a single behaviour with one assertion in the
AAA-marker shape required by STX-TQ001/TQ002/TQ003/TQ007.
"""

import os
import sys
from pathlib import Path

import pytest

# Add src to path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from scitex_db import _observers  # noqa: E402


@pytest.fixture
def db_path():
    """A store path to hand the dispatcher.

    The registry never opens it — ``db_path`` is carried through to the
    hook as provenance, so a plain path is the honest collaborator.
    """
    return Path("/tmp/scitex-db-observers/test.db")


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


def test_fire_post_save_invokes_a_registered_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(query)
    )

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (1)", None)

    # Assert
    assert seen == ["INSERT INTO t VALUES (1)"]


def test_fire_post_save_passes_the_store_path_through(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(path)
    )

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (1)", None)

    # Assert
    assert seen == [db_path]


def test_fire_post_save_passes_the_parameters_through(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(
        lambda path, query, params: seen.append(params)
    )

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (%s)", (1,))

    # Assert
    assert seen == [(1,)]


def test_fire_post_save_invokes_hooks_in_registration_order(db_path):
    # Arrange
    order = []
    _observers.register_post_save_hook(lambda p, q, x: order.append("first"))
    _observers.register_post_save_hook(lambda p, q, x: order.append("second"))

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (1)", None)

    # Assert
    assert order == ["first", "second"]


def test_fire_post_save_does_not_run_load_hooks(db_path):
    # Arrange
    seen = []
    _observers.register_post_load_hook(lambda p, q, r: seen.append(q))

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (1)", None)

    # Assert
    assert seen == []


# ----------------------------------------------------------------------------
# Read dispatch
# ----------------------------------------------------------------------------


def test_fire_post_load_invokes_a_registered_hook(db_path):
    # Arrange
    seen = []
    _observers.register_post_load_hook(lambda path, query, r: seen.append(query))

    # Act
    _observers.fire_post_load(db_path, "SELECT * FROM t", None)

    # Assert
    assert seen == ["SELECT * FROM t"]


def test_fire_post_load_passes_the_result_through(db_path):
    # Arrange
    seen = []
    _observers.register_post_load_hook(lambda path, query, r: seen.append(r))
    rows = [(1,), (2,)]

    # Act
    _observers.fire_post_load(db_path, "SELECT * FROM t", rows)

    # Assert
    assert seen == [rows]


def test_fire_post_load_does_not_run_save_hooks(db_path):
    # Arrange
    seen = []
    _observers.register_post_save_hook(lambda p, q, x: seen.append(q))

    # Act
    _observers.fire_post_load(db_path, "SELECT * FROM t", None)

    # Assert
    assert seen == []


# ----------------------------------------------------------------------------
# A misbehaving observer must never break the host's database access
# ----------------------------------------------------------------------------


def test_a_raising_post_save_hook_does_not_propagate(db_path):
    # Arrange
    def boom(path, query, params):
        raise RuntimeError("observer is broken")

    _observers.register_post_save_hook(boom)

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (1)", None)

    # Assert
    assert _observers._post_save_hooks == [boom]


def test_a_raising_post_save_hook_does_not_stop_later_hooks(db_path):
    # Arrange
    seen = []

    def boom(path, query, params):
        raise RuntimeError("observer is broken")

    _observers.register_post_save_hook(boom)
    _observers.register_post_save_hook(lambda p, q, x: seen.append(q))

    # Act
    _observers.fire_post_save(db_path, "INSERT INTO t VALUES (1)", None)

    # Assert
    assert seen == ["INSERT INTO t VALUES (1)"]


def test_a_raising_post_load_hook_does_not_propagate(db_path):
    # Arrange
    def boom(path, query, result):
        raise RuntimeError("observer is broken")

    _observers.register_post_load_hook(boom)

    # Act
    _observers.fire_post_load(db_path, "SELECT * FROM t", None)

    # Assert
    assert _observers._post_load_hooks == [boom]


# EOF
