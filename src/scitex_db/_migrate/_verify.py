#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-migration verification: refuse to declare success unless every row matches.

WHY THIS MODULE EXISTS, AND WHY IT IS NOT A ROW COUNT. The obvious check --
"did the same number of rows arrive?" -- passes for the failure that actually
matters. Measured on the live scitex-cards store, 2026-07-30::

    tasks total                       2872
    tombstoned (_log_meta.deleted_at)    1
    status = 'cancelled'                48
    cancelled but NOT tombstoned        47

A migration that silently dropped deleted history would be caught by comparing
tombstone counts -- except the count is 1, so ``1 == 1`` passes for almost any
bug. And the adjacent mistake is destructive rather than merely undetected: a
tool that treats ``status='cancelled'`` as "deleted" and filters it out
destroys 47 legitimately-cancelled live cards, because in this schema deletion
is ``_log_meta.deleted_at`` inside a JSON column and NOT the status. There is no
delete flag among the table's 33 columns.

So this module compares CONTENT, row by row. Tombstone preservation then holds
as a special case of "every row is identical", with no dependence on how rare
tombstones happen to be today.

SILENCE IS NOT SUCCESS. A verification that compared nothing must not report
success -- that is the failure mode where a green check means "the check did not
run". :func:`verify_table` therefore refuses an empty comparison it was not
explicitly told to expect, and :class:`VerificationReport` carries the number of
rows actually compared so a caller can never read a pass without its
denominator.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "MigrationVerificationError",
    "VerificationReport",
    "normalize_value",
    "row_checksum",
    "verify_table",
]


class MigrationVerificationError(Exception):
    """Raised when source and destination disagree, or could not be compared.

    Deliberately not a warning and not a return code. A migration whose
    verification failed has not migrated anything the caller may rely on, and
    the one thing this package must never do is let a partially-copied store
    look finished.
    """


def normalize_value(value: Any) -> Any:
    """Reduce a database value to a form both backends agree on.

    THE PROBLEM THIS SOLVES. SQLite and PostgreSQL hand Python different
    objects for the same stored data, so hashing driver output directly would
    report mismatches on rows that are in fact identical -- and a verification
    that cries wolf gets disabled, which is worse than not having it:

    * SQLite has no boolean type: it stores and returns ``0`` / ``1`` where
      PostgreSQL returns ``False`` / ``True``.
    * PostgreSQL ``NUMERIC`` comes back as :class:`~decimal.Decimal`, while
      SQLite returns :class:`float` or :class:`int`.
    * ``BYTEA`` arrives as :class:`memoryview` from some drivers and
      :class:`bytes` from others.

    Booleans normalize to ``0`` / ``1`` rather than to ``True`` / ``False``
    because the SQLite side genuinely cannot distinguish them: mapping toward
    the *less* expressive representation is lossless in the direction that
    matters, whereas mapping ``0 -> False`` would make an integer column
    containing zeros compare equal to a boolean column containing falses.

    Integral floats are NOT folded into ints. ``1.0`` and ``1`` are different
    stored values, and a migration that changed a column's type from REAL to
    INTEGER is exactly the kind of silent drift this check exists to catch.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, Decimal):
        # str() rather than float(): float() would round, and rounding two
        # different stored numbers into the same hash is a false pass.
        return f"D:{value.normalize():f}"
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _canonical(value: Any) -> str:
    """A stable text form of one normalized value, distinguishing its type.

    The type tag matters: without it the string ``"1"`` and the integer ``1``
    would hash identically, so a column whose type changed during migration
    would verify clean.
    """
    if value is None:
        return "N:"
    if isinstance(value, bytes):
        return "B:" + value.hex()
    if isinstance(value, str):
        return "S:" + value
    if isinstance(value, int):
        return "I:" + str(value)
    if isinstance(value, float):
        return "F:" + repr(value)
    # Anything else is reduced through JSON so the representation is defined
    # rather than dependent on __repr__, which is not a stability guarantee.
    return "J:" + json.dumps(value, sort_keys=True, default=str)


def _absorb(h: "hashlib._Hash", field: bytes) -> None:
    """Feed one field into ``h``, prefixed by its length.

    LENGTH-PREFIXED, NOT DELIMITED, and that distinction is the whole point.
    A delimiter is a byte the data is free to contain, so a value holding the
    delimiter can forge a field boundary and two different rows can hash the
    same. A declared length cannot be forged by content: the framing is fixed
    before any byte of the field is read, so every possible value -- including
    one made entirely of delimiters -- encodes to exactly one sequence.
    """
    h.update(str(len(field)).encode("ascii"))
    h.update(b":")
    h.update(field)


def row_checksum(row: Mapping[str, Any], columns: Sequence[str]) -> str:
    """Hash of ``row`` restricted to ``columns``, in ``columns`` order.

    ``columns`` is required rather than derived from the row's own keys,
    because the two sides must be compared over the SAME column set in the
    SAME order. Deriving it per-row would let a destination that gained or
    lost a column still produce matching digests for the columns it kept --
    a verification that passes while the schema drifted.

    Column NAMES are hashed alongside the values, so renaming a column is a
    mismatch even when every value moved across intact.

    THIS FUNCTION USED TO BE FORGEABLE, and the fix is worth understanding
    rather than just reading. Fields were framed with delimiters -- ``\\x00``
    before the name, ``\\x01`` before the value -- and a value is free to
    contain both. Measured on 2026-07-30, these two DIFFERENT rows produced
    the SAME digest:

        cols = ['a', 'b']
        {'a': 'X',            'b': '\\x00b\\x01S:Y'}
        {'a': 'X\\x00b\\x01S:', 'b': 'Y'}

    A crafted value was needed, so accidental corruption would never have hit
    it -- but the delimiter was ``\\x00``, and this store demonstrably holds
    ``\\x00`` inside TEXT message bodies. The byte the framing depended on
    being absent is a byte the data actually contains.

    It mattered because of where this sits: :func:`._copy.finalize` refuses to
    write the completion marker unless every report is clean, so this digest is
    the last thing standing between a bad copy and a destination that claims to
    have been verified. A gate with a known hole is not a gate.
    """
    h = hashlib.sha256()
    for name in columns:
        _absorb(h, name.encode("utf-8"))
        _absorb(h, _canonical(normalize_value(row.get(name))).encode("utf-8"))
    return h.hexdigest()


@dataclass(frozen=True)
class VerificationReport:
    """What a comparison actually established -- including its denominator.

    ``rows_compared`` is not decoration. A report saying "no mismatches" over
    zero rows means the check did not run, and a caller that prints only the
    verdict cannot tell that apart from a clean migration. Keeping the count in
    the result makes the denominator impossible to drop by accident.
    """

    table: str
    rows_compared: int
    source_rows: int
    destination_rows: int
    missing_ids: tuple[str, ...] = field(default_factory=tuple)
    extra_ids: tuple[str, ...] = field(default_factory=tuple)
    mismatched_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """True only if every row was compared and every comparison matched."""
        return not (self.missing_ids or self.extra_ids or self.mismatched_ids)

    def summary(self) -> str:
        """One line stating the verdict AND what it was measured over."""
        verdict = "OK" if self.ok else "MISMATCH"
        return (
            f"{self.table}: {verdict} "
            f"({self.rows_compared} row(s) compared; "
            f"source {self.source_rows}, destination {self.destination_rows}; "
            f"missing {len(self.missing_ids)}, extra {len(self.extra_ids)}, "
            f"differing {len(self.mismatched_ids)})"
        )


def _index_by_key(
    rows: Iterable[Mapping[str, Any]],
    key_columns: Sequence[str],
    columns: Sequence[str],
    side: str,
    table: str,
) -> dict[str, str]:
    index: dict[str, str] = {}
    for row in rows:
        key = "|".join(_canonical(normalize_value(row.get(k))) for k in key_columns)
        if key in index:
            raise MigrationVerificationError(
                f"{table}: duplicate key {key!r} on the {side} side over "
                f"key columns {list(key_columns)}. Verification cannot pair "
                f"rows one-to-one, so it would silently compare a row against "
                f"the wrong partner. Pick a key that is unique on both sides."
            )
        index[key] = row_checksum(row, columns)
    return index


def verify_table(
    table: str,
    source_rows: Iterable[Mapping[str, Any]],
    destination_rows: Iterable[Mapping[str, Any]],
    *,
    key_columns: Sequence[str],
    columns: Sequence[str],
    allow_empty: bool = False,
) -> VerificationReport:
    """Compare two row sets by key and content. Never raises on a clean match.

    Returns a :class:`VerificationReport`; the caller decides whether to raise.
    Both sides are consumed once, so generators streamed straight from a cursor
    are fine.

    ``allow_empty`` must be set explicitly to accept a table that genuinely has
    no rows (this store has three: ``notifications``, ``users``,
    ``user_names``). Without it an empty comparison RAISES, because "nothing to
    compare" and "everything matched" are otherwise indistinguishable in the
    result -- and the whole point of this module is that a pass has to mean
    something was checked.

    ``key_columns`` pairs rows across the two sides; ``columns`` is what gets
    compared once paired. Passing a key that is not unique raises rather than
    guessing a pairing.
    """
    if not key_columns:
        raise MigrationVerificationError(
            f"{table}: no key columns given, so rows cannot be paired between "
            f"source and destination. A positional comparison would depend on "
            f"row order, which neither backend guarantees without ORDER BY."
        )
    if not columns:
        raise MigrationVerificationError(
            f"{table}: no columns to compare. This would report a clean match "
            f"for any two row sets with the same keys, whatever their contents."
        )

    src = _index_by_key(source_rows, key_columns, columns, "source", table)
    dst = _index_by_key(destination_rows, key_columns, columns, "destination", table)

    if not src and not dst and not allow_empty:
        raise MigrationVerificationError(
            f"{table}: both sides are empty and allow_empty was not set. An "
            f"empty comparison establishes nothing, so it is refused rather "
            f"than reported as a pass. If this table is genuinely empty, say "
            f"so with allow_empty=True."
        )

    missing = sorted(set(src) - set(dst))
    extra = sorted(set(dst) - set(src))
    differing = sorted(k for k in (set(src) & set(dst)) if src[k] != dst[k])

    return VerificationReport(
        table=table,
        rows_compared=len(set(src) & set(dst)),
        source_rows=len(src),
        destination_rows=len(dst),
        missing_ids=tuple(missing),
        extra_ids=tuple(extra),
        mismatched_ids=tuple(differing),
    )


# EOF
