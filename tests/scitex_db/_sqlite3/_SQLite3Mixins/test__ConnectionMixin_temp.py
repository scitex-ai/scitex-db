"""Owned native files verify temporary-copy identity and cleanup isolation."""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import uuid

import pytest

from scitex_db import SQLite3
from scitex_db._sqlite3._SQLite3Mixins._ConnectionMixin import _ConnectionMixin


def _seed(path, value):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE signal(sample INTEGER)")
        conn.execute("INSERT INTO signal VALUES (?)", (value,))
        conn.commit()


def _rows(path):
    with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as conn:
        return conn.execute("SELECT sample FROM signal").fetchall()


@pytest.fixture
def copy_directory():
    return Path(tempfile.gettempdir())


_NEIGHBOR_BYTES = b"preserve unrelated neighboring activity"


@pytest.fixture
def copy_scope(copy_directory):
    token = uuid.uuid4().hex
    scope = {"paths": [], "neighbor": copy_directory / ("scitex-neighbor-" + token), "token": token}
    active = True
    thread = threading.get_ident()

    def observe(event, args):
        if active and event == "tempfile.mkstemp" and threading.get_ident() == thread:
            path = Path(args[0])
            if path.parent == copy_directory and path.name.startswith("scitex-db-"):
                if not scope["paths"]:
                    with scope["neighbor"].open("xb") as file:
                        file.write(_NEIGHBOR_BYTES)
                scope["paths"].append(path)

    sys.addaudithook(observe)
    try:
        yield scope
    finally:
        active = False
        scope["neighbor"].unlink(missing_ok=True)


def _owned_files_left(scope):
    candidates = [Path(str(path) + suffix) for path in scope["paths"] for suffix in ("", "-wal", "-shm", "-journal")]
    return [str(path) for path in candidates if path.exists()]


@pytest.fixture(params=["missing", "directory"])
def invalid_source(tmp_path, request):
    source = tmp_path / "source.db"
    if request.param == "directory":
        source.mkdir()
    return source


def _copy_error(owner, source):
    try:
        owner._create_temp_copy(str(source))
    except OSError as error:
        return error
    return None


def _readonly_error(db):
    try:
        db.conn.execute("INSERT INTO signal VALUES (84)")
    except sqlite3.OperationalError as error:
        return error
    return None


def _owner():
    owner = _ConnectionMixin.__new__(_ConnectionMixin)
    owner.temp_path = None
    return owner


@pytest.mark.parametrize("filename", ["signal.db", "recording?.db", "日本語 signal.db"])
def test_same_basename_copies_preserve_each_owners_rows_and_cleanup(tmp_path, copy_directory, copy_scope, filename):
    # Arrange
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    first, second = left / (copy_scope["token"] + filename), right / (copy_scope["token"] + filename)
    _seed(first, 42)
    _seed(second, 84)
    original = first.read_bytes(), second.read_bytes()
    owner1, owner2 = _owner(), _owner()
    # Act
    try:
        copy1 = Path(owner1._create_temp_copy(str(first)))
        copy2 = Path(owner2._create_temp_copy(str(second)))
        observed = copy1 != copy2, _rows(copy1), _rows(copy2)
        owner1.close()
        other_survives = copy2.exists()
    finally:
        owner1.close()
        owner2.close()
    # Assert
    assert (observed, other_survives, first.read_bytes(), second.read_bytes(), _owned_files_left(copy_scope), copy_scope["neighbor"].read_bytes()) == (
        (True, [(42,)], [(84,)]), True, *original, [], _NEIGHBOR_BYTES
    )


def test_temporary_copy_does_not_overwrite_or_remove_legacy_named_file(tmp_path, copy_directory, copy_scope):
    # Arrange
    source = tmp_path / (copy_scope["token"] + "signal.db")
    _seed(source, 42)
    witness = copy_directory / ("temp_" + source.name)
    with witness.open("xb") as file:
        file.write(b"owned unrelated witness")
    owner = _owner()
    # Act
    try:
        try:
            owner._create_temp_copy(str(source))
        finally:
            owner.close()
        preserved = witness.read_bytes() if witness.exists() else None
    finally:
        witness.unlink(missing_ok=True)
    # Assert
    assert (preserved, _owned_files_left(copy_scope), copy_scope["neighbor"].read_bytes()) == (b"owned unrelated witness", [], _NEIGHBOR_BYTES)


def test_copy_source_failure_leaves_no_allocated_file_or_owned_path(invalid_source, copy_directory, copy_scope):
    # Arrange
    owner = _owner()
    # Act
    error = _copy_error(owner, invalid_source)
    observed = isinstance(error, OSError), _owned_files_left(copy_scope), owner.temp_path, copy_scope["neighbor"].read_bytes()
    owner.close()
    # Assert
    assert observed == (True, [], None, _NEIGHBOR_BYTES)


@pytest.mark.parametrize("mode", ["rw", "rwc"])
def test_writable_temporary_copy_preserves_original_and_cleans_its_file(tmp_path, copy_directory, copy_scope, mode):
    # Arrange
    source = tmp_path / (copy_scope["token"] + "original.db")
    _seed(source, 42)
    original = source.read_bytes()
    # Act
    with SQLite3(str(source), use_temp=True, mode=mode) as db:
        temporary = Path(db.temp_path)
        initial = db.execute("SELECT sample FROM signal").fetchall()
        db.execute("INSERT INTO signal VALUES (84)")
        during = db.conn.execute("SELECT sample FROM signal ORDER BY sample").fetchall()
    # Assert
    assert (temporary.exists(), source.read_bytes(), _rows(source), initial, during, _owned_files_left(copy_scope), copy_scope["neighbor"].read_bytes()) == (
        False, original, [(42,)], [(42,)], [(42,), (84,)], [], _NEIGHBOR_BYTES
    )


def test_readonly_temporary_copy_refuses_writes_preserves_original_and_cleans_its_file(tmp_path, copy_directory, copy_scope):
    # Arrange
    source = tmp_path / (copy_scope["token"] + "original.db")
    _seed(source, 42)
    original = source.read_bytes()
    # Act
    with SQLite3(str(source), use_temp=True, mode="ro") as db:
        temporary = Path(db.temp_path)
        error = _readonly_error(db)
        during = db.execute("SELECT sample FROM signal").fetchall()
    # Assert
    assert (isinstance(error, sqlite3.OperationalError), temporary.exists(), source.read_bytes(), _rows(source), during, _owned_files_left(copy_scope), copy_scope["neighbor"].read_bytes()) == (
        True, False, original, [(42,)], [(42,)], [], _NEIGHBOR_BYTES
    )
