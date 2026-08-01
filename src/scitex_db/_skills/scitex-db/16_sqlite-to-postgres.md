---
description: |
  [TOPIC] Porting a package from SQLite to PostgreSQL
  [DETAILS] The failures that produce NO error — silent wrong-store writes, DDL that runs zero statements, lock semantics that differ, engine reported wrong. Checklist before and during a backend move.
tags: [scitex-db-postgres, scitex-db-migration, scitex-db]
---

# SQLite → PostgreSQL: the failures that do not raise

Written from a real migration: `scitex-cards` moved its canonical store
from SQLite to PostgreSQL over 2026-07-31 → 2026-08-01. Twelve distinct
defects were found. **Nine produced no error at all** — they returned an
id, created a file, printed a green check, or reported a matching
version string.

That is the durable lesson, and it is not any single incompatibility.
The incompatibilities are finite and listed below. The problem is that a
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

SQLite takes a write lock with `BEGIN IMMEDIATE`. PostgreSQL's
equivalent is `BEGIN` plus `pg_advisory_xact_lock`.

`SERIALIZABLE` is **not** a substitute: it aborts the loser instead of
blocking it. A naive port compiles, passes tests, and changes the
concurrency contract — visible only under load, as retries that used to
be waits.

Guard: one named "begin a write transaction" primitive per dialect, and
a test that runs two concurrent writers.

### 4. Ask the connection which engine it is

A health check that asserts the literal string `"SQLite"` reports the
wrong engine on every PostgreSQL deployment, forever, while passing.

Guard: report the live backend and the config tier that selected it.
Three-valued: SQLite / PostgreSQL / **unknown** — never default to a
guess.

### 5. Standard SQL is not portable SQL

`IS NOT DISTINCT FROM` is standard and unsupported by SQLite before
3.39. The host in question ran 3.37.2, so every insert raised.

Guard: pin the minimum SQLite version you support and test against *it*,
not against whatever the developer's machine has.

## Quiescence: sample it, do not snapshot it

Before copying a live store, "is anything writing to this?" is not a
question a point-in-time check can answer. A writer that opens, writes
and closes is invisible to `lsof` between its writes — a snapshot
reports quiet over exactly the writer that will lose your rows.

Poll over an interval and return the interval:
`"no writer observed over 60s at 0.2s sampling"`, never `"quiescent"`.
`scitex_db._migrate.observe_source` does this and refuses to mark a
migration complete if a writer was seen.

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

The migration toolkit (`scitex_db._migrate`) does cover the copy itself:
introspection, DDL translation, trigger handling, row copy, verification,
provenance markers, and the quiescence observer above.

The five guards above are **not** yet a shared module. Until they are,
each porting package implements them itself — which is precisely the
duplication this file exists to shorten. If you are about to write them,
say so on the scitex-db board first.

## See also

- [13_mixins.md](13_mixins.md) — where the two backends diverge
- `scitex-cards` `docs/design/sqlite-to-postgres-migration-hazards.md` —
  the incident record with the measurements behind each item above
