#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What the migration OBSERVES for itself, as opposed to what it is told.

Sibling of ``_provenance``, and the distinction is the whole point.
:class:`._provenance.Quiescence` is a CLAIM the caller makes and this package
records because it cannot check it. This module is the part it now can check --
and the reason it is a separate module is that evidence and assertion must not
be able to be mistaken for one another at a call site.

WHY THIS EXISTS, MEASURED. Two scitex-cards cutovers lost rows written after the
copy began. Both declared quiescence in good faith. The declaration was true
about the writers the caller knew about, and the writers that mattered were four
host-side systemd units, three cron entries and an hourly timer, none of which
carried the store's DSN and all of which had silently fallen back to the old
path. Nobody could have named them, so no amount of care in the CLAIM would have
helped. Only looking at the file does.

AND LOOKING ONCE IS NOT LOOKING. The first design of this module was "read a
high-water mark before the copy, read it again after, refuse if it moved" -- two
instants. scitex-cards killed that with a measurement: a point-in-time ``lsof``
showed NOBODY holding their database while a watcher wrote it every two seconds,
because the writer opens, writes and closes. Only 0.2s-interval polling caught
it. A two-instant check is not merely weak against that writer, it is SILENT:
it would have reported quiescence proven over the exact process that caused the
data loss, which is the worst possible failure for a check whose reason to exist
is that class of bug.

So nothing here ever answers "is the source quiet?". It answers "what did I see,
over how long, looking how often?" -- and :class:`QuiescenceEvidence` carries the
window and the interval so a caller cannot read more into a negative than was
measured. A silence of two seconds and a silence of ten minutes are different
facts and must not share a representation.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass

__all__ = ["QuiescenceEvidence", "observe_source"]


@dataclass(frozen=True)
class QuiescenceEvidence:
    """What was seen while watching a source, and over what window.

    Three-valued on purpose, because the honest answer set has three members and
    collapsing the third into either pole is the bug this package keeps finding:

    * ``writes_seen > 0``            -- a writer was caught. Positive, certain.
    * ``writes_seen == 0``           -- nothing was caught IN THIS WINDOW. A
      bounded negative, never "quiet"; a writer slower than ``observed_seconds``
      is entirely consistent with this result.
    * ``unobservable_reason`` set    -- the source could not be watched at all.
      NOT the same as seeing nothing, and the reason it is a separate field
      rather than ``writes_seen = 0`` is that a caller must not be able to read
      "I could not look" as "I looked and it was fine".

    There is deliberately no ``quiescent`` property and there should never be
    one. Any boolean here would have to drop either the window or the
    unobservable case, and both are load-bearing.
    """

    observed_seconds: float
    sample_interval_seconds: float
    samples_taken: int
    writes_seen: int
    signals_fired: tuple[str, ...] = ()
    unobservable_reason: str | None = None

    def __post_init__(self) -> None:
        # A validator, so a malformed answer fails where it is built rather than
        # three layers downstream in a migration that has already copied rows.
        if self.unobservable_reason is not None:
            if self.samples_taken or self.writes_seen:
                raise ValueError(
                    f"contradictory evidence: unobservable "
                    f"({self.unobservable_reason!r}) yet {self.samples_taken} "
                    f"sample(s) and {self.writes_seen} write(s) are recorded. "
                    f"'I could not look' and 'I looked' are different answers."
                )
            return
        if self.samples_taken < 2:
            raise ValueError(
                f"{self.samples_taken} sample(s) is not a sample. Detecting a "
                f"writer that opens, writes and closes requires COMPARING "
                f"consecutive observations, so fewer than two readings can "
                f"only ever report zero writes -- a check that cannot fail. "
                f"Widen the window or shorten the interval."
            )
        if self.writes_seen and not self.signals_fired:
            raise ValueError(
                "writes were seen but no signal is named. A refusal a caller "
                "cannot act on is half-written -- record WHICH signal moved."
            )

    @property
    def observed(self) -> bool:
        """Whether watching happened at all. False means unobservable."""
        return self.unobservable_reason is None

    def summary(self) -> str:
        """One line, always naming the window -- there is no unqualified form."""
        if not self.observed:
            return (
                f"quiescence NOT OBSERVED: {self.unobservable_reason}. This is "
                f"not evidence of quiet; nothing was watched."
            )
        window = (
            f"over {self.observed_seconds:.2f}s at "
            f"{self.sample_interval_seconds:.2f}s sampling "
            f"({self.samples_taken} samples)"
        )
        if self.writes_seen:
            return (
                f"WRITER OBSERVED: {self.writes_seen} write(s) {window}; "
                f"signals: {', '.join(self.signals_fired)}"
            )
        return f"no writer observed {window}"


def _read_signals(
    source_path: str, conn: sqlite3.Connection | None
) -> dict[str, object] | None:
    """One reading of every signal, or ``None`` if the source cannot be read.

    ``PRAGMA data_version`` is the load-bearing signal and the reason a
    connection is held at all: SQLite increments it ON THIS CONNECTION when
    ANOTHER connection commits, which is precisely the open-write-close writer
    that holds no handle for a point-in-time check to find.

    THE CONNECTION MUST BE HELD ACROSS THE WHOLE WINDOW, and the first version of
    this module opened a fresh one per reading. Measured on SQLite 3.x, python
    3.12:

        fresh connection per reading, across a commit:  1 -> 1   (never changes)
        one held connection, across a commit:           1 -> 2

    A fresh connection re-reads its own baseline every time, so the value is
    constant by construction and the signal is dead. It shipped green because the
    stat signals below were carrying every test on their own -- a dead signal
    beside a live one is invisible, which is the whole reason this file argues
    for naming WHICH signal fired.

    The stat signals are kept beside it rather than replaced by it: they catch a
    writer that touches the files by some route SQLite does not account for --
    a restore over the top, a copy, an external truncation. Two independent
    signals cost nothing here and the failure mode of trusting one is silence.
    """
    if not os.path.exists(source_path):
        return None
    reading: dict[str, object] = {}
    if conn is not None:
        try:
            reading["data_version"] = conn.execute(
                "PRAGMA data_version"
            ).fetchone()[0]
        except sqlite3.Error as exc:
            # Not fatal on its own -- the stat signals still work, and a source
            # that is briefly locked is exactly when a writer is active.
            reading["data_version_error"] = str(exc)
    for suffix in ("", "-wal"):
        path = source_path + suffix
        try:
            st = os.stat(path)
            reading[f"mtime_ns{suffix}"] = st.st_mtime_ns
            reading[f"size{suffix}"] = st.st_size
        except FileNotFoundError:
            reading[f"mtime_ns{suffix}"] = None
            reading[f"size{suffix}"] = None
    return reading


def observe_source(
    source_path: str,
    *,
    seconds: float,
    interval: float,
) -> QuiescenceEvidence:
    """Watch ``source_path`` for ``seconds``, sampling every ``interval``.

    Both are REQUIRED and keyword-only, with no defaults. A default window would
    be a number this module invented and every caller inherited without reading
    -- and since the whole result is "nothing seen in THIS window", a window
    nobody chose is a result nobody can interpret. The caller knows how long
    they can afford to wait and how fast the writers they fear are; this module
    knows neither.

    Returns evidence. Does NOT raise on finding a writer, and does not decide
    what to do about one: refusing is a policy the migration applies, and a
    function that both measures and enforces cannot be used to look before you
    commit to looking.
    """
    if interval <= 0:
        raise ValueError(
            f"interval must be positive, got {interval!r}. A zero or negative "
            f"interval would spin without advancing the window."
        )
    if seconds < interval:
        raise ValueError(
            f"window {seconds!r}s is shorter than the sampling interval "
            f"{interval!r}s, so at most one reading would be taken and the "
            f"result could only ever be 'no writes'. A check that cannot fail "
            f"is not a check."
        )

    if not os.path.exists(source_path):
        return QuiescenceEvidence(
            observed_seconds=0.0,
            sample_interval_seconds=interval,
            samples_taken=0,
            writes_seen=0,
            unobservable_reason=f"source {source_path!r} does not exist",
        )

    # ONE connection for the whole window -- see `_read_signals`. Opened here
    # rather than inside the loop because that is the difference between a live
    # `data_version` signal and a dead one.
    try:
        watcher: sqlite3.Connection | None = sqlite3.connect(
            f"file:{source_path}?mode=ro", uri=True
        )
    except sqlite3.Error:
        watcher = None

    try:
        return _watch(source_path, watcher, seconds=seconds, interval=interval)
    finally:
        if watcher is not None:
            watcher.close()


def _watch(
    source_path: str,
    watcher: sqlite3.Connection | None,
    *,
    seconds: float,
    interval: float,
) -> QuiescenceEvidence:
    """The sampling loop itself, split out so the connection is closed once."""
    started = time.monotonic()
    previous = _read_signals(source_path, watcher)
    samples = 1
    writes = 0
    fired: list[str] = []

    while time.monotonic() - started < seconds:
        time.sleep(interval)
        current = _read_signals(source_path, watcher)
        if current is None:
            # The source vanished mid-window. That IS a change, and a violent
            # one -- reported as a write rather than as unobservable, because
            # something plainly acted on it.
            writes += 1
            if "source-disappeared" not in fired:
                fired.append("source-disappeared")
            break
        samples += 1
        changed = [
            key
            for key in set(previous) | set(current)
            if previous.get(key) != current.get(key)
        ]
        if changed:
            writes += 1
            for key in changed:
                if key not in fired:
                    fired.append(key)
        previous = current

    return QuiescenceEvidence(
        observed_seconds=time.monotonic() - started,
        sample_interval_seconds=interval,
        samples_taken=samples,
        writes_seen=writes,
        signals_fired=tuple(fired),
    )

# EOF
