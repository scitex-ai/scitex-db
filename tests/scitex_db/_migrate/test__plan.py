#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._plan.

The behaviour under test is mostly REFUSAL, which is the point: this module
exists so that a table nobody thought about fails the migration instead of being
skipped. "Excluded on purpose" and "nobody noticed" must not look alike
afterwards, because only one of them loses data.

Real values throughout, no mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import pytest

from scitex_db._migrate._plan import (
    CARDS_STORE_DISPOSITIONS,
    Disposition,
    MigrationPlanError,
    TablePlan,
    build_plan,
    exclusions,
    tables_to_migrate,
)


# ----------------------------------------------------------------------------
# TablePlan -- an exclusion must carry its reason
# ----------------------------------------------------------------------------


def test_table_plan_accepts_a_migrate_entry_without_a_reason():
    # Arrange
    table = "tasks"
    # Act
    plan = TablePlan(table, Disposition.MIGRATE)
    # Assert
    assert plan.migrates is True


def test_table_plan_refuses_an_exclusion_with_no_reason():
    # Arrange
    table = "mirror_hashes"
    # Act
    disposition = Disposition.EXCLUDE
    # Assert
    with pytest.raises(MigrationPlanError, match="no reason given"):
        TablePlan(table, disposition)


def test_table_plan_refuses_an_exclusion_whose_reason_is_only_whitespace():
    # Arrange -- a blank reason is not a reason
    table = "mirror_hashes"
    # Act
    disposition = Disposition.EXCLUDE
    # Assert
    with pytest.raises(MigrationPlanError, match="no reason given"):
        TablePlan(table, disposition, "   ")


def test_table_plan_marks_an_excluded_table_as_not_migrating():
    # Arrange
    table = "mirror_hashes"
    # Act
    plan = TablePlan(table, Disposition.EXCLUDE, "YAML-mirror-era bookkeeping")
    # Assert
    assert plan.migrates is False


# ----------------------------------------------------------------------------
# build_plan -- refuses a store it does not fully describe
# ----------------------------------------------------------------------------


def test_build_plan_pairs_every_source_table_with_its_disposition():
    # Arrange
    source = ["tasks", "task_comments"]
    dispositions = {
        "tasks": TablePlan("tasks", Disposition.MIGRATE),
        "task_comments": TablePlan("task_comments", Disposition.MIGRATE),
    }
    # Act
    plan = build_plan(source, dispositions)
    # Assert
    assert len(plan) == 2


def test_build_plan_orders_entries_by_table_name_for_reproducibility():
    # Arrange -- introspection order must not leak into the plan
    source = ["tasks", "dm_messages", "task_comments"]
    dispositions = {
        t: TablePlan(t, Disposition.MIGRATE)
        for t in ("tasks", "dm_messages", "task_comments")
    }
    # Act
    plan = build_plan(source, dispositions)
    # Assert
    assert [p.table for p in plan] == ["dm_messages", "task_comments", "tasks"]


def test_build_plan_refuses_a_source_table_it_has_no_disposition_for():
    # Arrange -- the case that would otherwise silently leave rows behind
    source = ["tasks", "brand_new_table"]
    dispositions = {"tasks": TablePlan("tasks", Disposition.MIGRATE)}
    # Act
    tables = list(source)
    # Assert
    with pytest.raises(MigrationPlanError, match="brand_new_table"):
        build_plan(tables, dispositions)


def test_build_plan_refuses_a_disposition_for_an_absent_table():
    # Arrange -- a stale or misspelled plan no longer describes this store
    source = ["tasks"]
    dispositions = {
        "tasks": TablePlan("tasks", Disposition.MIGRATE),
        "taskz": TablePlan("taskz", Disposition.MIGRATE),
    }
    # Act
    tables = list(source)
    # Assert
    with pytest.raises(MigrationPlanError, match="does not have"):
        build_plan(tables, dispositions)


# ----------------------------------------------------------------------------
# tables_to_migrate / exclusions -- the omission stays auditable
# ----------------------------------------------------------------------------


def test_tables_to_migrate_omits_excluded_tables():
    # Arrange
    plan = (
        TablePlan("tasks", Disposition.MIGRATE),
        TablePlan("mirror_hashes", Disposition.EXCLUDE, "no second store to mirror"),
    )
    # Act
    result = tables_to_migrate(plan)
    # Assert
    assert result == ("tasks",)


def test_exclusions_reports_what_was_deliberately_not_carried():
    # Arrange -- a summary listing only copies would read as complete
    plan = (
        TablePlan("tasks", Disposition.MIGRATE),
        TablePlan("mirror_hashes", Disposition.EXCLUDE, "no second store to mirror"),
    )
    # Act
    result = exclusions(plan)
    # Assert
    assert [p.table for p in result] == ["mirror_hashes"]


# ----------------------------------------------------------------------------
# CARDS_STORE_DISPOSITIONS -- the agreed decisions for the live store
# ----------------------------------------------------------------------------


def test_cards_store_excludes_mirror_hashes():
    # Arrange -- YAML-mirror bookkeeping, meaningless without a second store
    dispositions = CARDS_STORE_DISPOSITIONS
    # Act
    entry = dispositions["mirror_hashes"]
    # Assert
    assert entry.migrates is False


def test_cards_store_excludes_users_pending_the_broken_reader_fix():
    # Arrange -- empty because list_users raises on a SQLite store, not unused
    dispositions = CARDS_STORE_DISPOSITIONS
    # Act
    entry = dispositions["users"]
    # Assert
    assert entry.migrates is False


def test_cards_store_migrates_the_tasks_table():
    # Arrange
    dispositions = CARDS_STORE_DISPOSITIONS
    # Act
    entry = dispositions["tasks"]
    # Assert
    assert entry.migrates is True


def test_cards_store_every_exclusion_states_a_reason():
    # Arrange
    dispositions = CARDS_STORE_DISPOSITIONS
    # Act
    excluded = [p for p in dispositions.values() if not p.migrates]
    # Assert
    assert all(p.reason.strip() for p in excluded)


def test_cards_store_plan_covers_the_live_store_table_set():
    # Arrange -- the 15 non-internal tables present on 2026-07-30
    live_tables = [
        "tasks",
        "task_comments",
        "task_edges",
        "task_roles",
        "users",
        "user_names",
        "inbox_recipients",
        "notifications",
        "messages",
        "schema_meta",
        "mirror_hashes",
        "dm_threads",
        "dm_thread_member_events",
        "dm_messages",
        "dm_receipts",
    ]
    # Act
    plan = build_plan(live_tables)
    # Assert
    assert len(plan) == 15


def test_cards_store_plan_migrates_twelve_of_fifteen_tables():
    # Arrange -- three excluded: mirror_hashes, users, user_names
    live_tables = list(CARDS_STORE_DISPOSITIONS)
    # Act
    plan = build_plan(live_tables)
    # Assert
    assert len(tables_to_migrate(plan)) == 12


# EOF
