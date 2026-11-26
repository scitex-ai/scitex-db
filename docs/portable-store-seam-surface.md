# Portable-store seam: current surface and open requirements

The five modules in `scitex_db.store` exist. This document began as a receiving
proposal on 2026-08-02; it now distinguishes current implementations from
remaining proposal requirements. Do not reimplement the five modules on the
assumption that they are missing.

This seam provides guards, not connections, a query wrapper or interchangeable
`SQLite3`/`PostgreSQL` classes. Connections and transaction completion belong to
the caller. Adoption by the canonical scitex-cards store remains an operator
decision; this document does not authorize a migration or claim adoption.
Historical Cards incident counts, fleet versions and lock measurements from the
proposal have not been revalidated by the current source/SQLite checks.

## Dependency and import boundary

The five store modules import standard-library modules and each other. They do
not import a PostgreSQL driver: callers supply DB-API connections. PostgreSQL
class extras elsewhere in the distribution are a separate concern.
`scitex_db.__init__` uses lazy exports, so importing `scitex_db.store` need not
load the existing scientific/CLI surface. This describes import behavior, not a
promise that normal installation omits the distribution's declared NumPy,
Pandas or logging dependencies. It does not establish a cold-import time budget.

Owners: `src/scitex_db/store/{__init__,_url,_ddl,_tx,_backend,_portable_sql}.py`
and `src/scitex_db/__init__.py`.

## Location selection: `_url.py`

`parse_store_url(value: str) -> StoreLocation` accepts nonempty bare paths,
`sqlite://`/`sqlite3://`, and `postgresql://`/`postgres://`. Unknown multi-letter
URL schemes raise `UnknownStoreScheme`; empty and non-string values raise.
A one-letter scheme is treated as a drive/path spelling. SQLite URLs remove
the scheme and coerce the remainder to a path; this is not a general SQLite
URI/query-option parser. PostgreSQL DSNs remain verbatim strings: parsing does
not connect, authenticate, validate a server or establish database existence.

`StoreLocation` is a frozen dataclass with `dialect`, `path=None`, `dsn=None`.
Its constructor validates the dialect and the presence/mutual exclusion of the
selected field. PostgreSQL carries `path=None`; SQLite carries `dsn=None`.
These checks do not establish full runtime field typing or DSN validity.

`resolve_store(*, env, default=None)` reads the caller-named environment
variable. Unset/blank values use an explicit default or raise; the selected
value goes through `parse_store_url`. It does not load YAML, `.env`, or a
package-wide configuration precedence chain. A caller that bypasses this
resolver and passes a raw DSN to `Path` remains outside its protection.

Controls: `tests/scitex_db/store/test__url.py`, including real SQLite files
showing the unguarded DSN/path hazard and actual environment selection.

## DDL accounting: `_ddl.py`

The current frozen `DDLResult` has three nonnegative integer counters:
`submitted=0`, `executed=0`, `skipped=0`. Booleans are rejected and the
constructor enforces `executed + skipped == submitted`. The original proposal
specified a tuple of skipped statements; that is not the implemented field.
Per-statement skip reasons remain a proposal difference, not an available API.

`execute_ddl(conn, statements, *, run=True)` requires an actual boolean `run`;
other types (including `"False"`, integers and `None`) raise before statement
collection or cursor creation. It filters out non-string and blank entries,
then executes each remaining string through one cursor. `submitted`
counts these usable inputs, including deliberate skips. With `run=False`, no
cursor is opened and every usable input is counted as skipped. With `run=True`,
SQL errors propagate; no partial-success result is returned. The caller owns
commit/rollback and recovery from partial effects. This helper neither splits
a SQL script nor supplies automatic transaction atomicity.

`should_run_ddl(observed, required)` returns true for an unknown (`None`)
observed version; otherwise it checks `observed < required`, not inequality.
At/ahead-of-required versions do not need DDL. `required` must be an integer,
excluding booleans, even when `observed` is unknown; invalid required versions
raise before a DDL decision. Non-null observed versions are also validated.
A counter or version decision does not prove that a consuming application uses
this precondition on every connection path.

Controls: `tests/scitex_db/store/test__ddl.py` checks actual SQLite schema and
counts, deliberate no-op behavior, errors and version decisions.

## Write-transaction start: `_tx.py`

The actual signature is `begin_write(conn, *, lock_key: int, dialect: str) -> None`.
It is not a context manager. Both keywords are required; booleans/non-integer
lock keys and unknown dialects are refused. SQLite executes `BEGIN IMMEDIATE`.
The PostgreSQL branch issues `SELECT pg_advisory_xact_lock(%s)` with the key on
a cursor; it does not issue a separate `BEGIN`. Driver transaction/autocommit
configuration therefore matters. The function does not commit, roll back or
release a lock on a caller's behalf.

The original proposal required a context manager and an explicit PostgreSQL
transaction start. Those differences remain open; documenting the current
function does not qualify it as meeting that proposed lifecycle. An advisory
lock is cooperative: writers that do not acquire the same key are not excluded
by this mechanism. Serializable isolation is not a substitute for proving the
intended blocking contract.

`tests/scitex_db/store/test__tx.py` uses two native SQLite connections to observe
write refusal while held and success after commit. Its PostgreSQL-shaped fake
records statements/parameters only. It does not observe a PostgreSQL server
lock, blocking, release or autocommit lifetime. The proposed native test must
still observe the chosen lock from another connection while held and after
transaction completion; a successful function return is insufficient.

## Backend reporting: `_backend.py`

`describe_backend(source, *, config_source=None) -> BackendReport` accepts a
location or a connection. A location reports the selected dialect with unknown
server version. A connection is probed with `SELECT sqlite_version()` and then
`SHOW server_version`; unidentifiable connections report unknown fields.
`config_source` is a caller-supplied note, not an inferred configuration tier.

Failed probes attempt rollback and cursors are closed. Rollback may discard
pending caller work; use a suitable diagnostic connection, not an assumed
side-effect-free probe in an active transaction. No PostgreSQL server behavior
is established by the recording fake. The report validator refuses unknown
dialect strings and a known server version with an unknown dialect.

Controls: `tests/scitex_db/store/test__backend.py` uses real SQLite plus
PostgreSQL-shaped/unknown objects; fake rollback coverage is not native server
qualification.

## SQL spellings: `_portable_sql.py`

`null_safe_eq(column, *, dialect)` returns a dialect-specific comparison with a
`?` placeholder. `column` is interpolated as supplied: this is not an identifier
quoting or untrusted-input API. `to_paramstyle(sql, *, dialect)` keeps SQLite
text unchanged. Its PostgreSQL branch changes placeholders outside single
quotes to `%s`, preserves question marks in single-quoted strings, handles
doubled single quotes and doubles percent signs, including inside literals.
It is a small scanner, not a complete SQL lexer or query builder; comments,
double-quoted identifiers and dollar-quoted bodies are not separately parsed.
Do not infer safe rewriting for every SQL grammar from its selected cases.

The module exports its null-safe/version and SQLite-only upsert constants.
`tests/scitex_db/store/test__portable_sql.py` exercises native SQLite results
and the running SQLite version, plus generated PostgreSQL strings. A version
constant or generated SQL string does not certify execution on older SQLite
or a PostgreSQL server.

## Disposable SQLite example

This explicitly reviewed fixture creates and removes only its own database.
It checks location/DDL/backend results, caller-owned transaction completion and
observable write refusal from another native connection. It makes no network
connection and performs no existing-file migration or health/repair operation.

```python
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from scitex_db.store import begin_write, describe_backend, execute_ddl, parse_store_url

with TemporaryDirectory() as directory:
    path = Path(directory) / "store.db"
    location = parse_store_url(str(path))
    assert location.dialect == "sqlite" and location.path == path and location.dsn is None
    with closing(sqlite3.connect(path)) as first, closing(sqlite3.connect(path, timeout=0)) as other:
        result = execute_ddl(first, ["CREATE TABLE records (id INTEGER PRIMARY KEY)", " "])
        assert (result.submitted, result.executed, result.skipped) == (1, 1, 0)
        skipped = execute_ddl(first, ["CREATE TABLE skipped (id INTEGER)"], run=False)
        assert (skipped.submitted, skipped.executed, skipped.skipped) == (1, 0, 1)
        assert first.execute("SELECT name FROM sqlite_master WHERE name='skipped'").fetchall() == []
        first.commit()
        report = describe_backend(first, config_source="owned example")
        assert report.dialect == "sqlite" and report.server_version == sqlite3.sqlite_version
        assert report.config_source == "owned example"
        assert begin_write(first, lock_key=17, dialect="sqlite") is None
        try:
            other.execute("INSERT INTO records VALUES (1)")
        except sqlite3.OperationalError as error:
            assert "locked" in str(error).lower()
        else:
            raise AssertionError("the second writer was not refused")
        first.rollback()
        other.execute("INSERT INTO records VALUES (2)")
        other.commit()
        assert first.execute("SELECT id FROM records").fetchall() == [(2,)]
assert not path.exists()
```

## Environment-to-path warning and adoption

The registered `scitex_dev.linter.plugins` provider is
`scitex_db._linter_plugin:get_plugin`. It defines `STX-DB001` for literal
`SQLite3(...)` construction and `STX-DB002` for direct environment-to-path
coercion. The latter warns once per `Path(...)` or `pathlib.Path(...)` call
with a positional argument that is a literal-key `os.environ[...]`,
`environ[...]`, `os.environ.get(...)`, `environ.get(...)`, `os.getenv(...)`
or `getenv(...)` lookup. Lookup calls accept a first positional key or literal
`key=`. Names match case-insensitive `*_DB`, `*_URL`, `*_DSN`, or `*_STORE*`.

This is a warning, not a source rewrite, runtime refusal or DSN detector. A
matching variable may hold a legitimate filesystem path. Imports and bindings
are not resolved: shadowed canonical names can warn; aliases, intermediate
variables, wrappers and dynamic keys can be missed. Review the value's intended
contract and use `resolve_store(env=...)` when selecting a database backend.
The linter does not read the environment, open a database or evaluate source.

Owners: `_linter_plugin.py` and `_linter_env_path.py`.
`tests/scitex_db/test__linter_plugin.py` checks existing behavior, rule IDs,
entry points and prose. `test__linter_env_path.py` exercises the real Dev
linter dispatcher for matches, exclusions, one warning per call and original
source positions. The former DB002 proposal exemption is removed; no rule or
audit waiver is added. Transaction lifecycle and native PostgreSQL requirements
above remain outstanding. Installing a plugin is not proof of consumer adoption.

Future changes must retain effect-based checks and negative controls for the
guards they advertise; do not rename merged public names without an alias.
Neither current tests nor this document decide canonical-store adoption.
Import-only, fake, native SQLite, native PostgreSQL and consuming-host evidence
must remain separate. Static Markdown/build success does not establish runtime
behavior, minimum-platform support, generated/served content or adoption.
