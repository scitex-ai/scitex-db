#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for caller-declared schema-object exclusions.

`declined` is a third state alongside `carried` and `uncarried`, and the
distinction is the point: `uncarried` means nobody decided, `declined` means
someone looked and said no, with a reason, on the record.

The case it exists for is real: scitex-cards GENERATES the PostgreSQL form of
their guards from a running server, so a translated copy would be an inferior
duplicate of a better one. Translating it anyway would be worse than declining.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile

import pytest

from scitex_db._migrate._plan import Disposition, MigrationPlanError, TablePlan
from scitex_db._migrate._preflight import preflight

DISPOSITIONS = {"t": TablePlan("t", Disposition.MIGRATE)}
REASON = "ported natively; generated from a running PostgreSQL server"


@pytest.fixture
def store():
    """A store whose trigger uses a form the translator does not handle."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "store.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES ('a', '1')")
    conn.execute(
        "CREATE TRIGGER exotic AFTER UPDATE OF v ON t FOR EACH ROW "
        "WHEN CAST(NEW.v AS INTEGER) < CAST(OLD.v AS INTEGER) "
        "BEGIN UPDATE t SET v = OLD.v WHERE id = NEW.id; END"
    )
    conn.commit()
    conn.close()
    yield path
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_an_untranslatable_trigger_blocks_by_default(store):
    # The control: without a declared exclusion this must still refuse, or the
    # feature would be a way to make problems disappear rather than decide them.
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS)
    # Assert
    assert report.ok is False


def test_a_declined_object_no_longer_blocks(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS, None, {"exotic": REASON})
    # Assert
    assert report.ok is True


def test_a_declined_object_leaves_uncarried_empty(store):
    # It must move OUT of uncarried, not merely stop counting -- otherwise the
    # report still says something is unaccounted for.
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS, None, {"exotic": REASON})
    # Assert
    assert report.uncarried == ()


def test_a_declined_object_is_recorded_with_its_reason(store):
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS, None, {"exotic": REASON})
    # Assert
    assert report.declined[0][1] == REASON


def test_a_declined_object_is_not_applied_to_the_destination(store):
    # Declining means the destination does NOT get a translated copy.
    # Arrange
    source = store
    # Act
    report = preflight(source, DISPOSITIONS, None, {"exotic": REASON})
    # Assert
    assert "exotic" not in [o.name for o in report.carried]


def test_the_summary_states_the_decline_and_the_reason(store):
    # Printed, because an absent trigger with no explanation is
    # indistinguishable from one that was lost.
    # Arrange
    source = store
    # Act
    summary = preflight(source, DISPOSITIONS, None, {"exotic": REASON}).summary()
    # Assert
    assert "DECLINED by the caller" in summary


def test_an_exclusion_matching_nothing_is_refused(store):
    # A stale exclusion is dangerous in the QUIET direction: if the object was
    # renamed, the rename is now uncarried while the exclusion protects nothing.
    # Arrange
    source = store
    # Act
    run = preflight
    # Assert
    with pytest.raises(MigrationPlanError, match="do not exist in this source"):
        run(source, DISPOSITIONS, None, {"renamed_away": REASON})


# EOF
