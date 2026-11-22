"""Native BLOB sample semantics and isolated Python-allocation controls."""
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest

from scitex_db import inspect
from scitex_db._inspect import OptimizedInspector

BLOB_BYTES = 16 * 1024 * 1024
SKIPPED_PEAK_LIMIT = 1024 * 1024


@pytest.fixture(params=["samples.db", "samples?#%3f 日本語.db"])
def sample_database(request, tmp_path):
    path = tmp_path / request.param
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('CREATE TABLE samples(id INTEGER PRIMARY KEY, payload BLOB, flex, label TEXT, amount REAL, "quoted""blob" BLOB, derived AS (flex) VIRTUAL)')
        connection.executemany('INSERT INTO samples(id,payload,flex,label,amount,"quoted""blob") VALUES(?,?,?,?,?,?)', [(1,b"A",b"BC","hello",1.5,b"Q"),(2,b"",None,"",2,None),(3,None,"plain","<BLOB 1 bytes>",None,b""),(4,"not-blob",7,"日本語",4,"text")])
    yield path


def _expected_samples():
    return [
        {"id":1,"payload":"<BLOB 1 bytes>","flex":"<BLOB 2 bytes>","label":"hello","amount":1.5,'quoted"blob':"<BLOB 1 bytes>","derived":"<BLOB 2 bytes>"},
        {"id":2,"payload":"<BLOB 0 bytes>","flex":None,"label":"","amount":2.0,'quoted"blob':None,"derived":None},
        {"id":3,"payload":None,"flex":"plain","label":"<BLOB 1 bytes>","amount":None,'quoted"blob':"<BLOB 0 bytes>","derived":"plain"},
        {"id":4,"payload":"not-blob","flex":7,"label":"日本語","amount":4.0,'quoted"blob':"text","derived":7},
    ]


def _seed_large_blob(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE large_samples(id INTEGER PRIMARY KEY,payload BLOB)")
        connection.execute("INSERT INTO large_samples VALUES(1,zeroblob(?))", (BLOB_BYTES,))


def _blob_python_peak(path, skip):
    script = '''import json,sys,tracemalloc
from pathlib import Path
from scitex_db import inspect
from scitex_db._inspect import OptimizedInspector
Path(sys.argv[1]).absolute().as_uri()
tracemalloc.start()
if sys.argv[2]=='True':
    result=inspect(sys.argv[1],table_names=['large_samples'],sample_size=1,verbose=False)
else:
    with OptimizedInspector(sys.argv[1]) as inspector:
        result=inspector.inspect_fast(table_names=['large_samples'],sample_size=1,skip_blob_content=False,verbose=False)
current,peak=tracemalloc.get_traced_memory()
tracemalloc.stop()
value=result[0]['sample_data'][0]['payload']
print(json.dumps({'peak':peak,'type':type(value).__name__,'length':len(value),'text':value if isinstance(value,str) else None,'row_count':result[0]['row_count']}))
'''
    result = subprocess.run([sys.executable,"-I","-c",script,str(path),str(skip)], cwd=path.parent, capture_output=True, text=True, timeout=60)
    result.check_returncode()
    return json.loads(result.stdout)


def test_default_inspect_preserves_mixed_blob_samples(sample_database):
    # Arrange
    expected = _expected_samples()
    # Act
    tables = inspect(str(sample_database), table_names=["samples"], sample_size=5, verbose=False)
    # Assert
    assert tables[0]["sample_data"] == expected


def test_raw_inspection_optout_retains_native_bytes(sample_database):
    # Arrange
    target = str(sample_database)
    # Act
    with OptimizedInspector(target) as inspector:
        tables = inspector.inspect_fast(table_names=["samples"], sample_size=5, skip_blob_content=False, verbose=False)
    # Assert
    assert (tables[0]["sample_data"][0]["payload"], tables[0]["sample_data"][0]["flex"], tables[0]["sample_data"][0]['quoted"blob'], tables[0]["sample_data"][0]["derived"]) == (b"A",b"BC",b"Q",b"BC")


def test_batch_stats_default_retains_raw_blob_values(sample_database):
    # Arrange
    target = str(sample_database)
    # Act
    with OptimizedInspector(target) as inspector:
        stats = inspector.get_table_stats_batch(["samples"], sample_size=1)
    # Assert
    assert (stats["samples"]["sample_data"][0]["payload"], stats["samples"]["sample_data"][0]["derived"]) == (b"A",b"BC")


def test_projected_samples_include_generated_columns(sample_database):
    # Arrange
    target = str(sample_database)
    # Act
    tables = inspect(target, table_names=["samples"], sample_size=1, verbose=False)
    # Assert
    assert (tables[0]["sample_data"][0]["derived"], list(tables[0]["sample_data"][0])) == ("<BLOB 2 bytes>", ["id","payload","flex","label","amount",'quoted"blob',"derived"])


@pytest.mark.parametrize("size", [0,1,3])
def test_projected_samples_preserve_requested_limit(sample_database, size):
    # Arrange
    expected = _expected_samples()[:size]
    # Act
    tables = inspect(str(sample_database), table_names=["samples"], sample_size=size, verbose=False)
    # Assert
    assert (tables[0]["sample_data"], tables[0]["row_count"], tables[0]["is_approximate"]) == (expected,4,False)


def test_projected_inspection_preserves_skip_count_flags(sample_database):
    # Arrange
    target = str(sample_database)
    # Act
    tables = inspect(target, table_names=["samples"], sample_size=1, skip_count=True, verbose=False)
    # Assert
    assert (tables[0]["row_count"], tables[0]["is_approximate"], tables[0]["sample_data"][0]["payload"]) == ("Not counted",None,"<BLOB 1 bytes>")


def test_skipped_blob_avoids_payload_sized_python_allocation(sample_database):
    # Arrange
    _seed_large_blob(sample_database)
    # Act
    observed = _blob_python_peak(sample_database, True)
    # Assert
    assert (observed["peak"] < SKIPPED_PEAK_LIMIT, observed["type"], observed["text"], observed["row_count"]) == (True,"str",f"<BLOB {BLOB_BYTES} bytes>",1)


def test_raw_blob_positive_control_measures_payload_allocation(sample_database):
    # Arrange
    _seed_large_blob(sample_database)
    # Act
    observed = _blob_python_peak(sample_database, False)
    # Assert
    assert (observed["peak"] >= BLOB_BYTES, observed["type"], observed["length"], observed["row_count"]) == (True,"bytes",BLOB_BYTES,1)


def test_projected_inspection_preserves_database_bytes(sample_database):
    # Arrange
    before = hashlib.sha256(sample_database.read_bytes()).hexdigest()
    # Act
    inspect(str(sample_database), table_names=["samples"], sample_size=5, verbose=False)
    # Assert
    assert hashlib.sha256(sample_database.read_bytes()).hexdigest() == before
