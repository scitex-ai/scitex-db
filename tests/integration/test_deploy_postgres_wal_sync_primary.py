"""wal-sync-primary.sh: offsite is confirmed by content, and nothing is pruned on a bad run.

Every test runs the real script with bash, real rsync and real sha256sum
against real files. The "far side" is a second temp directory: SCITEX_PG_RSH
points at a tiny remote-shell stand-in that runs the command in that
directory, with the same calling convention as ssh (HOST CMD...). rsync uses it
as its transport exactly as it would use ssh.

Each test asserts ONE outcome tuple, so a failure prints the whole observed
state (exit status, what is left locally, what is offsite) at once.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "scitex_db"
    / "deploy"
    / "postgres"
    / "backup"
    / "wal-sync-primary.sh"
)
SEGMENT_BYTES = 4096  # the script's WAL segment size, shrunk for speed
OFFSITE_PATH = "pg-backups/nas-03/wal-archive"
AGED = time.time() - 20 * 86400  # older than the 14-day retention
HEALTHY = {
    "in_recovery": "f",
    "archive_mode": "on",
    "failed_count": "0",
    "age_min": "1",
    "timeline_now": "2",
    "timeline_archived": "00000002",
}

FAKE_RSH = """#!/bin/sh
# Stand-in for ssh: HOST CMD... runs CMD in $FAKE_REMOTE_HOME.
[ -n "${FAKE_RSH_DOWN:-}" ] && { echo "ssh: connect to host $1: Connection refused" >&2; exit 255; }
shift
cd "$FAKE_REMOTE_HOME" || exit 255
exec sh -c "$*"
"""


def seg(n: int) -> str:
    return f"0000000200000080{n:08X}"


@dataclass
class Lane:
    root: Path
    archive: Path
    offsite: Path
    state: Path
    status_file: Path
    env: dict = field(default_factory=dict)

    def add(self, name: str, content: bytes | None = None, aged: bool = True) -> bytes:
        data = os.urandom(SEGMENT_BYTES) if content is None else content
        path = self.archive / name
        path.write_bytes(data)
        if aged:
            os.utime(path, (AGED, AGED))
        return data

    def put_offsite(self, name: str, data: bytes) -> None:
        (self.offsite / name).write_bytes(data)

    def status(self, **overrides: str) -> None:
        values = {**HEALTHY, **overrides}
        self.status_file.write_text("".join(f"{k}={v}\n" for k, v in values.items()))

    def run(self, *args: str, **extra_env: str) -> subprocess.CompletedProcess:
        env = {**self.env, **extra_env}
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def local_names(self) -> list[str]:
        return sorted(p.name for p in self.archive.iterdir())

    def offsite_names(self) -> list[str]:
        return sorted(
            p.name for p in self.offsite.iterdir() if not p.name.startswith(".")
        )

    def offsite_bytes(self, name: str) -> bytes:
        return (self.offsite / name).read_bytes()


@pytest.fixture
def lane(tmp_path: Path) -> Lane:
    archive = tmp_path / "wal-archive"
    remote_home = tmp_path / "remote-home"
    offsite = remote_home / OFFSITE_PATH
    state = tmp_path / "state"
    archive.mkdir()
    offsite.mkdir(parents=True)
    status_file = tmp_path / "archiver-status.txt"
    status_cmd = tmp_path / "archiver_status.sh"
    status_cmd.write_text(f'#!/bin/sh\ncat "{status_file}"\n')
    status_cmd.chmod(0o755)
    rsh = tmp_path / "fake-rsh"
    rsh.write_text(FAKE_RSH)
    rsh.chmod(0o755)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "LC_ALL": "C",
        "SCITEX_PG_ARCHIVE_DIR": str(archive),
        "SCITEX_PG_OFFSITE_HOST": "offsite",
        "SCITEX_PG_OFFSITE_PATH": OFFSITE_PATH,
        "SCITEX_PG_ARCHIVER_STATUS": str(status_cmd),
        "SCITEX_PG_SUDO": "",
        "SCITEX_PG_RSH": str(rsh),
        "SCITEX_PG_STATE_DIR": str(state),
        "SCITEX_PG_WAL_SEGMENT_BYTES": str(SEGMENT_BYTES),
        "FAKE_REMOTE_HOME": str(remote_home),
    }
    result = Lane(tmp_path, archive, offsite, state, status_file, env)
    result.status()
    return result


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- the happy path ---------------------------------------------------------


def test_clean_run_pushes_everything_and_prunes_only_aged_files(lane):
    # Arrange
    old = {seg(n): lane.add(seg(n), aged=True) for n in (1, 2)}
    young = {seg(3): lane.add(seg(3), aged=False)}

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        lane.local_names(),
        lane.offsite_names(),
        all(lane.offsite_bytes(n) == d for n, d in {**old, **young}.items()),
    ) == (0, [seg(3)], [seg(1), seg(2), seg(3)], True), result.stdout + result.stderr


def test_verified_files_are_not_hashed_again_on_the_next_run(lane):
    # Arrange
    lane.add(seg(1), aged=False)
    lane.run()

    # Act
    second = lane.run()

    # Assert
    assert (
        second.returncode,
        "newly hashed=0" in second.stdout,
        "verified=1" in second.stdout,
    ) == (
        0,
        True,
        True,
    ), second.stdout


def test_aged_file_beyond_the_verification_budget_is_held(lane):
    # Arrange
    lane.add(seg(1))
    lane.add(seg(2))

    # Act
    result = lane.run(SCITEX_PG_VERIFY_MAX="1")

    # Assert
    assert (
        result.returncode,
        lane.local_names(),
        "pending_verification=1" in result.stdout,
    ) == (
        0,
        [seg(2)],
        True,
    ), result.stdout


# --- the incident: a bad copy offsite under the right NAME --------------------


def test_truncated_offsite_copy_is_a_conflict_not_a_confirmation(lane):
    """2026-11-25: the far side had the name, so the old lane counted it as safe."""
    # Arrange
    good = lane.add(seg(1))
    lane.put_offsite(seg(1), good[: SEGMENT_BYTES // 3])

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        "CONFLICT" in result.stdout,
        seg(1) in lane.local_names(),
        lane.offsite_bytes(seg(1)) == good[: SEGMENT_BYTES // 3],
        lane.offsite_bytes(f"{seg(1)}.conflict-{sha(good)[:12]}") == good,
    ) == (1, True, True, True, True), result.stdout


def test_same_size_offsite_copy_with_different_bytes_is_a_conflict(lane):
    # Arrange
    good = lane.add(seg(1))
    other = os.urandom(SEGMENT_BYTES)
    lane.put_offsite(seg(1), other)

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        "sha256: local" in result.stdout,
        lane.local_names(),
        lane.offsite_bytes(seg(1)) == other,
        lane.offsite_bytes(f"{seg(1)}.conflict-{sha(good)[:12]}") == good,
    ) == (1, True, [seg(1)], True, True), result.stdout


def test_a_conflict_stops_all_pruning_that_run(lane):
    # Arrange
    lane.add(seg(1))
    lane.add(seg(2))
    lane.put_offsite(seg(2), os.urandom(SEGMENT_BYTES))

    # Act
    result = lane.run()

    # Assert
    assert (result.returncode, lane.local_names(), "NOT pruning" in result.stdout) == (
        1,
        [seg(1), seg(2)],
        True,
    ), result.stdout


def test_offsite_copy_changed_after_verification_is_caught_before_pruning(lane):
    # Arrange
    data = lane.add(seg(1), aged=False)
    lane.run()
    os.utime(lane.archive / seg(1), (AGED, AGED))
    tampered = bytearray(data)
    tampered[0] ^= 0xFF
    lane.put_offsite(seg(1), bytes(tampered))

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        "pre-prune re-check" in result.stdout,
        lane.local_names(),
    ) == (1, True, [seg(1)]), result.stdout


# --- never prune while anything is wrong --------------------------------------


def test_failing_archiver_still_pushes_but_prunes_nothing(lane):
    # Arrange
    lane.add(seg(1))
    lane.status(failed_count="3")

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        lane.local_names(),
        lane.offsite_names(),
        "NOT pruning" in result.stdout,
    ) == (1, [seg(1)], [seg(1)], True), result.stdout


def test_database_down_prunes_nothing(lane):
    """archiver_status.sh prints every key with an EMPTY value when psql cannot connect."""
    # Arrange
    lane.add(seg(1))
    lane.status_file.write_text(
        "in_recovery=\narchive_mode=\nfailed_count=\nage_min=\ntimeline_now=\ntimeline_archived=\n"
    )

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        "database is down or unreachable" in result.stdout,
        lane.local_names(),
    ) == (1, True, [seg(1)]), result.stdout


def test_stale_archive_prunes_nothing(lane):
    # Arrange
    lane.add(seg(1))
    lane.status(age_min="120")

    # Act
    result = lane.run()

    # Assert
    assert (result.returncode, lane.local_names()) == (1, [seg(1)]), result.stdout


def test_truncated_local_segment_is_not_pushed_and_nothing_is_pruned(lane):
    # Arrange
    lane.add(seg(1))
    lane.add(seg(2), content=os.urandom(SEGMENT_BYTES // 2))

    # Act
    result = lane.run()

    # Assert
    assert (
        result.returncode,
        "TRUNCATED" in result.stdout,
        lane.local_names(),
        lane.offsite_names(),
    ) == (1, True, [seg(1), seg(2)], [seg(1)]), result.stdout


def test_unreachable_offsite_host_fails_and_prunes_nothing(lane):
    # Arrange
    lane.add(seg(1))

    # Act
    result = lane.run(FAKE_RSH_DOWN="1")

    # Assert
    assert (result.returncode, lane.local_names(), lane.offsite_names()) == (
        1,
        [seg(1)],
        [],
    ), result.stdout


def test_empty_archive_with_archiving_on_is_an_alert(lane):
    # Arrange: nothing archived

    # Act
    result = lane.run()

    # Assert
    assert (result.returncode, "EMPTY" in result.stdout) == (1, True), result.stdout


# --- dry run --------------------------------------------------------------------


def test_dry_run_changes_nothing(lane):
    # Arrange
    lane.add(seg(1))
    lane.add(seg(2), aged=False)

    # Act
    result = lane.run("--dry-run")

    # Assert
    assert (
        result.returncode,
        lane.local_names(),
        lane.offsite_names(),
        lane.state.exists(),
        "would push" in result.stdout,
    ) == (0, [seg(1), seg(2)], [], False, True), result.stdout


def test_dry_run_reports_what_it_would_prune(lane):
    # Arrange
    data = lane.add(seg(1))
    lane.put_offsite(seg(1), data)

    # Act
    result = lane.run("--dry-run")

    # Assert
    assert (
        result.returncode,
        lane.local_names(),
        "would prune 1 file(s)" in result.stdout,
    ) == (
        0,
        [seg(1)],
        True,
    ), result.stdout


def test_dry_run_still_exits_non_zero_on_an_alert(lane):
    # Arrange
    lane.add(seg(1))
    lane.status(failed_count="1")

    # Act
    result = lane.run("--dry-run")

    # Assert
    assert result.returncode == 1, result.stdout


def test_unknown_argument_is_refused(lane):
    # Arrange: a healthy lane

    # Act
    result = lane.run("--prune-everything")

    # Assert
    assert (result.returncode, "unknown argument" in result.stderr) == (2, True), (
        result.stderr
    )
