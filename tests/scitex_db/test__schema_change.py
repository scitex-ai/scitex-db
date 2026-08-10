#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for _schema_change.

Every property here was a real failure on this fleet on 2026-08-09, not a
hypothetical. Each test names the behaviour it pins so a single failing line in
CI says exactly what broke.
"""

from __future__ import annotations

import pytest

from scitex_db._schema_change import (
    LockCost,
    RefusedToLockLiveStore,
    measure_lock_cost,
    ArtifactProbe,
    ExpectedFailure,
    Finding,
    PositiveControl,
    Report,
    Status,
    preflight,
)
from scitex_db._schema_change._cards_store import (
    catalogue_is_visible,
    row_level_write_landed,
    v10_rung_checks,
)


class _Conn:
    """Stand-in connection. The checks never introspect it."""


@pytest.fixture
def conn() -> _Conn:
    return _Conn()


@pytest.fixture
def live_control() -> PositiveControl:
    return PositiveControl(
        name="rows exist",
        query="SELECT count(*) FROM tasks",
        fetch_one_int=lambda c, q: 3569,
    )


@pytest.fixture
def dead_control() -> PositiveControl:
    return PositiveControl(
        name="rows exist",
        query="SELECT count(*) FROM tasks",
        fetch_one_int=lambda c, q: 0,
    )


@pytest.fixture
def absent_artifact() -> ArtifactProbe:
    return ArtifactProbe(
        name="row-level write path landed",
        artifact="tasks_row_level_write",
        exists=lambda c: False,
    )


@pytest.fixture
def present_artifact() -> ArtifactProbe:
    return ArtifactProbe(
        name="row-level write path landed",
        artifact="tasks_row_level_write",
        exists=lambda c: True,
    )


@pytest.fixture
def broken_artifact() -> ArtifactProbe:
    def boom(c):
        raise RuntimeError("no such function has_trigger")

    return ArtifactProbe(name="landed", artifact="x", exists=boom)


# --------------------------------------------------------------------------
# Status is three-valued and refuses to be a bool
# --------------------------------------------------------------------------


def test_unknown_status_refuses_boolean_coercion():
    # Arrange
    status = Status.UNKNOWN
    # Act / assert via the raise
    # Assert
    with pytest.raises(TypeError, match="three-valued"):
        bool(status)


def test_pass_status_also_refuses_boolean_coercion():
    # Arrange
    status = Status.PASS
    # Act
    # Assert
    with pytest.raises(TypeError, match="three-valued"):
        bool(status)


# --------------------------------------------------------------------------
# ArtifactProbe: the landed-check
# --------------------------------------------------------------------------


def test_absent_artifact_reports_fail(conn, absent_artifact):
    # Arrange
    probe = absent_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.FAIL


def test_absent_artifact_hint_says_it_is_an_honest_no(conn, absent_artifact):
    # Arrange
    probe = absent_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert "honest NO" in finding.hint


def test_present_artifact_reports_pass(conn, present_artifact):
    # Arrange
    probe = present_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.PASS


def test_broken_probe_reports_unknown_not_fail(conn, broken_artifact):
    """A probe that cannot run says nothing about the store.

    Reporting FAIL here is the error made this morning: an empty
    container-local database read as "the fleet registry is empty".
    """
    # Arrange
    probe = broken_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.UNKNOWN


def test_broken_probe_hint_denies_it_is_evidence(conn, broken_artifact):
    # Arrange
    probe = broken_artifact
    # Act
    finding = probe.run(conn)
    # Assert
    assert "NOT evidence" in finding.hint


# --------------------------------------------------------------------------
# PositiveControl: a zero must be earned
# --------------------------------------------------------------------------


def test_zero_control_marks_instrument_not_live(conn, dead_control):
    """A dead instrument's zeros must not read as a clean store."""
    # Arrange
    checks = [dead_control]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is False


def test_zero_control_makes_report_not_ok(conn, dead_control):
    # Arrange
    checks = [dead_control]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_run_without_any_control_is_not_live(conn, present_artifact):
    """Absence of a control is absence of proof, not permission."""
    # Arrange
    checks = [present_artifact]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is False


def test_live_control_marks_instrument_live(conn, live_control):
    # Arrange
    checks = [live_control]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is True


def test_all_passing_findings_are_still_not_ok_without_a_control(conn, present_artifact):
    """A dead instrument must veto ok even when every finding PASSED.

    ADDED AFTER A SURVIVING MUTATION. Deleting the ``instrument_live`` guard
    from ``Report.ok`` left all 21 tests green: every existing case that
    asserted ``ok is False`` also had a FAILING finding, so ``all(...)`` alone
    produced False and the guard was never exercised. This is the only shape
    that isolates it -- instrument not proven live, nothing else wrong.

    Which is the whole point of the guard: a run that finds no problems because
    it could not see anything must not read as a clean store."""
    # Arrange
    checks = [present_artifact]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


# --------------------------------------------------------------------------
# ExpectedFailure: success is the alarming outcome
# --------------------------------------------------------------------------


def test_refused_operation_reports_pass(conn):
    # Arrange
    def attempt(c):
        raise ValueError("FK violation")

    check = ExpectedFailure(
        name="missing parent refused",
        attempt=attempt,
        describe="insert with a genuinely missing parent",
    )
    # Act
    finding = check.run(conn)
    # Assert
    assert finding.status is Status.PASS


def test_accepted_operation_reports_fail(conn):
    """The guard being GONE is what this check exists to catch."""
    # Arrange
    check = ExpectedFailure(
        name="missing parent refused",
        attempt=lambda c: None,
        describe="insert with a genuinely missing parent",
    )
    # Act
    finding = check.run(conn)
    # Assert
    assert finding.status is Status.FAIL


def test_accepted_operation_hint_names_the_dangerous_direction(conn):
    # Arrange
    check = ExpectedFailure(
        name="missing parent refused",
        attempt=lambda c: None,
        describe="insert with a genuinely missing parent",
    )
    # Act
    finding = check.run(conn)
    # Assert
    assert "dangerous direction" in finding.hint


# --------------------------------------------------------------------------
# Report: ok is derived, unknown counts against it, everything is collected
# --------------------------------------------------------------------------


def test_unknown_finding_makes_report_not_ok(conn, live_control, broken_artifact):
    # Arrange
    checks = [live_control, broken_artifact]
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_every_check_runs_even_after_a_failure(conn, live_control):
    """Stopping at the first problem turns one review into N runs."""
    # Arrange
    calls: list[str] = []

    def make(name: str, ok: bool) -> ArtifactProbe:
        return ArtifactProbe(
            name=name,
            artifact=name,
            exists=lambda c, n=name, o=ok: (calls.append(n), o)[1],
        )

    checks = [live_control, make("a", False), make("b", False), make("c", True)]
    # Act
    preflight(conn, checks)
    # Assert
    assert calls == ["a", "b", "c"]


def test_report_collects_every_finding(conn, live_control):
    # Arrange
    probes = [
        ArtifactProbe(name=f"p{i}", artifact=f"a{i}", exists=lambda c: False)
        for i in range(3)
    ]
    # Act
    report = preflight(conn, [live_control, *probes])
    # Assert
    assert len(report.findings) == 4


def test_failing_finding_makes_ok_false():
    """ok is computed, so a report cannot contradict its findings."""
    # Arrange
    finding = Finding(name="x", status=Status.FAIL, detail="d", hint="h")
    # Act
    report = Report(findings=(finding,), instrument_live=True)
    # Assert
    assert report.ok is False


def test_ok_cannot_be_assigned():
    # Arrange
    report = Report(findings=(), instrument_live=True)
    # Act
    # Assert
    with pytest.raises(AttributeError):
        report.ok = True  # type: ignore[misc]


# --------------------------------------------------------------------------
# Finding: a verdict without evidence, or a failure without a hint, is refused
# --------------------------------------------------------------------------


def test_finding_without_detail_is_refused():
    # Arrange
    kwargs = dict(name="x", status=Status.PASS, detail="")
    # Act
    # Assert
    with pytest.raises(ValueError, match="no detail"):
        Finding(**kwargs)


def test_non_passing_finding_without_hint_is_refused():
    """An error that only states what broke is half-written."""
    # Arrange
    kwargs = dict(name="x", status=Status.FAIL, detail="something")
    # Act
    # Assert
    with pytest.raises(ValueError, match="no hint"):
        Finding(**kwargs)


# --------------------------------------------------------------------------
# _cards_store: the binding scitex-cards will call on 08-13
# --------------------------------------------------------------------------


def test_row_level_write_probe_reports_fail_when_trigger_absent(conn):
    # Arrange
    probe = row_level_write_landed(has_trigger=lambda c, name: False)
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.FAIL


def test_row_level_write_probe_reports_pass_when_trigger_present(conn):
    # Arrange
    probe = row_level_write_landed(has_trigger=lambda c, name: True)
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.PASS


def test_row_level_write_probe_asks_for_the_agreed_artifact_name(conn):
    """The rung name is scitex-cards' contract; drifting from it silently
    would make this probe answer a question nobody agreed to."""
    # Arrange
    asked: list[str] = []
    probe = row_level_write_landed(
        has_trigger=lambda c, name: (asked.append(name), False)[1]
    )
    # Act
    probe.run(conn)
    # Assert
    assert asked == ["tasks_row_level_write"]


def test_missing_cards_package_yields_unknown_not_fail(conn):
    """An absent package is not evidence that the change is absent."""
    # Arrange
    def unavailable(c, name):
        raise ImportError("No module named 'scitex_cards'")

    probe = row_level_write_landed(has_trigger=unavailable)
    # Act
    finding = probe.run(conn)
    # Assert
    assert finding.status is Status.UNKNOWN


def test_v10_rung_checks_put_the_control_first(conn):
    """A reader must meet the instrument's verdict before findings that rest on it."""
    # Arrange
    checks = v10_rung_checks(
        fetch_one_int=lambda c, q: 3569,
        has_trigger=lambda c, name: False,
    )
    # Act
    first = checks[0]
    # Assert
    assert isinstance(first, PositiveControl)


def test_v10_rung_is_not_ready_on_a_store_without_the_trigger(conn):
    """The whole point: an honest NOT READY, from a live instrument."""
    # Arrange
    checks = v10_rung_checks(
        fetch_one_int=lambda c, q: 3569,
        has_trigger=lambda c, name: False,
    )
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.ok is False


def test_blind_catalogue_makes_instrument_not_live(conn):
    """A catalogue read that sees NOTHING must not publish a verdict.

    THE ISOLATING CASE, per scitex-cards: a broken catalogue read returns False
    for every artifact, so row_level_write_landed reports "absent" -- which is
    byte-identical to an honest pre-flip store. Without this control the report
    would say NOT READY for the right reason by accident.

    Here the artifact probe legitimately fails too, so ok would be False either
    way; what this pins is that INSTRUMENT_LIVE goes False, which is the only
    signal that distinguishes "not landed" from "I cannot see anything"."""
    # Arrange
    blind = lambda c, name: False
    checks = v10_rung_checks(fetch_one_int=lambda c, q: 3608, has_trigger=blind)
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is False


def test_visible_catalogue_marks_instrument_live(conn):
    # Arrange
    sighted = lambda c, name: name == "tasks_bump_revision"
    checks = v10_rung_checks(fetch_one_int=lambda c, q: 3608, has_trigger=sighted)
    # Act
    report = preflight(conn, checks)
    # Assert
    assert report.instrument_live is True


def test_catalogue_control_asks_for_the_v7_rung(conn):
    """It must probe an artifact known to exist, through the same helper."""
    # Arrange
    asked: list[str] = []
    control = catalogue_is_visible(
        has_trigger=lambda c, name: (asked.append(name), True)[1]
    )
    # Act
    control.run(conn)
    # Assert
    assert asked == ["tasks_bump_revision"]


# --------------------------------------------------------------------------
# measure_lock_cost: takes a REAL lock, so the disruptive path cannot be
# reached by forgetting an argument
# --------------------------------------------------------------------------


def test_measuring_without_asserting_scratch_is_refused(conn):
    """The lock is taken even though the write is rolled back."""
    # Arrange
    stmt = "CREATE TRIGGER t AFTER UPDATE ON tasks BEGIN SELECT 1; END"
    # Act
    # Assert
    with pytest.raises(RefusedToLockLiveStore):
        measure_lock_cost(conn, stmt, scratch=False)


def test_refusal_names_the_lock_not_the_write(conn):
    """A caller who reads 'rolled back' must not conclude 'undisruptive'."""
    # Arrange
    stmt = "ALTER TABLE tasks ADD COLUMN x INTEGER"
    # Act
    with pytest.raises(RefusedToLockLiveStore) as excinfo:
        measure_lock_cost(conn, stmt, scratch=False)
    # Assert
    assert "blocks every reader and writer" in str(excinfo.value)


def test_scratch_measurement_rolls_back(conn):
    # Arrange
    calls: list[str] = []
    # Act
    result = measure_lock_cost(
        conn,
        "CREATE TRIGGER t",
        scratch=True,
        execute=lambda c, s: calls.append("execute"),
        begin=lambda c: calls.append("begin"),
        rollback=lambda c: calls.append("rollback"),
    )
    # Assert
    assert result.rolled_back is True


def test_scratch_measurement_never_commits(conn):
    """There is no commit path; the sequence must end in rollback."""
    # Arrange
    calls: list[str] = []
    # Act
    measure_lock_cost(
        conn,
        "CREATE TRIGGER t",
        scratch=True,
        execute=lambda c, s: calls.append("execute"),
        begin=lambda c: calls.append("begin"),
        rollback=lambda c: calls.append("rollback"),
    )
    # Assert
    assert calls == ["begin", "execute", "rollback"]


def test_a_raising_statement_still_rolls_back(conn):
    """A failed DDL must not leave the transaction open holding its lock."""
    # Arrange
    calls: list[str] = []

    def boom(c, s):
        raise RuntimeError("syntax error")

    # Act
    with pytest.raises(RuntimeError):
        measure_lock_cost(
            conn,
            "CREATE TRIGGR t",
            scratch=True,
            execute=boom,
            begin=lambda c: calls.append("begin"),
            rollback=lambda c: calls.append("rollback"),
        )
    # Assert
    assert calls == ["begin", "rollback"]


def test_summary_names_a_committed_result_loudly():
    """rolled_back=False must be visibly alarming in the summary."""
    # Arrange
    cost = LockCost(statement="ALTER TABLE tasks ...", seconds=0.5, rolled_back=False)
    # Act
    text = cost.summary()
    # Assert
    assert "COMMITTED" in text
