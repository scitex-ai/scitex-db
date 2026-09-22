"""Enforces SciTeX skills quality checklist §1–§4."""

from pathlib import Path

import pytest

scitex_dev = pytest.importorskip("scitex_dev")
from scitex_dev._skills_quality_pytest import make_skill_quality_tests

test_skills_quality = make_skill_quality_tests(
    package_root=Path(__file__).resolve().parents[1]
)


def test_skills_leaf_files_exist():
    # Arrange
    skills_dir = Path(__file__).resolve().parents[2] / "src" / "scitex_db" / "_skills"
    # Act
    leaves = [p for p in skills_dir.rglob("*.md") if p.is_file()]
    # Assert
    assert len(leaves) >= 1
