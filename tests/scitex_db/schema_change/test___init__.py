#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The export list is a promise, so it is checked rather than trusted.

WHY THIS FILE EXISTS. On 2026-08-11 scitex-cards asked whether
``add_deferrable_fk`` was importable so their migration rung could CALL it
instead of writing a second copy of the one-transaction discipline. It was not:
PRs #78 and #79 shipped the code, the tests and the mutation coverage, and never
imported either module into the package. Nothing failed, because nothing here
looked.

Worse, I had already written into a shared design record that ``OrphansFound``
was "an exported type". Another agent was about to write that import against an
08-13 commitment. The claim was about my OWN package, made confidently because I
had just written the code -- proximity felt like knowledge, and no amount of
"state inferences as inferences" would have caught it. Only asking the package
would.

THE SECOND TRAP IS THE ONE THAT NEEDS A MACHINE. The module docstring carried
its own export list, and it repeated the omission exactly, because it was
written from the same belief. So the docstring and ``__all__`` AGREED, and their
agreement proved nothing: two artifacts confirming each other is not two
witnesses when one was copied from the other. That is not a thing a reader
catches by being careful -- it looks like corroboration. It is mechanically
checkable, so it is checked here.
"""

from __future__ import annotations

import importlib

import pytest

import scitex_db.schema_change as schema_change

#: Names the module promises. Kept here, spelled out, rather than derived from
#: ``__all__`` -- a test that reads its subject's own answer back to it cannot
#: fail. Deleting a name from ``__all__`` must turn this file red, which it
#: cannot do if it asks ``__all__`` what to expect.
PROMISED = {
    "preflight",
    "Report",
    "Finding",
    "Status",
    "Check",
    "ArtifactProbe",
    "PositiveControl",
    "ExpectedFailure",
    "measure_lock_cost",
    "LockCost",
    "RefusedToLockLiveStore",
    "add_deferrable_fk",
    "OrphansFound",
    "observe_fk",
    "FKShape",
    "FKObservation",
}


@pytest.mark.parametrize("name", sorted(PROMISED))
def test_every_promised_name_is_actually_reachable(name):
    """The exact failure that shipped twice: exported in spirit, absent in fact."""
    # Arrange
    module = schema_change
    # Act
    present = hasattr(module, name)
    # Assert
    assert present, f"{name} is promised but not on scitex_db.schema_change"


@pytest.mark.parametrize("name", sorted(PROMISED))
def test_every_promised_name_is_declared_in_all(name):
    """Reachable-but-undeclared is a name callers cannot rely on."""
    # Arrange
    declared = set(schema_change.__all__)
    # Act
    is_declared = name in declared
    # Assert
    assert is_declared, f"{name} is reachable but missing from __all__"


def test_all_declares_nothing_beyond_the_promise():
    """Catches a name added to ``__all__`` without being added to the promise."""
    # Arrange
    declared = set(schema_change.__all__)
    # Act
    undeclared_here = declared - PROMISED
    # Assert
    assert not undeclared_here, f"in __all__ but not promised here: {undeclared_here}"


def test_the_fk_primitive_is_importable_the_way_another_package_would_write_it():
    """The literal line scitex-cards would have written, as a test.

    Not redundant with the reachability check above: that one asks the module
    object this test already imported. This one performs the import a CALLER
    performs, from the public path, which is the thing that was broken.
    """
    # Arrange
    module = importlib.import_module("scitex_db.schema_change")
    # Act
    imported = (module.add_deferrable_fk, module.OrphansFound)
    # Assert
    assert all(obj is not None for obj in imported)


def test_the_private_name_is_gone_rather_than_left_as_a_second_door():
    """One public path, not a public path beside the private one it replaced.

    An alias would let a caller keep importing ``_schema_change`` and never
    learn the boundary moved -- and nothing outside this module ever imported
    the private path, so there is no migration to stage. Alias-then-remove is
    for a PUBLISHED contract; this one was never published, which is precisely
    the defect being fixed.
    """
    # Arrange
    old_path = "scitex_db._schema_change"
    # Act
    act = lambda: importlib.import_module(old_path)
    # Assert
    with pytest.raises(ModuleNotFoundError):
        act()
