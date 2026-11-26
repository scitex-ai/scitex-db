---
description: |
  [TOPIC] Porting a package from SQLite to PostgreSQL
  [DETAILS] The failures that produce NO error — silent wrong-store writes, DDL that runs zero statements, lock semantics that differ, engine reported wrong. Checklist before and during a backend move.
tags: [scitex-db-sqlite-to-postgres, scitex-db-migration, scitex-db]
---

# SQLite → PostgreSQL: the failures that do not raise

Written from a real migration: `scitex-cards` moved its canonical store
from SQLite to PostgreSQL over 2026-07-31 → 2026-08-01. Twelve distinct
defects were found. **Nine produced no error at all** — they returned an
id, created a file, printed a green check, or reported a matching
version string.

That is the durable lesson, and it is not any single incompatibility.
The examples below do not exhaust the incompatibilities. A
backend port moves working code into an environment where its old
assumptions are silently untrue, and the code keeps reporting success.

A crash would have been cheap.

## The one habit that catches this class

Verify the **artifact and the effect**, never the report:

- read the SQL that was executed, not the test result
- read the file that was installed, not the version metadata
- read the inode the process opened, not the path you built
- read what the fail-soft handler logged, not what the caller returned

## Five hazards to guard before you start

### 1. A DSN is not a path

`Path("postgresql://host/db")` does not fail. It collapses to the
relative path `postgresql:/host/db`, which SQLite will happily *create*
under the caller's working directory. The process then serves an empty
store and reports healthy.

This shipped twice in one day — once in a stale container image, once in
a notification rail whose `enqueue` returned a valid id after writing to
a store nobody would ever read.

Guard: detect a URL scheme *before* any `Path()` coercion, and raise
rather than fall back.

### 2. "The DDL ran" and "the DDL call did not raise" are different claims

Execute DDL statement by statement and **return the count**. A script
that silently ran zero statements otherwise passes as success, and the
triggers you believe are installed are not.

Guard: assert the returned count against what you handed in. If a
construct cannot be ported, raise naming it — never skip it.

### 3. Write-lock semantics are not portable

SQLite `BEGIN IMMEDIATE` starts a write transaction immediately and can
fail with `SQLITE_BUSY` when another writer is active
([SQLite transaction rules](https://www.sqlite.org/lang_transaction.html)).
PostgreSQL transaction-level advisory locks can coordinate cooperating
writers using the same key, but do not prevent writes from clients that
ignore that convention; they are not a database-wide SQLite write lock
([PostgreSQL advisory locks](https://www.postgresql.org/docs/19/explicit-locking.html#ADVISORY-LOCKS)).

`SERIALIZABLE` can require transaction retries after a serialization
failure; it does not promise the same waiting contract
([PostgreSQL isolation rules](https://www.postgresql.org/docs/19/transaction-iso.html#XACT-SERIALIZABLE)).

Guard: one named "begin a write transaction" primitive per dialect, and
a test that runs two concurrent writers.

### 4. Ask the connection which engine it is

A health check that asserts the literal string `"SQLite"` reports the
wrong engine on every PostgreSQL deployment, forever, while passing.

Guard: report the live backend and the config tier that selected it.
Three-valued: SQLite / PostgreSQL / **unknown** — never default to a
guess.

### 4b. SQLite stores the CREATE text you wrote, not the schema you meant

`sqlite_schema.sql` (also accessible through `sqlite_master`) retains
much of the original DDL text, but applies documented normalization and
can change after `ALTER TABLE`. It is not a byte-for-byte record of the
submitted statement. Text differences can still occur between equivalent
schemas; compare the intended schema properties as well as stored SQL
([SQLite schema table](https://www.sqlite.org/schematab.html)).

Measured by scitex-cards, 2026-08-02: an explanatory comment placed
inside a `CREATE TABLE` column list made a database built via
statement-by-statement `execute_ddl` stop matching one built via
`executescript`. Three CI legs went red on a single assertion.

Worth knowing because a porting package would not guess it, and because
schema comparison is exactly the tool you reach for to convince yourself
a migration was faithful.

The test that caught it existed only because of an earlier near-miss —
its docstring records that "eleven unit tests passed while the splitter
was cutting four append-only triggers in half". 187 tests had been run
locally beforehand and that file was in neither selection: the thing
that would have told them was present and not consulted.

### 5. Standard SQL is not portable SQL

`IS NOT DISTINCT FROM` is standard and unsupported by SQLite before
[3.39.0](https://www.sqlite.org/releaselog/3_39_0.html). The historical host
in this incident ran 3.37.2, so every insert raised.

Guard: pin the minimum SQLite version you support and test against *it*,
not against whatever the developer's machine has.

## Quiescence: sample it, do not snapshot it

Before copying a live store, "is anything writing to this?" is not a
question a point-in-time check can answer. A writer that opens, writes
and closes is invisible to `lsof` between its writes — a snapshot
reports quiet over exactly the writer that will lose your rows.

Poll over an interval and return the interval:
`"no writer observed over 60s at 0.2s sampling"`, never `"quiescent"`.
Those numbers illustrate a report, not defaults. The actual observer is
`scitex_db._migrate._observe.observe_source(source_path, *, seconds, interval)`;
it is not re-exported as `scitex_db._migrate.observe_source`. Both timing
arguments are required. It returns `QuiescenceEvidence`; seeing a writer
does not itself raise or stop that writer.

`scitex_db._migrate.migrate` does not start observation. The caller supplies
`quiescence_evidence` explicitly: positive evidence refuses completion in
`_copy.finalize`, while `None` or unobservable evidence can still reach a
marker under the current API. The marker records that absence of evidence;
it does not prove quiet. A separate `Quiescence` declaration names the
caller's mechanism for stopping writers. A bounded negative, an unobservable
source or a completion marker is no replacement for actually stopping them.

Two things measured while building it, both worth stealing:

- `PRAGMA data_version` only changes on a connection **held** across the
  window. A fresh connection per reading re-reads its own baseline and
  returns the same number forever — a dead signal that looks alive.
- A dead signal sitting beside a live one is invisible. Record *which*
  signal fired, and check that your negative control can actually go red.

## What scitex-db gives you today, honestly

`SQLite3` and `PostgreSQL` are **not** interchangeable — see
[13_mixins.md](13_mixins.md) for the measured divergence. Do not plan a
port as "construct the other class".

The toolkit exports `preflight` and `migrate` for a one-way cutover, not
a dual-live-store abstraction. Source owners include `_introspect`, `_ddl`,
`_triggers`, `_run`, `_verify`, `_provenance` and `_observe`. Reuse these
primitives before adding another migration implementation, but qualify
each application's routing, DDL, locking, health and version requirements.

Behavioral evidence lives in `tests/scitex_db/_migrate/`: `test__observe.py`
uses real SQLite files and a background writer, and
`test__copy_quiescence_refusal.py` checks positive-writer refusal and the
marker evidence for no observation/unobservable cases. `test__run.py`
uses SQLite on both sides; `test__run_acceptance.py` checks actual SQLite
rejection of translated PostgreSQL trigger SQL. These do not prove that
a PostgreSQL server accepts every translated trigger or that a live port
is safe. PostgreSQL execution, cooperative locking and application cutover
need their own native tests. The historical Cards incident counts above
are incident context, not a fresh audit of its current deployment.

## See also

- [13_mixins.md](13_mixins.md) — where the two backends diverge
- `scitex-cards` `docs/design/sqlite-to-postgres-migration-hazards.md` —
  the incident record with the measurements behind each item above
