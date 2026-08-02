#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests that teardown survives an object whose __init__ never finished.

Different precondition from `test__SQLite3_close_is_total.py`. That file covers
teardown surviving its own FAILURE. This one covers teardown surviving never
having been SET UP: `__init__` can raise before `_ConnectionMixin.__init__`
assigns `self.cursor` / `self.conn`, and `__del__` then calls `close()` on the
half-built object.

The reachable route is a plain caller mistake -- a mistyped `mode=` -- so the
user's one error produced two tracebacks, the louder of which named an attribute
they have never heard of.

The half-built object is produced by the real constructor failing, not by
deleting attributes off a good instance: the point is that this state is what
the class actually hands to `__del__`.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile

import pytest

from scitex_db._sqlite3._SQLite3 import SQLite3


@pytest.fixture
def path():
    tmpdir = tempfile.mkdtemp()
    yield os.path.join(tmpdir, "store.db")
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def half_constructed(path):
    """An instance whose __init__ raised before the handles were assigned."""
    instance = SQLite3.__new__(SQLite3)
    with pytest.raises(ValueError):
        instance.__init__(path, mode="not-a-mode")
    return instance


@pytest.fixture
def unraisables_from_a_rejected_construction(path):
    """Whatever `__del__` throws after the constructor rejects a `mode=`.

    THIS IS THE THIRD SHAPE OF THIS TEST, and the first two were both green
    against the unfixed source -- worth recording, because each was wrong for a
    different reason and both looked like evidence.

    Attempt 1 read stderr after `with pytest.raises(...)`. `raises` keeps the
    ExceptionInfo, the traceback keeps the frame, and the frame keeps the
    half-built object ALIVE -- so stderr was read while the destructor was still
    pending. Nothing had happened yet.

    Attempt 2 fixed the lifetime with `try/except` + `gc.collect()` and still
    passed, because pytest installs its own `sys.unraisablehook`: the destructor
    DID raise, and pytest turned it into a `PytestUnraisableExceptionWarning`
    instead of letting it reach stderr. The check was looking at a channel the
    thing it measured no longer travels on.

    So observe the destructor DIRECTLY. `sys.unraisablehook` is where an
    exception from `__del__` actually goes; capturing it cannot be satisfied by
    anything except the destructor staying quiet.
    """
    captured = []
    previous = sys.unraisablehook
    sys.unraisablehook = captured.append
    try:
        try:
            SQLite3(path, mode="not-a-mode")
        except ValueError:
            pass
        gc.collect()
    finally:
        sys.unraisablehook = previous
    return captured


def test_the_constructor_still_rejects_a_bad_mode(path):
    # Arrange
    bad = "not-a-mode"
    # Act
    raises = pytest.raises(ValueError, match="mode must be one of")
    # Assert
    with raises:
        SQLite3(path, mode=bad)


def test_close_on_a_half_constructed_object_does_not_raise(half_constructed):
    # Was AttributeError: 'SQLite3' object has no attribute 'cursor'.
    # Arrange
    instance = half_constructed
    # Act
    instance.close()
    # Assert
    assert instance.conn is None


def test_close_on_a_half_constructed_object_clears_the_cursor(half_constructed):
    # Arrange
    instance = half_constructed
    # Act
    instance.close()
    # Assert
    assert instance.cursor is None


def test_close_on_a_half_constructed_object_is_repeatable(half_constructed):
    # __del__ may run after an explicit close(); the second call must be quiet.
    # Arrange
    instance = half_constructed
    instance.close()
    # Act
    instance.close()
    # Assert
    assert instance.conn is None


def test_a_rejected_construction_leaves_the_destructor_silent(
    unraisables_from_a_rejected_construction,
):
    # The user-visible damage: one mistake, two errors, the loud one wrong.
    # Arrange
    captured = unraisables_from_a_rejected_construction
    # Act
    kinds = [type(u.exc_value).__name__ for u in captured]
    # Assert
    assert kinds == []


def test_a_bare_new_instance_can_be_closed():
    # `__new__` with no `__init__` at all -- the widest form of the same state.
    # Arrange
    instance = SQLite3.__new__(SQLite3)
    # Act
    instance.close()
    # Assert
    assert instance.conn is None


def test_a_normal_instance_leaves_no_handle_after_close(path):
    # Positive control: the getattr reads must not stop teardown from working.
    # Arrange
    db = SQLite3(path)
    db._context_manager_used = True
    # Act
    db.close()
    # Assert
    assert db.conn is None


def test_a_normal_instance_leaves_no_cursor_after_close(path):
    # Arrange
    db = SQLite3(path)
    db._context_manager_used = True
    # Act
    db.close()
    # Assert
    assert db.cursor is None

# EOF
