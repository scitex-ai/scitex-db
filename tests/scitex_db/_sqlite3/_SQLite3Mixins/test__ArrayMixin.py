"""Exercise stored shape parsing against actual SQLite array records."""

import sqlite3
from contextlib import closing

import numpy as np
import pytest

from scitex_db import SQLite3


def _seed(db_path, array, compress=False, shape=None):
    with SQLite3(str(db_path)) as db:
        db.create_table("arrays", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})
        db.save_array("arrays", array, additional_columns={"id": 1}, compress=compress, verbose=False)
        if shape is not None:
            db.execute("UPDATE arrays SET data_shape = ? WHERE id = 1", (shape,))


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("shape", [(), (0, 3), (2, 3), (2000,)])
def test_literal_shape_preserves_array_values(tmp_path, compress, shape):
    # Arrange
    expected = np.arange(np.prod(shape, dtype=int), dtype=np.float32).reshape(shape)
    path = tmp_path / "arrays.db"
    _seed(path, expected, compress=compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_array("arrays", "data", verbose=False)[0]
    # Assert
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("compress", [False, True])
def test_literal_shape_preserves_array_dtype(tmp_path, compress):
    # Arrange
    expected = np.arange(2000, dtype=np.int16)
    path = tmp_path / "arrays.db"
    _seed(path, expected, compress=compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_arrays("arrays", ["data"], verbose=False)["data"]
    # Assert
    assert actual.dtype == expected.dtype


@pytest.mark.parametrize("shape", ["(2, 3)", "[2, 3]"])
def test_literal_legacy_shape_forms_load(tmp_path, shape):
    # Arrange
    expected = np.arange(6).reshape(2, 3)
    path = tmp_path / "arrays.db"
    _seed(path, expected, shape=shape)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_array("arrays", "data", verbose=False)[0]
    # Assert
    assert np.array_equal(actual, expected)


def _expression(marker):
    return f"(__import__('pathlib').Path({str(marker)!r}).write_text('executed'), (4,))[1]"


def test_shape_expression_is_rejected(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    _seed(path, np.arange(4), shape=_expression(tmp_path / "marker"))
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        with SQLite3(str(path), mode="ro") as db:
            db.load_arrays("arrays", ["data"], verbose=False)


def test_shape_metadata_does_not_execute_python(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    marker = tmp_path / "marker"
    _seed(path, np.arange(4), shape=_expression(marker))
    # Act
    with SQLite3(str(path), mode="ro") as db:
        try:
            db.load_array("arrays", "data", verbose=False)
        except ValueError:
            pass
    # Assert
    assert not marker.exists()


def _helper_frame(path, array, shape=None, compress=False):
    _seed(path, array, compress=compress, shape=shape)
    columns = ["data", "data_dtype", "data_shape"]
    if compress:
        columns.append("data_is_compressed")
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", columns=columns, return_as="dataframe")


def _read_helper(path, frame, reader):
    with SQLite3(str(path), mode="ro") as db:
        if reader == "binary_to_array":
            row = frame.iloc[0]
            return db.binary_to_array(
                row["data"], row["data_dtype"], row["data_shape"],
                compressed=row.get("data_is_compressed") in [1, "1", True],
            )
        if reader == "get_array_dict":
            return db.get_array_dict(frame, columns=["data"])["data"][0]
        return db.decode_array_columns(frame, columns=["data"])["data"].iloc[0]


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("shape", ["(4,)", "[4]", "4"])
def test_helper_literal_shape_preserves_values(tmp_path, reader, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.arange(4, dtype=np.float32)
    frame = _helper_frame(path, expected, shape=shape)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
def test_helper_preserves_existing_dtype_conversion(tmp_path, reader, dtype):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _helper_frame(path, np.arange(4, dtype=dtype))
    expected_dtype = np.dtype(dtype).newbyteorder("=") if reader == "get_array_dict" else np.dtype(dtype)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert actual.dtype == expected_dtype


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
def test_helper_shape_expression_is_rejected(tmp_path, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _helper_frame(path, np.arange(4), shape=_expression(tmp_path / "marker"))
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        _read_helper(path, frame, reader)


@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
def test_helper_shape_metadata_does_not_execute_python(tmp_path, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    marker = tmp_path / "marker"
    frame = _helper_frame(path, np.arange(4), shape=_expression(marker))
    # Act
    try:
        _read_helper(path, frame, reader)
    except ValueError:
        pass
    # Assert
    assert not marker.exists()


@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("shape", [(), (0, 3), (2, 3), (2000,)])
def test_binary_helper_preserves_native_payload(tmp_path, compress, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.arange(np.prod(shape, dtype=int), dtype=np.float32).reshape(shape)
    frame = _helper_frame(path, expected, compress=compress)
    # Act
    actual = _read_helper(path, frame, "binary_to_array")
    # Assert
    assert np.array_equal(actual, expected)


def test_binary_helper_compressed_shape_expression_is_rejected(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    expression = _expression(tmp_path / "marker").replace("(4,)", "(2000,)")
    frame = _helper_frame(path, np.arange(2000), shape=expression, compress=True)
    # Act
    ctx = pytest.raises(ValueError)
    # Assert
    with ctx:
        _read_helper(path, frame, "binary_to_array")


def test_binary_helper_compressed_metadata_does_not_execute_python(tmp_path):
    # Arrange
    path = tmp_path / "arrays.db"
    marker = tmp_path / "marker"
    expression = _expression(marker).replace("(4,)", "(2000,)")
    frame = _helper_frame(path, np.arange(2000), shape=expression, compress=True)
    # Act
    try:
        _read_helper(path, frame, "binary_to_array")
    except ValueError:
        pass
    # Assert
    assert not marker.exists()


def _frame_table(path, table_kind):
    if table_kind == "native":
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE arrays (id INTEGER PRIMARY KEY, data BLOB)")
            connection.commit()
    else:
        with SQLite3(str(path)) as db:
            db.create_table("arrays", {"id": "INTEGER PRIMARY KEY", "data": "BLOB"})


def _stored_frame(path, array, compress, table_kind):
    _frame_table(path, table_kind)
    with SQLite3(str(path)) as db:
        db.save_array("arrays", array, additional_columns={"id": 1}, compress=compress, verbose=False)
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", order_by="id", return_as="dataframe")


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("size", [128, 2048])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
def test_stored_frame_compression_preserves_values(tmp_path, reader, compress, size, dtype, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.arange(size, dtype=dtype)
    frame = _stored_frame(path, expected, compress, table_kind)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert np.array_equal(actual, expected)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("size", [128, 2048])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
def test_stored_frame_compression_preserves_dtype_conversion(tmp_path, reader, compress, size, dtype, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _stored_frame(path, np.arange(size, dtype=dtype), compress, table_kind)
    expected_dtype = np.dtype(dtype).newbyteorder("=") if reader == "get_array_dict" else np.dtype(dtype)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert actual.dtype == expected_dtype


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("size", [128, 2048])
def test_stored_frame_decoding_preserves_database_bytes(tmp_path, reader, compress, size, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _stored_frame(path, np.arange(size, dtype=np.float32), compress, table_kind)
    before = path.read_bytes()
    # Act
    _read_helper(path, frame, reader)
    # Assert
    assert path.read_bytes() == before


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("size", [128, 2048])
def test_stored_frame_has_native_compression_flag(tmp_path, compress, size, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    array = np.arange(size, dtype=np.float32)
    flag = int(compress and array.nbytes > 1024)
    expected_flag = str(flag) if table_kind == "native" else flag
    # Act
    frame = _stored_frame(path, array, compress, table_kind)
    # Assert
    assert frame["data_is_compressed"].iloc[0] == expected_flag


def _mixed_frame(path, first, second, table_kind):
    _frame_table(path, table_kind)
    with SQLite3(str(path)) as db:
        db.save_array("arrays", first, additional_columns={"id": 1}, compress=False, verbose=False)
        db.save_array("arrays", second, additional_columns={"id": 2}, compress=True, verbose=False)
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", order_by="id", return_as="dataframe")


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("dtype", ["float32", "int16"])
def test_stored_frame_mixed_compression_decodes_each_row(tmp_path, reader, dtype, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    first = np.arange(2048, dtype=dtype)
    second = first + 1
    frame = _mixed_frame(path, first, second, table_kind)
    expected = np.stack([first, second])
    # Act
    with SQLite3(str(path), mode="ro") as db:
        if reader == "get_array_dict":
            actual = db.get_array_dict(frame, columns=["data"])["data"]
        else:
            decoded = db.decode_array_columns(frame, columns=["data"])
            actual = np.stack(decoded["data"].tolist())
    # Assert
    assert np.array_equal(actual, expected)


def _discovery_frame(path, table_kind, names, compress=False):
    schema = {"id": "INTEGER PRIMARY KEY", "label": "TEXT", "score": "REAL"}
    schema.update({name: "BLOB" for name in names})
    if table_kind == "native":
        with closing(sqlite3.connect(path)) as connection:
            definition = ", ".join(f"{name} {kind}" for name, kind in schema.items())
            connection.execute(f"CREATE TABLE arrays ({definition})")
            connection.commit()
    else:
        with SQLite3(str(path)) as db:
            db.create_table("arrays", schema)
    expected = {
        names[0]: np.arange(2048, dtype=np.float32).reshape(1024, 2),
        names[1]: np.arange(12, dtype=np.int16),
    }
    with SQLite3(str(path)) as db:
        db.save_arrays("arrays", expected, additional_columns={"id": 1, "label": "trial", "score": 1.25}, compress=compress, verbose=False)
    with SQLite3(str(path), mode="ro") as db:
        frame = db.get_rows("arrays", order_by="id", return_as="dataframe")
    return frame, expected


def _invoke_default(path, frame, reader, **hints):
    with SQLite3(str(path), mode="ro") as db:
        if reader == "get_array_dict":
            return db.get_array_dict(frame, **hints)
        return db.decode_array_columns(frame, **hints)


def _default_value(result, reader, name):
    if reader == "get_array_dict":
        return result[name][0]
    return result[name].iloc[0]


@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("names", [("signal", "other"), ("signal_dtype", "other_shape"), ("signal_hash", "other_is_compressed")])
def test_default_discovery_decodes_metadata_backed_arrays(tmp_path, reader, table_kind, compress, names):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _discovery_frame(path, table_kind, names, compress)
    # Act
    actual = _invoke_default(path, frame, reader)
    # Assert
    assert all(np.array_equal(_default_value(actual, reader, name), value) for name, value in expected.items())


@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("names", [("signal", "other"), ("signal_dtype", "other_shape"), ("signal_hash", "other_is_compressed")])
def test_default_discovery_preserves_result_column_contract(tmp_path, reader, table_kind, compress, names):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _discovery_frame(path, table_kind, names, compress)
    expected_names = list(names) if reader == "get_array_dict" else list(frame.columns)
    # Act
    actual = _invoke_default(path, frame, reader)
    # Assert
    assert list(actual) == expected_names


@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("empty", [False, True])
def test_default_discovery_without_arrays_preserves_scalar_frame(tmp_path, reader, empty):
    # Arrange
    path = tmp_path / "arrays.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE scalars (id INTEGER PRIMARY KEY, label TEXT)")
        if not empty:
            connection.executemany("INSERT INTO scalars VALUES (?, ?)", [(1, "first"), (2, "second")])
        connection.commit()
    with SQLite3(str(path), mode="ro") as db:
        frame = db.get_rows("scalars", order_by="id", return_as="dataframe")
    before = frame.copy(deep=True)
    # Act
    actual = _invoke_default(path, frame, reader)
    # Assert
    assert actual == {} if reader == "get_array_dict" else actual.equals(before)


@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("shape", [(2048,), (1024, 2)])
def test_default_discovery_retains_dtype_shape_hint_path(tmp_path, reader, table_kind, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, values = _discovery_frame(path, table_kind, ("signal", "other"))
    raw_frame = frame[["signal"]].copy()
    expected = values["signal"].reshape(shape)
    # Act
    result = _invoke_default(path, raw_frame, reader, dtype=np.dtype("float32"), shape=shape)
    # Assert
    assert np.array_equal(_default_value(result, reader, "signal"), expected)


def _empty_array_frame(path, table_kind, names):
    _discovery_frame(path, table_kind, names, compress=True)
    with SQLite3(str(path)) as db:
        db.execute("DELETE FROM arrays")
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", order_by="id", return_as="dataframe")


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("names", [("signal", "other"), ("signal_dtype", "other_is_compressed")])
@pytest.mark.parametrize("selection", ["default", "explicit"])
def test_empty_array_dict_matches_main_reader_absence(tmp_path, table_kind, names, selection):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _empty_array_frame(path, table_kind, names)
    options = {} if selection == "default" else {"columns": list(names)}
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", **options)
    # Assert
    assert actual == {name: None for name in names}


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("names", [("signal", "other"), ("signal_dtype", "other_is_compressed")])
@pytest.mark.parametrize("selection", ["default", "explicit"])
def test_empty_array_decoder_preserves_schema_and_dtypes(tmp_path, table_kind, names, selection):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _empty_array_frame(path, table_kind, names)
    before = frame.copy(deep=True)
    options = {} if selection == "default" else {"columns": list(names)}
    # Act
    actual = _invoke_default(path, frame, "decode_array_columns", **options)
    # Assert
    assert actual.equals(before)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("names", [("signal", "other"), ("signal_dtype", "other_is_compressed")])
@pytest.mark.parametrize("selection", ["default", "explicit"])
def test_empty_array_decoder_retains_input_identity(tmp_path, table_kind, names, selection):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _empty_array_frame(path, table_kind, names)
    options = {} if selection == "default" else {"columns": list(names)}
    # Act
    actual = _invoke_default(path, frame, "decode_array_columns", **options)
    # Assert
    assert actual is frame


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("names", [("signal", "other"), ("signal_dtype", "other_is_compressed")])
def test_main_reader_empty_array_policy_is_none(tmp_path, table_kind, names):
    # Arrange
    path = tmp_path / "arrays.db"
    _empty_array_frame(path, table_kind, names)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_arrays("arrays", columns=list(names), verbose=False)
    # Assert
    assert actual == {name: None for name in names}


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("shape", [(2048,), (1024, 2)])
def test_empty_hint_array_dict_has_no_fabricated_array(tmp_path, table_kind, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _empty_array_frame(path, table_kind, ("signal", "other"))[["signal"]].copy()
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", dtype=np.dtype("float32"), shape=shape)
    # Assert
    assert actual == {"signal": None}


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("shape", [(2048,), (1024, 2)])
def test_empty_hint_decoder_preserves_frame(tmp_path, table_kind, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _empty_array_frame(path, table_kind, ("signal", "other"))[["signal"]].copy()
    before = frame.copy(deep=True)
    # Act
    actual = _invoke_default(path, frame, "decode_array_columns", dtype=np.dtype("float32"), shape=shape)
    # Assert
    assert actual.equals(before)


@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
def test_present_zero_length_array_is_not_absence(tmp_path, reader, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.empty((0, 3), dtype=np.float32)
    frame = _stored_frame(path, expected, False, table_kind)
    # Act
    actual = _read_helper(path, frame, reader)
    # Assert
    assert (actual.shape, actual.dtype) == (expected.shape, expected.dtype)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("missing", ["dtype", "shape", "both"])
@pytest.mark.parametrize("after_valid", [False, True])
@pytest.mark.parametrize("rows", [slice(None), slice(0)], ids=["populated", "empty"])
def test_dictionary_missing_metadata_rejects_selection(tmp_path, table_kind, missing, after_valid, rows):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _discovery_frame(path, table_kind, ("signal", "other"))
    removed = [f"other_{part}" for part in ("dtype", "shape") if missing in (part, "both")]
    frame = frame.drop(columns=removed)
    frame = frame.iloc[rows].copy()
    columns = ["signal", "other"] if after_valid else ["other", "signal"]
    with SQLite3(str(path), mode="ro") as db:
        # Act
        rejection = pytest.raises(ValueError, match="other.*requires.*dtype.*shape")
        # Assert
        with rejection:
            db.get_array_dict(frame, columns=columns)


@pytest.mark.parametrize("column", ["label", "id"])
@pytest.mark.parametrize("after_valid", [False, True])
def test_dictionary_scalar_selection_rejects_previous_array_reuse(tmp_path, column, after_valid):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _discovery_frame(path, "native", ("signal", "other"))
    columns = ["signal", column] if after_valid else [column, "signal"]
    with SQLite3(str(path), mode="ro") as db:
        # Act
        rejection = pytest.raises(ValueError, match=f"{column}.*requires.*dtype.*shape")
        # Assert
        with rejection:
            db.get_array_dict(frame, columns=columns)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("missing", ["dtype", "shape", "both"])
@pytest.mark.parametrize("after_valid", [False, True])
@pytest.mark.parametrize("rows", [slice(None), slice(0)], ids=["populated", "empty"])
def test_dictionary_rejected_selection_preserves_frame(tmp_path, table_kind, missing, after_valid, rows):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _discovery_frame(path, table_kind, ("signal", "other"))
    removed = [f"other_{part}" for part in ("dtype", "shape") if missing in (part, "both")]
    frame = frame.drop(columns=removed).iloc[rows].copy()
    columns = ["signal", "other"] if after_valid else ["other", "signal"]
    original = frame.copy(deep=True)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        try:
            db.get_array_dict(frame, columns=columns)
        except ValueError:
            pass
    # Assert
    assert frame.equals(original)



def _null_array_frame(path, table_kind, row_count, metadata, compress, other_present=False):
    _, expected = _discovery_frame(path, table_kind, ("signal", "other"), compress)
    columns = ["signal"] if other_present else list(expected)
    assignments = [f"{name} = NULL" for name in columns]
    if metadata == "null":
        assignments.extend(f"{name}_{suffix} = NULL" for name in columns for suffix in ("dtype", "shape", "is_compressed", "hash"))
    with SQLite3(str(path)) as db:
        for row_id in range(2, row_count + 1):
            db.save_arrays("arrays", expected, additional_columns={"id": row_id}, compress=compress, verbose=False)
        db.execute("UPDATE arrays SET " + ", ".join(assignments))
    with SQLite3(str(path), mode="ro") as db:
        frame = db.get_rows("arrays", order_by="id", return_as="dataframe")
    return frame, expected


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("row_count", [1, 3])
@pytest.mark.parametrize("metadata", ["retained", "null"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("selection", ["default", "explicit"])
def test_all_null_dictionary_columns_match_absence_policy(tmp_path, table_kind, row_count, metadata, compress, selection):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _null_array_frame(path, table_kind, row_count, metadata, compress)
    options = {} if selection == "default" else {"columns": ["signal", "other"]}
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", **options)
    # Assert
    assert all(actual[name] is None for name in ("signal", "other"))


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("row_count", [1, 3])
@pytest.mark.parametrize("metadata", ["retained", "null"])
@pytest.mark.parametrize("compress", [False, True])
def test_main_reader_all_null_columns_return_none(tmp_path, table_kind, row_count, metadata, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    _null_array_frame(path, table_kind, row_count, metadata, compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_arrays("arrays", columns=["signal", "other"], verbose=False)
    # Assert
    assert all(actual[name] is None for name in ("signal", "other"))


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("row_count", [1, 3])
def test_all_null_dictionary_hint_column_returns_none(tmp_path, table_kind, row_count):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _null_array_frame(path, table_kind, row_count, "null", True)
    frame = frame[["signal"]].copy()
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", dtype=np.dtype("float32"), shape=(2048,))
    # Assert
    assert actual["signal"] is None


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("selection", ["default", "explicit"])
def test_all_null_dictionary_column_does_not_hide_populated_neighbor(tmp_path, table_kind, compress, selection):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _null_array_frame(path, table_kind, 3, "retained", compress, other_present=True)
    options = {} if selection == "default" else {"columns": ["signal", "other"]}
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", **options)
    # Assert
    assert np.array_equal(actual["other"], np.stack([expected["other"]] * 3))


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("selection", ["default", "explicit"])
def test_all_null_dictionary_absence_is_per_column(tmp_path, table_kind, compress, selection):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _null_array_frame(path, table_kind, 3, "retained", compress, other_present=True)
    options = {} if selection == "default" else {"columns": ["signal", "other"]}
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", **options)
    # Assert
    assert actual["signal"] is None



def _raw_hint_frame(path, dtype, shape, table_kind, empty=False, null=False):
    expected = np.full(shape, 7, dtype=np.dtype(dtype))
    _stored_frame(path, expected, False, table_kind)
    with SQLite3(str(path)) as db:
        if empty:
            db.execute("DELETE FROM arrays")
        elif null:
            db.execute("UPDATE arrays SET data = NULL")
    with SQLite3(str(path), mode="ro") as db:
        frame = db.get_rows("arrays", columns=["data"], return_as="dataframe")
    return frame, expected


def _read_fallback_hint(path, frame, reader, dtype, shape, explicit=True):
    options = {"columns": ["data"]} if explicit else {}
    with SQLite3(str(path), mode="ro") as db:
        if reader == "binary_to_array":
            return db.binary_to_array(frame["data"].iloc[0], dtype=dtype, shape=shape)
        if reader == "get_array_dict":
            return db.get_array_dict(frame, dtype=dtype, shape=shape, **options)["data"][0]
        return db.decode_array_columns(frame, dtype=dtype, shape=shape, **options)["data"].iloc[0]


def _fallback_expected(path, expected, reader):
    if reader == "get_array_dict":
        return expected.astype(expected.dtype.newbyteorder("="))
    if reader == "decode_array_columns" and expected.shape == ():
        with SQLite3(str(path), mode="ro") as db:
            frame = db.get_rows("arrays", return_as="dataframe")
            decoded = db.decode_array_columns(frame, columns=["data"])
        return decoded["data"].iloc[0]
    return expected


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["binary_to_array", "get_array_dict", "decode_array_columns"])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
@pytest.mark.parametrize("shape", [(), (0,), (2, 3)])
def test_fallback_hint_preserves_native_payload(tmp_path, table_kind, reader, dtype, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _raw_hint_frame(path, dtype, shape, table_kind)
    target = _fallback_expected(path, expected, reader)
    # Act
    actual = _read_fallback_hint(path, frame, reader, np.dtype(dtype), shape)
    # Assert
    assert (actual.shape, actual.dtype, actual.tobytes()) == (target.shape, target.dtype, target.tobytes())


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("reader", ["get_array_dict", "decode_array_columns"])
def test_scalar_hint_default_selection_decodes_value(tmp_path, table_kind, reader):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _raw_hint_frame(path, "float32", (), table_kind)
    target = _fallback_expected(path, expected, reader)
    # Act
    actual = _read_fallback_hint(path, frame, reader, expected.dtype, (), explicit=False)
    # Assert
    assert (actual.shape, actual.dtype, actual.tobytes()) == (target.shape, target.dtype, target.tobytes())


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
def test_scalar_hint_empty_dictionary_has_absence_result(tmp_path, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _raw_hint_frame(path, "float32", (), table_kind, empty=True)
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", dtype=expected.dtype, shape=())
    # Assert
    assert actual["data"] is None


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
def test_scalar_hint_empty_decoder_preserves_frame(tmp_path, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _raw_hint_frame(path, "float32", (), table_kind, empty=True)
    before = frame.copy(deep=True)
    # Act
    actual = _invoke_default(path, frame, "decode_array_columns", dtype=expected.dtype, shape=())
    # Assert
    assert actual.equals(before)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
def test_scalar_hint_null_dictionary_has_absence_result(tmp_path, table_kind):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, expected = _raw_hint_frame(path, "float32", (), table_kind, null=True)
    # Act
    actual = _invoke_default(path, frame, "get_array_dict", dtype=expected.dtype, shape=())
    # Assert
    assert actual["data"] is None


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype,shape", [(None, ()), ("float32", None), (None, None)])
def test_fallback_hint_missing_component_preserves_binary(tmp_path, table_kind, dtype, shape):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _ = _raw_hint_frame(path, "float32", (), table_kind)
    blob = frame["data"].iloc[0]
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.binary_to_array(blob, dtype=dtype, shape=shape)
    # Assert
    assert actual is blob


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype", ["float32", "int16", ">i4"])
def test_scalar_hint_metadata_control_preserves_dtype(tmp_path, table_kind, dtype):
    # Arrange
    path = tmp_path / "arrays.db"
    expected = np.full((), 7, dtype=np.dtype(dtype))
    frame = _stored_frame(path, expected, False, table_kind)
    target = expected
    # Act
    actual = _read_helper(path, frame, "decode_array_columns")
    # Assert
    assert (actual.shape, actual.dtype, actual.tobytes()) == (target.shape, target.dtype, target.tobytes())



def _mixed_null_frame(path, table_kind, dtype, missing_id, compress):
    _frame_table(path, table_kind)
    arrays = [np.full((512, 4), row_id, dtype=np.dtype(dtype)) for row_id in (1, 2, 3)]
    with SQLite3(str(path)) as db:
        for row_id, array in enumerate(arrays, 1):
            db.save_array("arrays", array, additional_columns={"id": row_id}, compress=compress, verbose=False)
        db.execute("UPDATE arrays SET data = NULL, data_dtype = NULL, data_shape = NULL, data_is_compressed = NULL, data_hash = NULL WHERE id = ?", (missing_id,))
    with SQLite3(str(path), mode="ro") as db:
        frame = db.get_rows("arrays", order_by="id", return_as="dataframe")
    expected = [array.copy() for array in arrays]
    expected[missing_id - 1][...] = np.nan
    return frame, np.stack(expected), arrays


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype", ["float32", "float64", ">f4"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
@pytest.mark.parametrize("compress", [False, True])
def test_mixed_null_floating_main_reader_fills_nan(tmp_path, table_kind, dtype, missing_id, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    _, expected, _ = _mixed_null_frame(path, table_kind, dtype, missing_id, compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_arrays("arrays", columns=["data"], verbose=False)["data"]
    # Assert
    assert np.array_equal(actual, expected, equal_nan=True)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype", ["float32", "float64", ">f4"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
@pytest.mark.parametrize("compress", [False, True])
def test_mixed_null_floating_main_reader_retains_shape_dtype(tmp_path, table_kind, dtype, missing_id, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    _, expected, _ = _mixed_null_frame(path, table_kind, dtype, missing_id, compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.load_arrays("arrays", columns=["data"], verbose=False)["data"]
    # Assert
    assert (actual.shape, actual.dtype) == (expected.shape, expected.dtype)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
@pytest.mark.parametrize("compress", [False, True])
def test_mixed_null_decoder_retains_none_cell(tmp_path, table_kind, missing_id, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, _ = _mixed_null_frame(path, table_kind, "float32", missing_id, compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.decode_array_columns(frame)
    # Assert
    assert actual["data"].iloc[missing_id - 1] is None


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
@pytest.mark.parametrize("compress", [False, True])
def test_mixed_null_decoder_preserves_present_values(tmp_path, table_kind, missing_id, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, expected = _mixed_null_frame(path, table_kind, "float32", missing_id, compress)
    # Act
    with SQLite3(str(path), mode="ro") as db:
        actual = db.decode_array_columns(frame)
    # Assert
    assert all(np.array_equal(actual["data"].iloc[index], expected[index]) for index in range(3) if index != missing_id - 1)


def _read_mixed_null_result(path, frame, reader):
    with SQLite3(str(path), mode="ro") as db:
        if reader == "load_arrays":
            return db.load_arrays("arrays", columns=["data"], verbose=False)
        return db.decode_array_columns(frame)


@pytest.mark.parametrize("reader", ["load_arrays", "decode_array_columns"])
@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
def test_mixed_null_reader_preserves_main_database_bytes(tmp_path, reader, table_kind, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, _ = _mixed_null_frame(path, table_kind, "float32", 2, compress)
    before = path.read_bytes()
    # Act
    _read_mixed_null_result(path, frame, reader)
    # Assert
    assert path.read_bytes() == before



def _floating_null_stacks(path, frame, dtype=None, shape=None, explicit=False):
    options = {"columns": ["data"]} if explicit else {}
    with SQLite3(str(path), mode="ro") as db:
        expected = db.load_arrays("arrays", columns=["data"], verbose=False)["data"]
        actual = db.get_array_dict(frame, dtype=dtype, shape=shape, **options)["data"]
    return actual, expected


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype", ["float32", "float64", ">f4"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
@pytest.mark.parametrize("compress", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_floating_null_dictionary_matches_main(tmp_path, table_kind, dtype, missing_id, compress, explicit):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, _ = _mixed_null_frame(path, table_kind, dtype, missing_id, compress)
    # Act
    actual, expected = _floating_null_stacks(path, frame, explicit=explicit)
    # Assert
    assert (actual.shape, actual.dtype) == (expected.shape, expected.dtype) and np.array_equal(actual, expected, equal_nan=True)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype", ["float32", "float64", ">f4"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
def test_floating_null_raw_hint_matches_main(tmp_path, table_kind, dtype, missing_id):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, _ = _mixed_null_frame(path, table_kind, dtype, missing_id, False)
    frame = frame[["data"]].copy()
    # Act
    actual, expected = _floating_null_stacks(path, frame, dtype=np.dtype(dtype), shape=(512, 4))
    # Assert
    assert (actual.shape, actual.dtype) == (expected.shape, expected.dtype) and np.array_equal(actual, expected, equal_nan=True)


def _scalar_floating_null_frame(path, table_kind, dtype, missing_id):
    _frame_table(path, table_kind)
    with SQLite3(str(path)) as db:
        for row_id in (1, 2, 3):
            db.save_array("arrays", np.full((), row_id, dtype=np.dtype(dtype)), additional_columns={"id": row_id}, verbose=False)
        db.execute("UPDATE arrays SET data = NULL, data_dtype = NULL, data_shape = NULL, data_is_compressed = NULL, data_hash = NULL WHERE id = ?", (missing_id,))
    with SQLite3(str(path), mode="ro") as db:
        return db.get_rows("arrays", order_by="id", return_as="dataframe")


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("dtype", ["float32", "float64", ">f4"])
@pytest.mark.parametrize("missing_id", [1, 2, 3])
@pytest.mark.parametrize("explicit", [False, True])
def test_floating_null_scalar_matches_main(tmp_path, table_kind, dtype, missing_id, explicit):
    # Arrange
    path = tmp_path / "arrays.db"
    frame = _scalar_floating_null_frame(path, table_kind, dtype, missing_id)
    # Act
    actual, expected = _floating_null_stacks(path, frame, explicit=explicit)
    # Assert
    assert (actual.shape, actual.dtype) == (expected.shape, expected.dtype) and np.array_equal(actual, expected, equal_nan=True)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
def test_floating_null_dictionary_preserves_input_frame(tmp_path, table_kind, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, _ = _mixed_null_frame(path, table_kind, "float32", 2, compress)
    before = frame.copy(deep=True)
    # Act
    _floating_null_stacks(path, frame)
    # Assert
    assert frame.equals(before)


@pytest.mark.parametrize("table_kind", ["wrapper", "native"])
@pytest.mark.parametrize("compress", [False, True])
def test_floating_null_dictionary_preserves_main_database_bytes(tmp_path, table_kind, compress):
    # Arrange
    path = tmp_path / "arrays.db"
    frame, _, _ = _mixed_null_frame(path, table_kind, "float32", 2, compress)
    before = path.read_bytes()
    # Act
    _floating_null_stacks(path, frame)
    # Assert
    assert path.read_bytes() == before
