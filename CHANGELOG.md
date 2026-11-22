# Changelog

All notable changes to `scitex-db` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Documentation

- Qualify cutover quiescence and retirement guidance: equal row counts and a
  completion marker do not prove writers stopped; document bounded observation
  evidence, marker-stage refusal and per-path retirement verification.

- Update the portable-store proposal to current location/DDL/transaction/report
  contracts while retaining unmet lifecycle, native PostgreSQL and linter requirements.

- Consolidate CLI guidance and correct help depth, JSON flag scope, limited
  API/MCP inventories and skill installation destination/side-effect contracts.

- Replace invalid README database/repair examples with a disposable verified
  SQLite quick start,accurate backend composition and command-specific CLI scope.

- Correct installation dependencies,PostgreSQL driver and standalone namespace
  guidance; distinguish installed profile checks from umbrella/native adoption.

- Consolidate quick starts around a disposable verified SQLite example; correct
  context-manager, maintenance-keyword, backend and health-provider guidance.

- Correct migration observation imports, evidence/refusal boundaries, advisory
  locking and stored-schema-text guidance; state native PostgreSQL coverage limits.

- Correct the mixin guide's base-inheritance and backend method-name claims;
  replace stale coverage counts with source owners and actual test scope.

- Describe existing floating mixed-NULL reader results and the unresolved
  array-dictionary alignment gap, with native behavioral controls.

### Fixed

- Reject non-boolean DDL run flags before collecting statements or opening a
  cursor, preventing truthy strings such as `"False"` from running schema changes.

- Validate the required DDL version even when the observed store version is
  unknown, preventing invalid inputs from authorizing schema changes.

- Add the leaf-owned STX-DB002 warning for direct store-related environment
  lookups passed to Path, with explicit syntax and false-positive limits.

- Honor provided per-row compression flags with raw array dtype/shape fallback
  hints, retaining the existing no-flag and empty-frame paths.

- Fill NULL rows in floating array dictionaries with NaN arrays, matching the
  main reader while retaining existing non-floating handling.

- Honor explicit scalar `shape=()` fallback hints in binary and DataFrame array
  helpers by checking hint presence instead of truthiness.

- Return `None` for all-NULL payload columns in array dictionaries, matching
  the main reader's absence result while retaining populated neighboring arrays.

- Reject array-dictionary selections without dtype/shape metadata or usable hints
  instead of reusing a preceding column's arrays or raising an unbound-local error.

- Handle zero-row DataFrames in array helpers: the dictionary maps recognized
  columns to `None`, matching `load_arrays`, and the in-place decoder preserves
  the empty frame without a Pandas assignment error. Present zero-length
  NumPy arrays retain their shape and dtype.
- Infer default DataFrame array columns from dtype/shape companions rather
  than suffix filtering. Scalar/hash fields are excluded and actual payloads
  with metadata-like names remain discoverable; explicit columns and hint-based
  decoding retain their existing paths.
- Forward each row's compression flag in `get_array_dict` and normalize
  integer/text flags in `decode_array_columns`, matching the main array reader.
  Numeric DataFrames from `get_rows` can decode raw and compressed payloads
  from both wrapper-created and pre-existing native SQLite tables.
- Parse `binary_to_array` shape metadata with `ast.literal_eval`, matching the
  main array reader. Python expressions in shape strings are rejected instead
  of executed, including calls through the DataFrame decoding helpers.

## [0.2.1] — 2026-08-02

### Added

- `STX-DB001` — the `SQLite3(...)` construction rule, registered through the
  `scitex_dev.linter.plugins` entry point so scitex-linter discovers it. The
  rule states its own limits: plain AST detection, no seeing through wrapper
  functions, fires wherever `SQLite3(` literally appears.
- A gate pinning prose to the rule corpus: every `STX-DB###` named in `docs/`
  or the skill docs must be defined by the plugin, or listed as an open
  proposal with a written reason. A companion test fails if such an exemption
  outlives the rule landing, and the rule-id extractor is itself tested to fire
  and to not over-fire — a broken extractor would make both gates vacuous.

### Fixed

- `docs/portable-store-seam-surface.md`, published in 0.2.0, told another
  package to add `STX-DB002` "in the existing plugin beside `STX-DB001`" and to
  "state its limits as plainly as DB001 states its own" — while the plugin was
  on neither `main` nor `develop`. It had sat unmerged on a branch since
  2026-07-05, so the published surface pointed a reader at code this repository
  did not carry. Landing the rule makes the claim true; the new gate is what
  stops the next one.

### Note

The 0.2.0 gate (`tests/scitex_db/test__skills.py`) did not cover this: it scans
the skill docs for `db.<method>(` calls only, so `docs/` was unguarded. Two
gates now, over different prose and different claims.

## [0.2.0] — 2026-08-02

First release containing the SQLite→PostgreSQL migration toolkit. The work
landed on `develop` between 2026-07-25 and 2026-08-02 and had never reached
`main`; `v0.1.12` predates all of it.

### Added

- `scitex_db._migrate` — the migration toolkit: introspection, DDL translation,
  trigger handling, row copy, verification, refusal, provenance markers, and a
  destination model.
- `observe_source()` — quiescence by **sampling**, not snapshotting. Reports the
  window it watched (`"no writer observed over 60s at 0.2s sampling"`) rather
  than a bare verdict, because a writer that opens, writes and closes is
  invisible to a point-in-time check. `finalize()` refuses to mark a migration
  complete when a writer was observed on the source during the run.
- `16_sqlite-to-postgres` skill — porting guidance drawn from a real migration
  in which **nine of twelve defects produced no error at all**.
- `docs/portable-store-seam-surface.md` — the receiving surface for a proposed
  stdlib-only store seam (DSN-vs-path, DDL statement counts, per-dialect write
  locks, live-backend reporting, portable SQL spellings).
- `tests/scitex_db/test__skills.py` — a gate asserting every `db.<method>(` in
  the skill docs resolves to a method that is actually implemented.

### Fixed

- Skill documentation claimed an interchangeability the code does not have.
  `13_mixins.md` listed twelve method names existing on neither backend and
  stated "call those names on either class"; the quick-start had three lines
  that could not run. Measured: `SQLite3` leaves 23 of the 59 base methods
  unimplemented, and the two backends spell the same operations differently.
- `cla.yml` no longer uses `secrets: inherit`. Both of its triggers are
  unauthenticated, and the repository holds a credential the callee never
  references.

### Note

`SQLite3` and `PostgreSQL` are **not** interchangeable and this release does not
make them so. See `13_mixins.md` for the measured divergence.

## [0.1.11] — 2026-05-25

### Fixed

- Populated empty `_BaseMixins` / `_PostgreSQLMixins` test directories with real,
  no-mock test files (PS-207). `_BaseConnectionMixin` gets 6 single-assert AAA
  tests; `_BatchMixin` gets 12 single-assert AAA tests.
- Replaced broken `ecosystem-clone` audit template with single-package
  `audit-all` gate.
- Disabled Codecov PR comments.
- Made `_sphinx_html` commit-back CI step non-fatal.

## [0.1.10] — 2026-05-19 (unreleased — release workflow failed)

### Changed

- Resynced release pipeline from scitex-dev v0.11.20.
- Standardized CI workflow set to scitex-dev canonical.

## [0.1.9] — 2026-05-18

### Changed

- Test-quality cleanup: cleared PA-306 (no mocks) and PA-307 (TQ rules)
  violations. Deleted pure-theater mock tests; replaced with real-collaborator
  tests using `tmp_path` SQLite databases.

## [0.1.8]

- Initial CHANGELOG entry — see git log for prior history.
