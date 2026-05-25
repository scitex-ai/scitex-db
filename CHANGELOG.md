# Changelog

All notable changes to `scitex-db` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
