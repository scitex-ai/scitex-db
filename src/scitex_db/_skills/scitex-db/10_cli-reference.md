---
description: |
  [TOPIC] CLI reference
  [DETAILS] Actual inspection, consent/provider limits, discovery and skill commands.
tags: [scitex-db-cli-reference, scitex-db]
---

# CLI Reference

The console entry is `scitex_db.__main__:main`, declared in `pyproject.toml`.
Use `scitex-db --help` and each nested command's own `--help` for its options.

## Root options and command boundaries

| Root option | Current behavior |
|---|---|
| `-V`, `--version` | Print the installed distribution version and exit |
| `-h`, `--help` | Print root help and exit |
| `--help-recursive` | Print root and immediate subcommand/group help; nested command help is not traversed |
| `--json` | Store a root flag consumed by `inspect-db`; other callbacks below require their own `--json` |

`--quiet`, `--dry-run` and `--yes` are command-specific. Root `--json` alone
still leaves `list-python-apis`, `mcp list-tools` and `skills list/get` in human
output mode. Accepted root flags do not establish JSON serialization for health.
The source owners are `main`, `_print_help_recursive` and the individual
callbacks in `scitex_db.__main__`; skill callbacks live in `scitex_db._skills`.

For nested help, use `scitex-db mcp list-tools --help` or
`scitex-db skills get --help`.

## Configuration limit

Configuration files are not implemented. Pass database paths and options
explicitly. `./config.yaml`, `$SCITEX_DB_CONFIG`, `~/.scitex/db/config.yaml`
and automatic `.env` loading do not set CLI defaults. Valid and malformed
files are ignored; a successful command does not validate them. Portable
`.scitex/db` configuration remains intended, with no supported precedence.
Python `store.resolve_store(env=...)` separately reads a caller-named variable.

Owners: `scitex_db.__main__.main` and `inspect_db`. Actual subprocess controls
in `tests/scitex_db/test___main__.py` check configuration locations/content,
explicit table selection, unchanged fixture bytes and help disclosure.

## Commands

| Command | Current scope |
|---|---|
| `inspect-db` | Read-only SQLite path inspection; human summary or JSON |
| `check-health` | Provider preflight and consent guard; provider-present scans/repairs remain separately unqualified |
| `list-python-apis` | Fixed advertised list of three maintenance helpers, not exhaustive API introspection |
| `mcp list-tools` | Empty tool inventory; no MCP server start/serve command |
| `skills list/get/install` | Bundled guidance discovery, retrieval and local installation |

### scitex-db inspect-db

```
scitex-db inspect-db <db_path> [--tables TBL]... [--quiet] [--json]
```

* `db_path` — SQLite3 file
* `--tables` — only inspect the named tables (default: all)
* `--quiet` — minimal output
* `--json` — emit the inspection result as standard JSON; the global flag
  `scitex-db --json inspect-db ...` has the same effect

Wraps `scitex_db.inspect()`. JSON is a list of tables with `table_name`,
`columns`, `row_count`, `is_approximate` and `sample_data`. Sample values retain
SQLite integers, finite reals, strings and nulls. The default is up to five
sample rows per table. BLOB samples are strings such as `<BLOB 3 bytes>`, not
raw bytes or decoded scientific arrays. Counts below 100,000 are exact JSON
integers (`is_approximate=false`). At the 100,000-row probe cap, `row_count`
is the inclusive lower-bound string `">=100,000"` (`is_approximate=true`),
including when the table has exactly 100,000 rows. Native boundary/CLI controls
live in `tests/scitex_db/test__inspect_count_boundary.py`. Repeated `--tables` flags select
and order the tables. `--quiet` suppresses human output, not JSON output.
Non-finite numbers such as infinity cannot be encoded as standard JSON:
the command exits nonzero, writes the error to stderr and leaves stdout empty.

```bash
scitex-db inspect-db trials.db --tables trials --tables participants --json
scitex-db --json inspect-db trials.db
```

The owning callback is `scitex_db.__main__.inspect_db`. Actual subprocess
controls in `tests/scitex_db/test___main__.py` check JSON flag positions,
quiet/human behavior, schema/types/Unicode/null/BLOB samples, table selection,
the five-row sample limit, non-finite refusal and unchanged database bytes.

Paths must already exist and name files. A missing path is refused without
creating a database. Human summaries use the package logger (stderr in the
reviewed default environment); JSON uses stdout. Read-only opening of the main
SQLite file does not establish a universal no-side-effect sandbox for WAL or
other sidecars. The owning read-only controls are
`tests/scitex_db/test__inspect_readonly.py`; count-boundary and CLI controls
above cover their own behaviors.

### scitex-db check-health

```text
scitex-db check-health <db_path> [<db_path> ...] [--fix] [--yes] [--quiet] [--dry-run] [--json]
```

Paths must already exist. One path dispatches to the Python `check_health`;
multiple paths dispatch to `batch_health_check`. `--fix` requests repair and
requires `--yes`/`-y`, except that `--fix --dry-run` clears the repair flag first.
That combination prints a generic banner and continues the non-repair path;
it does not produce an issue-by-issue repair plan. `--dry-run` alone also
continues the non-repair health path. With a provider present, neither form is
a promise to avoid database access. `--quiet` reduces human output. The accepted
`--json` flag does not serialize health results.

When the `scitex` loadability provider cannot be found, the CLI exits with
code 1, empty stdout and a named missing-provider error on stderr before any
SQLite scan or repair. Core installs do not supply this provider. The presence
check does not import or validate its implementation. `--fix` without `--yes`
still refuses with code 2 before this preflight; `--fix --dry-run` never
repairs. Neither health JSON nor provider functionality is implemented by
this guard.

Owner: `scitex_db.__main__.check_health`. Actual subprocess controls in
`tests/scitex_db/test___main__.py` cover ordinary/quiet/JSON/global-JSON,
confirmed-fix/dry-run, multiple paths, consent priority and a real exclusive
SQLite lock. They qualify missing-provider refusal and file/row preservation;
provider-present health/loadability/repair behavior remains unverified.

### scitex-db list-python-apis

```bash
scitex-db list-python-apis --json
```

The callback returns `{"apis": [...]}` containing only
`scitex_db._inspect.inspect`, `scitex_db._check_health.check_health` and
`scitex_db._check_health.batch_health_check`. It does not enumerate classes,
array helpers or every public export. This describes the current limited
inventory; broader predictable API discovery remains an unresolved contract.
Use the command-level flag shown above for JSON.

### scitex-db mcp list-tools

```bash
scitex-db mcp list-tools --json
```

The result is `{"tools": []}`. Human mode prints `(no MCP tools registered)`.
The group provides this inventory command only; it does not start a server or
expose database operations as live MCP tools. No server availability is claimed.

### scitex-db skills

```bash
scitex-db skills list --json
scitex-db skills get 10_cli-reference --json
```

`list` returns name/path objects for bundled Markdown files. `get` accepts a
file stem or that stem plus `.md`, and returns name/path/content in JSON mode.
Both traverse the leaf skill directory recursively and exclude `SKILL.md`.
A missing name exits nonzero. The root skill is retrieved through the owning
Dev provider; leaf `get SKILL` does not retrieve it. Installed names and bytes
must be checked independently of a static source reference.

Installation defaults to a symlink at `~/.scitex/dev/skills/scitex-db`.
`--dest` names its parent directory: the installer appends `scitex-db`.
`--no-link` copies the skill directory instead, including `SKILL.md`.
An existing target file/link is removed or an existing target directory is
replaced. The installer is non-interactive; `--yes` is accepted but unused.
Choose a dedicated destination when trying it.

The following is a preview with a placeholder destination; it makes no copy or
link. Substitute an owned directory before an actual installation.

```bash
scitex-db skills install --dest /owned/skill-parent --no-link --dry-run
```

`--claude-symlink` additionally targets `~/.claude/skills/scitex` at the skill
parent directory. Existing non-symlink entries there are left in place with a
warning; this does not prove that an agent discovers or uses the installed
skills. Default-home and Claude integration are not qualified by the owned
custom-destination checks below.

## Behavioral evidence and remaining scope

Existing leaf subprocess controls in `tests/scitex_db/test___main__.py` cover
configuration disclosure, inspection values and flags, and missing-provider
health/consent behavior. Inspection and count-boundary tests are named above.
`tests/scitex_db/test__skills.py` checks selected Python method names in skill
examples statically; it does not execute every CLI example or install skills.

The reviewed owned CLI fixtures separately check help depth, root versus
command JSON, the three advertised helper names, empty MCP inventory, exact
leaf/owning-provider skill bytes, and custom-destination dry-run/symlink/copy
results. Source and installed-command evidence do not qualify public wheels,
minimum Python/platforms, native PostgreSQL, provider-present health/repair,
agent adoption, generated/served docs or hosted availability. Static Markdown
checks and successful builds do not establish those results.
