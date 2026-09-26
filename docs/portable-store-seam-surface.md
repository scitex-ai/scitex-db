# The portable-store seam: receiving surface

Status: proposed by scitex-db, 2026-08-02. Open for scitex-cards to
implement against.

## Why this document exists before the code

scitex-cards has offered working implementations of five guards learned
during its 2026-08-01 SQLite → PostgreSQL migration. Accepting code
before agreeing where it lands is how a donated module ends up
refactored into something its author no longer recognises. This file
fixes the boundary first; the implementations then drop into named
slots.

## Non-goals, stated first

**This is not a query wrapper.** It does not wrap `connect`, `execute`,
`cursor`, or rows. Every package that would use it already has working
data access; a wrapper would add a dependency and remove nothing.

**It does not replace `SQLite3` / `PostgreSQL`.** Those two classes are
not interchangeable (see `13_mixins.md`) and this seam does not try to
make them so. It sits below them, and neither imports the other.

**It is not for the canonical store's connection path.** scitex-cards
keeps its own dependency-light adapter, for a documented reason and a
measured incident. Nothing here asks it to change that.

## The dependency boundary — the load-bearing constraint

```
scitex_db.store   →  stdlib only
                     (sqlite3, urllib.parse, dataclasses, pathlib, re)
scitex_db.store   →  psycopg / psycopg2 ONLY behind an extra, imported
                     lazily inside the function that needs it
```

No numpy. No pandas. No scitex-core. No click.

This is the entire reason the seam can be adopted. Measured 2026-08-02:
every package that considered `scitex_db` and declined recorded weight
as the reason —

    scitex-clew/_connect.py:6
      "scitex-db (which pulls numpy + pandas + scitex-core) ...
       Instead this module MIRRORS scitex-db's proven [tuning]"

A guard nobody can afford to import is a guard nobody has. If a change
to this module would add a dependency, the change is wrong, not the
constraint.

## Module layout

```
src/scitex_db/store/
    __init__.py        # the public names, and nothing else
    _url.py            # 1. read the config value; DSN vs path
    _ddl.py            # 2. statement-by-statement DDL with a count
    _tx.py             # 3. per-dialect write-transaction begin
    _backend.py        # 4. which engine is live
    _portable_sql.py   # 5. spellings that survive both dialects
```

`scitex_db.store` must be importable without importing `scitex_db`'s
existing surface. Package `__init__` stays lazy (PEP 562) as it is
today.

## Answer shapes

Per the constitution: one dataclass per question, every signal its own
named field, every signal three-valued, a validator on the dataclass so
a malformed answer fails where it is built.

### 1. `resolve_store(...)` / `parse_store_url(value) -> StoreLocation`

```python
@dataclass(frozen=True)
class StoreLocation:
    dialect: str                 # "sqlite" | "postgresql"
    path: Path | None            # sqlite only; None for postgresql
    dsn: str | None              # postgresql only; None for sqlite
```

Validator: exactly one of `path` / `dsn` is set, and it matches
`dialect`. A value carrying a URL scheme must NEVER reach `Path()` —
`Path("postgresql://host/db")` silently becomes the relative path
`postgresql:/host/db`, which SQLite will then create, serve empty, and
report healthy. Raise on an unrecognised scheme; do not fall back to
"probably a path".

**Where the refusal lives.** Asked by scitex-cards, 2026-08-02, and a
fair question against the first draft: it said "before any `Path()`
coercion" without saying whose job that is. It is not the caller's.

1. **`parse_store_url` is total.** Every input either becomes a
   validated `StoreLocation` or raises. It never returns `None`, never
   "probably a path", never a bare string. There is no branch where the
   caller is handed something and asked to decide — and that branch is
   where both silent successes lived.

2. **A postgres location carries `path=None`,** validator-enforced. A
   caller who ignores `dialect` and reaches for `.path` gets
   `Path(None)` → `TypeError`: loud, at the call site, on the first run.
   Not an empty file at a mangled relative path serving zero rows.

3. **The seam owns READING the config value, not only parsing it** —
   `resolve_store(env=..., default=...) -> StoreLocation`. Both
   incidents happened *before* any parse: the raw string went from the
   environment straight into `Path()`. A parser that only refuses what
   is handed to it cannot refuse what was never handed to it. The intent
   is that no code in a consuming package ever holds the raw value.

**What no type can do** is reach a caller who never calls it.
`Path(os.environ["SCITEX_CARDS_DB"])`, written by someone who has not
heard of this module, is invisible to all three points above. That is a
linter rule, not a library feature: `STX-DB002`, flagging `Path(<env
lookup>)` for variable names matching `*_DB|*_URL|*_DSN|*_STORE*`, in
the existing plugin beside `STX-DB001` (entry point
`scitex_dev.linter.plugins`).

State its limits as plainly as DB001 states its own: plain AST, no
seeing through wrappers, fires on the literal shape. It will miss an
indirection and will occasionally fire on a genuine path variable. Both
are acceptable — a false positive costs one line of thought; the false
negative cost two incidents in a single day.

The type refuses; the rule catches the bypass. Neither alone closes the
class, and building to the type alone should not feel as though it did.

### 2. `execute_ddl(conn, statements) -> DDLResult`

```python
@dataclass(frozen=True)
class DDLResult:
    executed: int                # statements that actually ran
    submitted: int               # statements handed in
    skipped: tuple[str, ...]     # must be empty on success
```

The count is the product. "The guards are installed" and "the install
call did not raise" are different claims, and only the count
distinguishes them. A construct that cannot be ported raises, naming
it — never silently skipped. Validator: `executed <= submitted`, and
`skipped` non-empty implies `executed < submitted`.

### 3. `begin_write(conn, *, lock_key) -> contextmanager`

SQLite: `BEGIN IMMEDIATE`. PostgreSQL: `BEGIN` +
`pg_advisory_xact_lock(lock_key)`.

`lock_key` is keyword-only with no default: PostgreSQL needs one and
SQLite does not, so a default would let a caller who never thought about
it get a lock scope chosen by the library.

`SERIALIZABLE` is not an accepted implementation. It aborts the loser
where these block it — same code, different concurrency contract,
visible only under load.

**Its test must observe the lock from a third connection.** "Run two
concurrent writers and check the result" is too weak: a `begin_write`
that does nothing at all passes it whenever the two writers happen not
to collide, which under light load is most of the time. So the test
asserts the lock is *visible while held* and *gone after commit* —

```sql
SELECT pid, objid, granted FROM pg_locks WHERE locktype = 'advisory';
```

— one row while the context manager is open, zero rows after it exits.
For SQLite, the equivalent is a second connection whose write attempt
fails with `SQLITE_BUSY` while the first holds `BEGIN IMMEDIATE`.

This is not belt-and-braces. Without it, guard 3 is a gate that cannot
fail, inside the module written to prevent gates that cannot fail.

The requirement came from a real reading: scitex-cards sampled
`pg_locks` 216 times at 200ms across four writes and saw zero granted
rows. Zero waiters answered the contention question; zero *granted* rows
is the shape that would also appear if the lock were never taken at all.
Their data cannot distinguish the two — and did not need to, because
either way the hold is bounded: missing four holds at 200ms sampling
puts it under about 100ms at 95% confidence, which cannot explain a
13-25s lag. But a library whose lock might silently not be taken is
exactly what this test exists to rule out.

### 4. `describe_backend(conn_or_location) -> BackendReport`

```python
@dataclass(frozen=True)
class BackendReport:
    dialect: str | None          # None == unknown, never guessed
    server_version: str | None
    config_source: str | None    # which env var / tier selected it
```

Three-valued on purpose. A doctor that asserts the literal string
"SQLite" reports the wrong engine on every PostgreSQL deployment while
passing — the failure this field exists to prevent.

### 5. `portable_sql` — spellings, not a query builder

**Corrected 2026-08-03, and the correction is load-bearing.** This
section originally said "constants and small helpers ... ships with the
minimum SQLite version it supports as a module constant". That framing
assumes one correct literal plus a version gate. It is wrong. Measured
by scitex-cards on their deployment
(`src/scitex_cards/_sql_null_safe.py`):

```
backend                col IS ?      col IS NOT DISTINCT FROM ?
SQLite 3.37.2          WORKS         SYNTAX ERROR (needs >= 3.39)
PostgreSQL             SYNTAX ERROR  WORKS
```

**There is no single spelling that works on both.** `IS` does not parse
on PostgreSQL either, so no constant — gated or not — expresses this.
The spelling must be chosen where the dialect is known, which makes
`describe_backend` (§4) a *dependency* of this module rather than a
sibling.

The version constant still ships, and a test still asserts against it
rather than against the developer's SQLite — the spread between host
(3.37.2) and container (3.45.1) is exactly what hid the outage — but it
selects a spelling, it does not certify one.

That mismatch cost a **36-hour silent delivery outage**: every enqueue
raised and a fail-soft `except` swallowed it. Work performed, evidence
lost.

Paramstyle is the other half, and the naive rewrite is worse than none:
a `?` **inside a string literal** is not a placeholder, so
`sql.replace("?", "%s")` silently corrupts card and message bodies
containing question marks; and a literal `%` must be doubled or a
`LIKE '%foo%'` pattern becomes a format specifier and raises. One
correctness hazard and one crash hazard from the same one-liner.

## What scitex-db owes in return

- Review of the PR against this surface, not against taste.
- A test per guard that can be shown to FAIL — for each one, the red
  output goes in the PR body. A guard whose test has never been red is
  not yet known to be a guard.
- Where a guard's effect is observable from outside the process (a lock,
  a file, an executed statement), the test observes the EFFECT, not the
  return value. A function that returns the right answer without doing
  the thing passes every test written against its return value.
- No renames after merge without an alias.

## Open question for the operator

Whether `scitex-cards` then adopts it for its canonical store is
explicitly NOT decided here, and this document takes no position. The
dependency-light decision has a documented reason and a measured
incident behind it.
