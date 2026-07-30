#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._transform.

Real SQLite stores holding a real NUL byte, written as ``char(0)`` rather than
as a quoted literal -- a literal would put the byte in this file and git would
classify the test suite as binary, which is the defect the module exists to
handle. scitex-cards hit exactly that in the first draft of their own guard.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._plan import Disposition, TablePlan
from scitex_db._migrate._preflight import preflight
from scitex_db._migrate._transform import (
    NUL,
    NUL_REPLACEMENT,
    TransformationError,
    Transformations,
    escape_nuls,
    plan_nul_escapes,
)

DISPOSITIONS = {"notes": TablePlan("notes", Disposition.MIGRATE)}


@pytest.fixture
def store():
    """Two rows with NULs and one without."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "store.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO notes VALUES ('clean', 'ordinary text')")
    conn.execute("INSERT INTO notes VALUES ('a', 'has ' || char(0) || ' one')")
    conn.execute(
        "INSERT INTO notes VALUES ('b', char(0) || 'two' || char(0) || 'here')"
    )
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
# The rule
# ----------------------------------------------------------------------------


def test_escape_nuls_replaces_every_occurrence():
    # Arrange
    value = NUL + "middle" + NUL
    # Act
    escaped = escape_nuls(value)
    # Assert
    assert escaped == NUL_REPLACEMENT + "middle" + NUL_REPLACEMENT


def test_escape_nuls_leaves_bytes_untouched():
    # A BLOB may hold 0x00 legitimately and migrates to BYTEA, which accepts it.
    # Arrange
    value = b"\x00binary"
    # Act
    escaped = escape_nuls(value)
    # Assert
    assert escaped == value


def test_the_module_source_contains_no_literal_nul():
    # The module about the byte must not contain the byte: git would classify
    # it as binary, which is the exact defect the original rows were discussing.
    # Arrange
    from scitex_db._migrate import _transform

    # Act
    source = open(_transform.__file__, "rb").read()
    # Assert
    assert b"\x00" not in source


# ----------------------------------------------------------------------------
# The declaration
# ----------------------------------------------------------------------------


def test_plan_nul_escapes_finds_every_affected_row(store):
    # Every one, not a sample: this is the set the copy is permitted to change,
    # so a capped list would leave the remainder to raise mid-run.
    # Arrange
    source = store
    # Act
    declared = plan_nul_escapes(source, DISPOSITIONS, stated_by="test")
    # Assert
    assert len(declared.escapes) == 2


def test_plan_nul_escapes_records_the_original_bytes_as_hex(store):
    # Hex, not text: a manifest holding the original as text would carry the
    # NUL and re-block the destination -- the same trap one level in.
    # Arrange
    source = store
    # Act
    declared = plan_nul_escapes(source, DISPOSITIONS, stated_by="test")
    escape = next(e for e in declared.escapes if e.key == ("a",))
    # Assert
    assert bytes.fromhex(escape.original_hex).decode("utf-8").count(NUL) == 1


def test_plan_nul_escapes_names_the_row_not_just_the_column(store):
    # A declaration that said only "two rows in notes.body" could not detect
    # that the rows met during the copy differ from the ones declared.
    # Arrange
    source = store
    # Act
    declared = plan_nul_escapes(source, DISPOSITIONS, stated_by="test")
    # Assert
    assert sorted(e.key for e in declared.escapes) == [("a",), ("b",)]


def test_transformations_refuses_to_be_declared_by_nobody():
    # Altering a stored value is the one thing this tool will not do on its
    # own, so the marker has to record who authorised it.
    # Arrange
    escapes = ()
    # Act
    build = Transformations
    # Assert
    with pytest.raises(TransformationError, match="declared by nobody"):
        build(escapes=escapes, stated_by="   ")


# ----------------------------------------------------------------------------
# The preflight gate -- default is still refusal
# ----------------------------------------------------------------------------


def test_a_nul_column_still_blocks_without_a_declaration(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert report.ok is False


def test_a_fully_declared_nul_column_no_longer_blocks(store):
    # Arrange
    source = store
    declared = plan_nul_escapes(source, DISPOSITIONS, stated_by="test")
    # Act
    report = preflight(source, DISPOSITIONS, declared)
    # Assert
    assert report.ok is True


def test_a_partially_declared_nul_column_still_blocks(store):
    # Partial coverage must block: the undeclared remainder would raise
    # mid-copy, which is the late failure the preflight exists to prevent.
    # Arrange
    source = store
    full = plan_nul_escapes(source, DISPOSITIONS, stated_by="test")
    partial = Transformations(escapes=full.escapes[:1], stated_by="test")
    # Act
    report = preflight(source, DISPOSITIONS, partial)
    # Assert
    assert report.ok is False


# ----------------------------------------------------------------------------
# Applying it -- and refusing what was not declared
# ----------------------------------------------------------------------------


def test_apply_escapes_a_declared_value(store):
    # Arrange
    declared = plan_nul_escapes(store, DISPOSITIONS, stated_by="test")
    # Act
    result = declared.apply("notes", ("a",), "body", "has " + NUL + " one")
    # Assert
    assert result == "has " + NUL_REPLACEMENT + " one"


def test_apply_refuses_a_nul_in_an_undeclared_row(store):
    # A NUL in a row nobody declared means the source changed after the
    # preflight. Continuing would silently widen an enumerable exception.
    # Arrange
    declared = plan_nul_escapes(store, DISPOSITIONS, stated_by="test")
    # Act
    apply = declared.apply
    # Assert
    with pytest.raises(TransformationError, match="no .*transformation was declared"):
        apply("notes", ("brand_new",), "body", "surprise " + NUL)


def test_apply_leaves_a_value_without_a_nul_alone(store):
    # Arrange
    declared = plan_nul_escapes(store, DISPOSITIONS, stated_by="test")
    # Act
    result = declared.apply("notes", ("a",), "body", "nothing to do")
    # Assert
    assert result == "nothing to do"


# ----------------------------------------------------------------------------
# The manifest
# ----------------------------------------------------------------------------


def test_the_manifest_names_the_rule_that_was_applied(store):
    # Arrange
    declared = plan_nul_escapes(store, DISPOSITIONS, stated_by="test")
    # Act
    manifest = declared.manifest()
    # Assert
    assert {entry["rule"] for entry in manifest} == {"nul->U+2400"}


def test_the_summary_states_who_declared_the_change(store):
    # Arrange
    declared = plan_nul_escapes(store, DISPOSITIONS, stated_by="an-operator")
    # Act
    summary = declared.summary()
    # Assert
    assert "an-operator" in summary


# EOF
