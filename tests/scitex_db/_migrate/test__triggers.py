#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for scitex_db._migrate._triggers.

The inputs are the REAL trigger SQL from the live scitex-cards store (the five
append-only guards) plus the agreed revision-bump shape, rather than invented
examples — a translator tested only against SQL its author also wrote proves
the author is self-consistent, not that it handles the store.

The refusal tests carry as much weight as the translations: an unrecognised
trigger must fail loudly, because a plausible-looking mistranslation enforces
something different from the source and no row comparison would catch it.

No mocks. One assertion per test, AAA markers.
"""

from __future__ import annotations

import pytest

from scitex_db._migrate._introspect import SchemaObject
from scitex_db._migrate._triggers import TriggerTranslationError, translate_trigger

# Verbatim from the live store.
NO_DELETE = SchemaObject(
    name="dm_threads_no_delete",
    table="dm_threads",
    kind="trigger",
    sql=(
        "CREATE TRIGGER dm_threads_no_delete\n"
        "BEFORE DELETE ON dm_threads BEGIN\n"
        "    SELECT RAISE(ABORT, 'dm_threads is append-only: rows are never removed');\n"
        "END"
    ),
)

IMMUTABLE = SchemaObject(
    name="dm_messages_immutable",
    table="dm_messages",
    kind="trigger",
    sql=(
        "CREATE TRIGGER dm_messages_immutable\n"
        "BEFORE UPDATE ON dm_messages\n"
        "WHEN OLD.thread_id   IS NOT NEW.thread_id\n"
        "  OR OLD.sender      IS NOT NEW.sender\n"
        "  OR OLD.body        IS NOT NEW.body\n"
        "BEGIN\n"
        "    SELECT RAISE(ABORT,\n"
        "        'dm_messages rows are immutable except deleted_at/deleted_by');\n"
        "END"
    ),
)

# The shape scitex-cards settled on for the optimistic-lock counter.
BUMP = SchemaObject(
    name="tasks_bump_revision",
    table="tasks",
    kind="trigger",
    sql=(
        "CREATE TRIGGER tasks_bump_revision AFTER UPDATE ON tasks\n"
        "  FOR EACH ROW WHEN NEW.revision = OLD.revision\n"
        "BEGIN\n"
        "  UPDATE tasks SET revision = OLD.revision + 1 WHERE id = NEW.id;\n"
        "END"
    ),
)


# ----------------------------------------------------------------------------
# Guards -- one SQLite object becomes a FUNCTION plus a TRIGGER
# ----------------------------------------------------------------------------


def test_a_delete_guard_emits_a_plpgsql_function():
    # Arrange
    obj = NO_DELETE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert 'CREATE OR REPLACE FUNCTION "dm_threads_no_delete_fn"()' in sql


def test_a_delete_guard_raises_an_exception_rather_than_raise_abort():
    # Arrange -- PostgreSQL has no RAISE(ABORT, ...) expression
    obj = NO_DELETE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert "RAISE EXCEPTION 'dm_threads is append-only: rows are never removed'" in sql


def test_a_delete_guard_keeps_its_timing_and_event():
    # Arrange
    obj = NO_DELETE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert 'BEFORE DELETE ON "dm_threads"' in sql


def test_a_delete_guard_binds_the_trigger_to_its_function():
    # Arrange -- a function without its trigger silently enforces nothing
    obj = NO_DELETE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert 'EXECUTE FUNCTION "dm_threads_no_delete_fn"()' in sql


def test_a_conditional_guard_keeps_its_when_clause():
    # Arrange
    obj = IMMUTABLE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert "WHEN (" in sql


def test_sqlite_is_not_becomes_is_distinct_from():
    # Arrange -- SQLite's `IS NOT` between values is NULL-safe inequality.
    # `<>` would stop firing when either side is NULL, silently weakening the
    # immutability guard exactly where a column became or stopped being NULL.
    # Asserted on the operator alone: the source aligns its columns with runs
    # of spaces, and pinning those would make this test about the source's
    # formatting rather than about the translation.
    obj = IMMUTABLE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert "IS NOT NEW." not in sql


def test_every_is_not_comparison_is_translated_not_just_the_first():
    # Arrange -- the guard lists three columns; translating only the first
    # would leave a condition that still parses and fires less often
    obj = IMMUTABLE
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert sql.count("IS DISTINCT FROM") == 3


def test_an_already_escaped_message_is_not_escaped_twice():
    # Arrange -- REGRESSION. A single-quoted SQLite literal already doubles its
    # internal quote, and PostgreSQL uses the same convention. Re-escaping
    # produced 'don''''t' — a mangled error message that still COMPILES, so
    # nothing downstream would have complained.
    obj = SchemaObject(
        name="t_guard",
        table="t",
        kind="trigger",
        sql="CREATE TRIGGER t_guard BEFORE DELETE ON t BEGIN "
        "SELECT RAISE(ABORT, 'don''t remove rows'); END",
    )
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert "RAISE EXCEPTION 'don''t remove rows'" in sql


def test_a_double_quoted_message_gets_its_quotes_escaped():
    # Arrange -- the other half: a double-quoted source literal holds RAW
    # single quotes, which must be doubled before landing in a single-quoted
    # PostgreSQL literal or the string ends early and the DDL fails to parse
    obj = SchemaObject(
        name="t_guard",
        table="t",
        kind="trigger",
        sql='CREATE TRIGGER t_guard BEFORE DELETE ON t BEGIN '
        "SELECT RAISE(ABORT, \"don't remove rows\"); END",
    )
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert "RAISE EXCEPTION 'don''t remove rows'" in sql


# ----------------------------------------------------------------------------
# The self-bumping counter -- meaning preserved, structure deliberately not
# ----------------------------------------------------------------------------


def test_the_bump_trigger_becomes_before_update_not_after():
    # Arrange -- SQLite uses AFTER only because BEFORE cannot assign to NEW
    obj = BUMP
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert 'BEFORE UPDATE ON "tasks"' in sql


def test_the_bump_trigger_assigns_instead_of_nesting_an_update():
    # Arrange -- reproducing the nested UPDATE would cost a second write per row
    obj = BUMP
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert 'NEW."revision" := OLD."revision" + 1;' in sql


def test_the_bump_trigger_keeps_the_guard_as_a_conditional():
    # Arrange -- THE ONE THAT MATTERS. `WHEN NEW.c = OLD.c` means "only bump if
    # the caller did not set it". Assigning unconditionally would overwrite the
    # value a lock-holding writer supplied, turning optimistic locking into
    # silent last-write-wins.
    obj = BUMP
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert 'IF NEW."revision" = OLD."revision" THEN' in sql


def test_the_bump_trigger_returns_new():
    # Arrange -- a BEFORE row trigger returning NULL SKIPS the update entirely,
    # so the write would vanish with no error
    obj = BUMP
    # Act
    sql = translate_trigger(obj)
    # Assert
    assert "RETURN NEW;" in sql


# ----------------------------------------------------------------------------
# Refusals -- an unfamiliar body must not be guessed at
# ----------------------------------------------------------------------------


def test_an_unrecognised_trigger_body_is_refused():
    # Arrange -- a body that does real work, not a guard or a bump
    obj = SchemaObject(
        name="t_audit",
        table="t",
        kind="trigger",
        sql="CREATE TRIGGER t_audit AFTER INSERT ON t BEGIN "
        "INSERT INTO audit_log (what) VALUES ('inserted'); END",
    )
    # Act
    translator = translate_trigger
    # Assert
    with pytest.raises(TriggerTranslationError, match="not a recognised trigger form"):
        translator(obj)


def test_the_refusal_includes_the_original_sql():
    # Arrange -- the next step is a human reading the original
    obj = SchemaObject(
        name="t_audit",
        table="t",
        kind="trigger",
        sql="CREATE TRIGGER t_audit AFTER INSERT ON t BEGIN SELECT hand_written(); END",
    )
    # Act
    translator = translate_trigger
    # Assert
    with pytest.raises(TriggerTranslationError, match="hand_written"):
        translator(obj)


def test_a_non_trigger_object_is_refused():
    # Arrange -- indexes are carried by a different path
    obj = SchemaObject(
        name="idx_t_id", table="t", kind="index", sql="CREATE INDEX idx_t_id ON t (id)"
    )
    # Act
    translator = translate_trigger
    # Assert
    with pytest.raises(TriggerTranslationError, match="not a trigger"):
        translator(obj)


# EOF
