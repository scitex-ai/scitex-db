#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared fixtures for the schema_change tests.

Lifted here rather than duplicated per module so each test file carries only
the behaviour it pins. The connection is a stand-in: every check in this
package takes its store access as an injected callable, precisely so the
package can be tested without a live database.
"""

from __future__ import annotations

import pytest

from scitex_db.schema_change import ArtifactProbe, PositiveControl


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
        fetch_one_int=lambda c, q: 3611,
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
