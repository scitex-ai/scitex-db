"""Smoke test for examples/01_basic.py.

Auto-generated stub (audit-project PS303). Replace with a real test
that runs the example end-to-end and asserts on its outputs.
"""

import importlib.util
from pathlib import Path

import pytest


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "01_basic.py"

pytestmark = pytest.mark.skipif(
    EXAMPLE.suffix != ".py",
    reason=f"non-python example: {EXAMPLE.suffix}",
)


def test_example_file_exists_on_disk():
    # Arrange
    path = EXAMPLE
    # Act
    exists = path.exists()
    # Assert
    assert exists, f"missing example file: {path}"


def test_example_spec_resolves_with_non_none_value():
    # Arrange
    target = EXAMPLE
    # Act
    spec = importlib.util.spec_from_file_location("ex", target)
    # Assert
    assert spec is not None


def test_example_spec_loader_is_not_none():
    # Arrange
    target = EXAMPLE
    spec = importlib.util.spec_from_file_location("ex", target)
    # Act
    loader = spec.loader
    # Assert
    assert loader is not None


def test_example_module_object_creates_from_spec():
    # Arrange
    target = EXAMPLE
    spec = importlib.util.spec_from_file_location("ex", target)
    # Act
    module = importlib.util.module_from_spec(spec)
    # Assert
    assert module is not None
