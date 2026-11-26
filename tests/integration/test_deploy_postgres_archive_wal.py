"""archive-wal.sh: a WAL segment is published whole or not at all.

Every test runs the real script with /bin/sh against real files in a temp
directory. The "copy cut short" cases make the copy fail for real by lowering
RLIMIT_FSIZE (``ulimit -f``) with SIGXFSZ ignored, so ``write(2)`` returns
EFBIG part-way through, just as ENOSPC did on scitex-nas-03 on 2026-11-24.

Each test asserts ONE outcome tuple (exit status, archive contents, ...), so a
failure prints the whole observed state rather than stopping at the first
mismatch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "scitex_db"
    / "deploy"
    / "postgres"
    / "archive-wal.sh"
)
SEGMENT = "00000002000000800000007D"
SEGMENT_BYTES = 1024 * 1024
# dash counts `ulimit -f` in 512-byte blocks: 256 blocks = 128 KiB, well
# short of the 1 MiB test segment.
SHORT_WRITE_BLOCKS = 256


@pytest.fixture
def wal(tmp_path: Path) -> tuple[Path, Path]:
    """A source segment with random content, and an empty archive dir."""
    pg_wal = tmp_path / "pg_wal"
    archive = tmp_path / "wal-archive"
    pg_wal.mkdir()
    archive.mkdir()
    src = pg_wal / SEGMENT
    src.write_bytes(os.urandom(SEGMENT_BYTES))
    return src, archive


def run_archive(src: Path, name: str, archive: Path, fsize_blocks: int | None = None):
    """Run archive-wal.sh, optionally with a file-size limit that cuts the copy short."""
    if fsize_blocks is None:
        argv = ["sh", str(SCRIPT), str(src), name, str(archive)]
    else:
        argv = [
            "sh",
            "-c",
            f'trap "" XFSZ; ulimit -f {fsize_blocks}; exec sh "$0" "$@"',
            str(SCRIPT),
            str(src),
            name,
            str(archive),
        ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def run_legacy_archive_command(
    src: Path, archive: Path, fsize_blocks: int | None = None
):
    """The archive_command this script replaces, verbatim apart from paths."""
    legacy = f"test ! -f {archive}/{SEGMENT} && cp -f {src} {archive}/{SEGMENT}"
    if fsize_blocks is not None:
        legacy = f'trap "" XFSZ; ulimit -f {fsize_blocks}; {legacy}'
    return subprocess.run(
        ["sh", "-c", legacy], capture_output=True, text=True, timeout=30
    )


def archive_names(archive: Path) -> list[str]:
    return sorted(p.name for p in archive.iterdir())


def archived_matches(src: Path, archive: Path) -> bool:
    dest = archive / SEGMENT
    return dest.is_file() and dest.read_bytes() == src.read_bytes()


def test_new_segment_is_archived_byte_identical_with_no_temp_left(wal):
    # Arrange
    src, archive = wal

    # Act
    result = run_archive(src, SEGMENT, archive)

    # Assert
    assert (
        result.returncode,
        archived_matches(src, archive),
        archive_names(archive),
    ) == (
        0,
        True,
        [SEGMENT],
    ), result.stderr


def test_identical_existing_copy_is_success_and_left_untouched(wal):
    # Arrange
    src, archive = wal
    run_archive(src, SEGMENT, archive)
    inode_before = (archive / SEGMENT).stat().st_ino

    # Act
    result = run_archive(src, SEGMENT, archive)

    # Assert
    assert (
        result.returncode,
        "byte-identical" in result.stderr,
        (archive / SEGMENT).stat().st_ino == inode_before,
    ) == (0, True, True), result.stderr


def test_truncated_existing_copy_fails_loudly_and_is_not_overwritten(wal):
    """The state the incident left behind: a prefix of the segment under its real name."""
    # Arrange
    src, archive = wal
    truncated = src.read_bytes()[: SEGMENT_BYTES // 3]
    (archive / SEGMENT).write_bytes(truncated)
    expected_detail = f"archived {len(truncated)} bytes, source {SEGMENT_BYTES} bytes"

    # Act
    result = run_archive(src, SEGMENT, archive)

    # Assert
    assert (
        result.returncode != 0,
        "DIFFERS" in result.stderr,
        expected_detail in result.stderr,
        (archive / SEGMENT).read_bytes() == truncated,
        archive_names(archive),
    ) == (True, True, True, True, [SEGMENT]), result.stderr


def test_same_size_different_content_fails_loudly_and_is_kept(wal):
    # Arrange
    src, archive = wal
    other = os.urandom(SEGMENT_BYTES)
    (archive / SEGMENT).write_bytes(other)

    # Act
    result = run_archive(src, SEGMENT, archive)

    # Assert
    assert (
        result.returncode != 0,
        "DIFFERS" in result.stderr,
        (archive / SEGMENT).read_bytes() == other,
    ) == (True, True, True), result.stderr


def test_copy_cut_short_publishes_nothing(wal):
    """The incident's failure, through this script: no truncated file appears."""
    # Arrange
    src, archive = wal

    # Act
    result = run_archive(src, SEGMENT, archive, fsize_blocks=SHORT_WRITE_BLOCKS)

    # Assert
    assert (
        result.returncode != 0,
        "nothing was published" in result.stderr,
        archive_names(archive),
    ) == (True, True, []), result.stderr


def test_retry_after_a_copy_cut_short_succeeds(wal):
    """What the legacy command could never do once the disk had filled."""
    # Arrange
    src, archive = wal
    run_archive(src, SEGMENT, archive, fsize_blocks=SHORT_WRITE_BLOCKS)

    # Act
    retry = run_archive(src, SEGMENT, archive)

    # Assert
    assert (
        retry.returncode,
        archived_matches(src, archive),
        archive_names(archive),
    ) == (
        0,
        True,
        [SEGMENT],
    ), retry.stderr


def test_legacy_archive_command_wedges_after_a_short_copy(wal):
    """Why the old command had to go: one short copy, then every retry fails."""
    # Arrange
    src, archive = wal
    first = run_legacy_archive_command(src, archive, fsize_blocks=SHORT_WRITE_BLOCKS)

    # Act
    retry = run_legacy_archive_command(src, archive)

    # Assert
    assert (
        first.returncode != 0,
        (archive / SEGMENT).stat().st_size < SEGMENT_BYTES,
        retry.returncode != 0,
    ) == (True, True, True)


def test_stale_temp_from_a_killed_attempt_is_removed(wal):
    # Arrange
    src, archive = wal
    (archive / f".{SEGMENT}.partial.99999").write_bytes(b"half a segment")

    # Act
    result = run_archive(src, SEGMENT, archive)

    # Assert
    assert (result.returncode, archive_names(archive)) == (0, [SEGMENT]), result.stderr


@pytest.mark.parametrize("bad_name", ["", "..", ".hidden", "../escape", "a/b"])
def test_unsafe_segment_names_are_refused(wal, bad_name):
    # Arrange
    src, archive = wal

    # Act
    result = run_archive(src, bad_name, archive)

    # Assert
    assert (
        result.returncode != 0,
        "refusing segment name" in result.stderr,
        archive_names(archive),
    ) == (True, True, []), result.stderr


def test_missing_source_fails(wal):
    # Arrange
    src, archive = wal

    # Act
    result = run_archive(src.with_name("absent"), SEGMENT, archive)

    # Assert
    assert (result.returncode != 0, "is not a regular file" in result.stderr) == (
        True,
        True,
    ), result.stderr


def test_missing_archive_dir_fails(wal, tmp_path):
    # Arrange
    src, _ = wal

    # Act
    result = run_archive(src, SEGMENT, tmp_path / "no-such-dir")

    # Assert
    assert (result.returncode != 0, "does not exist" in result.stderr) == (
        True,
        True,
    ), result.stderr


def test_wrong_argument_count_fails(wal):
    # Arrange
    src, _ = wal

    # Act
    result = subprocess.run(
        ["sh", str(SCRIPT), str(src), SEGMENT],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Assert
    assert (result.returncode != 0, "usage" in result.stderr) == (True, True), (
        result.stderr
    )
