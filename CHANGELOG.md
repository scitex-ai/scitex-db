# Changelog

All notable changes to `scitex-db` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed

**BREAKING — the package now carries one backend, PostgreSQL.** Everything
below was deleted rather than deprecated, per the operator's standing ruling
that the ecosystem carries exactly one storage engine.

- The file-backed backend package, its class and its thirteen mixins, together
  with the path-level duplicate-removal helper built on it.
- Six top-level exports: the removed backend class, both duplicate-removal
  helpers, `inspect`, `check_health` and `batch_health_check`.
  `scitex_db.__all__` is now `PostgreSQL`, `register_post_save_hook`,
  `register_post_load_hook`, `__version__`.
- CLI verbs `scitex-db inspect-db` and `scitex-db check-health`. Both took a
  database FILE PATH and had no connection-string form, so neither survives the
  move to a server-based store. `scitex-db list-python-apis` now reports the
  three symbols above.
- `scitex_db._migrate` — the one-way cutover toolkit added in 0.2.0. It had no
  CLI verb and no caller in this repository or the wider ecosystem.
- `scitex_db.store` — the portable-store seam proposed in 0.2.0. Its premise
  was surviving a dialect change; with one dialect there is nothing to be
  portable between, and it was never implemented against.
- `scitex_db._linter_plugin` and its `scitex_dev.linter.plugins` entry point.
  Rule `STX-DB001` no longer exists — a linter config naming it should drop it.
- The `git` optional-dependency extra (`GitPython`), whose only consumer was a
  mixin of the removed backend. It is also gone from `all`.
- `docs/portable-store-seam-surface.md`, the cutover runbook beside it, and
  the `16_*`, `10_*`, `11_*`, `12_*` skill leaves.

### Changed

- The observer registry (`register_post_save_hook` /
  `register_post_load_hook`) is retained and still exported, but the removed
  backend was its ONLY firing site. Until `_postgresql._QueryMixin` fires them,
  a registered hook will not be called.

## [0.2.1] — 2026-08-02

### Added

- `STX-DB001` — a construction rule for the file-backed backend, registered
  through the `scitex_dev.linter.plugins` entry point so scitex-linter
  discovers it. The rule states its own limits: plain AST detection, no seeing
  through wrapper functions, fires wherever the constructor literally appears.
  (Removed in Unreleased, along with the backend it policed.)
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

First release containing the store-migration toolkit. The work landed on
`develop` between 2026-07-25 and 2026-08-02 and had never reached `main`;
`v0.1.12` predates all of it. (The toolkit was removed in Unreleased.)

### Added

- `scitex_db._migrate` — the migration toolkit: introspection, DDL translation,
  trigger handling, row copy, verification, refusal, provenance markers, and a
  destination model.
- `observe_source()` — quiescence by **sampling**, not snapshotting. Reports the
  window it watched (`"no writer observed over 60s at 0.2s sampling"`) rather
  than a bare verdict, because a writer that opens, writes and closes is
  invisible to a point-in-time check. `finalize()` refuses to mark a migration
  complete when a writer was observed on the source during the run.
- A porting-guidance skill leaf drawn from a real migration in which **nine of
  twelve defects produced no error at all**.
- `docs/portable-store-seam-surface.md` — the receiving surface for a proposed
  stdlib-only store seam (DSN-vs-path, DDL statement counts, per-dialect write
  locks, live-backend reporting, portable SQL spellings).
- `tests/scitex_db/test__skills.py` — a gate asserting every `db.<method>(` in
  the skill docs resolves to a method that is actually implemented.

### Fixed

- Skill documentation claimed an interchangeability the code did not have.
  `13_mixins.md` listed twelve method names existing on neither backend and
  stated "call those names on either class"; the quick-start had three lines
  that could not run. Measured: one backend left 23 of the 59 base methods
  unimplemented, and the two spelled the same operations differently.
- `cla.yml` no longer uses `secrets: inherit`. Both of its triggers are
  unauthenticated, and the repository holds a credential the callee never
  references.

### Note

The two backends were **not** interchangeable and this release did not make
them so. See `13_mixins.md` for the measured divergence.

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
  tests using `tmp_path` databases.

## [0.1.8]

- Initial CHANGELOG entry — see git log for prior history.
