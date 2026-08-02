# Changelog

All notable changes to `scitex-db` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
