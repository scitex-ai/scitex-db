"""Real-file controls for literal migration source names and read-only admission."""

from contextlib import closing
import sqlite3

import pytest

from scitex_db._migrate._introspect import connect_readonly


@pytest.fixture(
    params=[
        ("source.db", "unrelated.db"),
        ("source#fragment.db", "source"),
        ("source?mode=rw&ignored=", "source"),
        ("source%23name.db", "source#name.db"),
        ("データ #1?.db", "データ "),
    ]
)
def stores(tmp_path, request):
    """A literal source and a distinct store a raw URI could select instead."""
    literal_name, decoy_name = request.param
    literal, decoy = tmp_path / literal_name, tmp_path / decoy_name
    for path, value in [(literal, "literal"), (decoy, "decoy")]:
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE sample (value TEXT)")
            conn.execute("INSERT INTO sample VALUES (?)", (value,))
            conn.commit()
    yield literal, decoy


def test_readonly_connection_selects_the_literal_filename(stores):
    # Arrange
    literal, _ = stores
    # Act
    with closing(connect_readonly(str(literal))) as conn:
        value = conn.execute("SELECT value FROM sample").fetchone()["value"]
    # Assert
    assert value == "literal"


def test_readonly_connection_refuses_insert_for_literal_filename(stores):
    # Arrange
    literal, _ = stores
    # Act
    with closing(connect_readonly(str(literal))) as conn:
        statement = "INSERT INTO sample VALUES ('forbidden')"
        # Assert
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(statement)


def test_missing_literal_source_never_opens_the_existing_decoy(stores):
    # Arrange
    literal, _ = stores
    literal.unlink()
    # Act
    source = str(literal)
    # Assert
    with pytest.raises(sqlite3.OperationalError):
        with closing(connect_readonly(source)):
            pass
