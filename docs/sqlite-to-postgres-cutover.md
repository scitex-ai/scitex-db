# SQLite → PostgreSQL cutover runbook

For moving a scitex-cards store from SQLite to PostgreSQL. Written from two
real runs (2026-07-30 and 2026-07-31), so every warning below is something that
actually happened rather than something imagined.

**A cutover is not a copy.** A verified copy proves the destination matches the
source at a moment. A cutover additionally makes the destination *the* store and
the source unusable. The steps that do the second part are the ones people skip,
and they are the ones that cause silent loss.

---

## The order, and why each adjacency matters

```
1  quiesce, and MEASURE it
2  create a FRESH destination database
3  copy, with the provenance record
4  verify independently, by someone who did not run step 3
5  RETIRE the source store
6  point readers at the destination
7  restart
8  CARRY THE DELTA, and verify that too
```

**8 is not optional and it is not cleanup.** Steps 1–7 move the store as it stood
at the snapshot; every write made after it is still only in the source. Skipping
8 is the difference between a cutover and a partial data loss that reads as a
success — see §7.

**8 comes after 7, not before.** The delta cannot converge while any writer still
holds the old path, and the parties coordinating the cutover are themselves
writers: each message they send re-opens it. Only a fleet that has already moved
produces a delta that stops growing.

**5 before 6.** Retiring first means a straggler still holding the old path
fails loudly instead of quietly serving yesterday's board. Reverse them and the
window between is one where a half-restarted fleet writes to two stores.

**6 takes effect at container LAUNCH**, not at config write. So the interval
between 6 and 7 completing is exactly the two-live-stores condition. Keep it
short and expect it, rather than assuming the switch is instantaneous.

**4 is done by the other party.** Two readers is the point. A verification run
by whoever ran the copy shares the copy's blind spots.

**Connectivity is not usability.** A `SELECT count(*)` that succeeds proves a
socket, not a product. On 2026-07-31 that probe reported the destination
reachable while the *client* could not open it at all: the migration had left
schema objects owned by two different roles, and the client's own `init_schema`
re-asserts its guards on every open, which is a DDL call on someone else's
object. Neither failure could be reached by any number of plain SELECTs, because
both live on the client's open path.

Verify by opening the store **the way the application opens it** — its own
client, its own code path — not with a driver call of your own. And check what
the DSN resolves to *in the environment that will use it*: a hostless
`postgresql:///name` resolves to a Unix socket, which works on the host and
fails in every container. A measurement only supports a claim about the
environment it was taken in.

---

## 1. Quiescence: measure it, never accept the declaration

A declaration and a fact are different things. Daemons write independently of
whether agents are stopped.

Take a full per-table row count **before and after** the copy and require zero
drift. On 2026-07-30 that was 17,353 = 17,353 across the copy, which is what
made the run trustworthy. It costs one query per table.

Two traps found the hard way:

- **Agents talking about the cutover write to the store.** Every DM is a row.
  Both parties broke their own "I will stop writing" promise on 2026-07-31,
  minutes apart. Design the handshake so it does not depend on anyone behaving:
  the number that matters is the one the copy takes from its own snapshot.
- **Copy from a snapshot, not from the live file.** The source is read twice —
  once to copy, once to verify. If it can change between those reads, a mismatch
  is unattributable: nobody can tell a copy bug from ordinary drift. A snapshot
  makes the two reads see the same database by construction.

---

## 2. The destination must be fresh

`migrate()` **refuses** a destination that already carries a completion marker,
because copying into a finished store would insert every row a second time. This
is deliberate and there is no bypass.

So creating the destination is a *step*, not a precondition someone forgot.

Prefer creating a **new** database and renaming after verification, rather than
dropping the old one first. The stale copy is then an intact rollback for the
whole operation, at the cost of one rename.

Two access gotchas, both hit on 2026-07-31:

- A **5-field `.pgpass`** (`host:port:db:user:password`) matches only the named
  database. Connecting to `postgres` to issue `CREATE DATABASE` will fail with
  `fe_sendauth: no password supplied` — correct behaviour, surprising timing.
- The store role may lack **CREATEDB**. `CREATE ROLE x LOGIN PASSWORD ...` does
  not grant it. Creating the database needs a superuser path.

Neither changed anything when they failed, because both happen before the copy.
That is the intended shape: the operations that can fail cheaply happen first.

---

## 3. The copy and its provenance record

The completion marker is written **last**, and only if verification passed. An
absent marker means the destination is unusable — never "probably fine".

The marker carries, by construction rather than by anyone writing a report:

- the source identity and the completion timestamp
- **`store_identity`** — the store's own UUID, so a reader can ask *which* store
  this is, not merely whether it is complete
- **`quiescence`** — the mechanism and *who stated it*, because it is the one
  claim the migration cannot verify for itself
- per-table row counts at copy time
- excluded tables **with reasons**
- **the transformation manifest**, with original bytes as hex

Two questions, deliberately separate:

```
destination_is_usable(fetch)       was this migration completed and verified
destination_is_whole_store(fetch)  is this everything
```

Folding the second into the first is how a green report came to mean two
different things to two readers. **A cutover must consult both.**

---

## 4. Schema drift between copies

**The source's schema can change between one copy and the next.** On
2026-07-31 the re-copy refused because a trigger had appeared since the previous
run — a monotonic version floor shipped in the interim.

This is the preflight working. It refuses rather than silently dropping a guard
the store depends on, because a copy that arrives without its triggers accepts
the `DELETE` the source refuses, and a row-for-row verification cannot see that.

**Budget for it.** Between any two copies, re-check that every trigger and index
still translates. A cutover scheduled on yesterday's preflight is scheduled on
stale evidence.

**"Translates" is weaker than it reads, and this line used to hide that.** The
preflight calls an object *carried* when the translator produces output. Nobody
asked the destination whether that output is valid for it. On 2026-07-31 a
trigger with a subquery in its `WHEN` clause translated cleanly and PostgreSQL
refused it outright — `cannot use subquery in trigger WHEN condition` — and the
refusal arrived after **21,792 rows had been copied**. The destination had to be
dropped and rebuilt.

`migrate()` now executes every carried object against the destination inside a
savepoint and rolls it back, after the tables exist and before any row is
copied. If you are carrying objects with an older build, do that by hand. The
check is free; discovering it from `apply_schema_objects` is not.

When something cannot be carried, there are exactly two honest outcomes:

- its owner ports it by hand, and someone attacks the result, or
- it is dropped **deliberately**, with a stated reason, recorded as an exclusion

Never translate approximately. A guard that looks present and does not fire is
worse than one that is absent.

---

## 5. Prove enforcement, do not look for triggers

Before retiring the source, prove the retirement guard actually *fires* on it.

`sqlite_master` tells you a trigger row exists. It does not tell you the trigger
works. Both parties shipped a check that could not fail:

- an enforcement test that deleted a **nonexistent** id — a `BEFORE DELETE`
  trigger fires per row, so deleting zero rows succeeded and the test reported
  "not enforced" against a store where the guard demonstrably refuses
- a probe for `retired -> current` on a store that had **never been retired** —
  zero rows matched, nothing fired, and it read as "not enforced"

Use `EnforcementProbe`. It requires a fragment of the guard's **own** refusal
message, because "did it raise?" passes vacuously against a read-only
connection, a typo'd table, or a locked database — every one of which raises.

**Manufacture the precondition inside the transaction**, attempt the forbidden
action, expect the refusal, roll back. And note the consequence: an enforcement
attempt is a *write*, so it can only run inside the quiet window. The honest
check is the one that forces you to be quiesced to perform it.

**And enforcement is per code path, not per store.** The retirement marker is
consulted where the client takes its canonical read. On 2026-07-31 card writes
were refused by a retired store while DM writes went straight through, because
DM writing is a separate path that never consults the status. So "retire first
so stragglers fail loudly" is true for the paths that check and silently false
for the ones that do not. Before you rely on retirement as a fence, find out
which of your write paths consult it — and prefer consulting the status where
the connection is opened, so a new write path cannot silently inherit the gap.

**Un-retiring is not the mirror image of retiring.** Measured 2026-07-31, when
the cutover was reversed. The instinct is to undo what retirement did: drop the
guard triggers, delete `retired_at` / `retired_by` / `retired_in_favour_of`. The
store still refused — because those keys are *metadata*, the actual flag is
`schema_meta.store_status`, and the triggers are the **guard whose presence
proves currency**. Removing them turned "retired" into "cannot prove it is
current", which is refused just the same.

Correct order: drop the triggers, set `store_status=current`, then let
`init_schema` re-assert the guards on the next open.

---

## 6. The successor is a NEW store, not the same store at a new address

Mint a **fresh** `store_uuid` for the destination and record the predecessor's
in the completion marker.

`migrate()` takes `store_identity` as a required keyword with no default,
precisely so a caller must decide. On 2026-07-31 the caller decided badly and
passed the source's uuid straight through, because it was in front of them. The
result:

```
retired SQLite    store_uuid            = 0bb1395b-…
                  retired_in_favour_of  = 0bb1395b-…      <- itself
live PostgreSQL   store_uuid            = 0bb1395b-…      <- twin
```

The retirement pointed at itself. Nothing resolved by uuid at the time, so there
was no live harm — but `expected_uuid` exists to answer "am I on the right
store?", and against a twin it **passes on both**, including the retired one. A
gate that cannot fail.

Keeping the uuid is defensible *if* retirement points by DSN or location
instead. What must never ship is the combination we shipped: the same uuid and
a uuid-shaped pointer.

A second defect was hiding this one. The identity reader was path-only, so
`Path("postgresql://…").exists()` was False and it returned `None` **without
raising** — a store with an identity reported as having none, indistinguishable
from a store that genuinely has none, from the exact command an operator runs to
check. Two independent defects stacked so the guard was doubly incapable of
firing. Read identity through the same seam that opens the store.

---

## 7. Retirement must carry the post-snapshot delta

**A verified copy plus a retirement still loses every write made after the
snapshot.** Copy verification cannot see it — the copy was correct at snapshot
time — and neither can the independent verifier, because it compares the same
two things. It surfaces when a straggler hits the retirement refusal, which is
far too late to be a plan.

Measured on 2026-07-31: 21 missing rows and 2 changed rows survived a copy both
parties had verified as clean.

Two traps inside the delta:

- **A count check is blind to the changed rows.** Two cards existed in both
  stores with the right ids, holding reverted `status`. Row counts matched.
  Compare by id **and content**, never by counts.
- **The retirement rows are IN the delta and must NOT be carried.**
  `store_status=retired`, `retired_at`, `retired_in_favour_of`, `retired_by` are
  present in the source and absent in the destination, so a backfill rule of
  "insert every row present in source and absent in destination" — which sounds
  exactly right — **retires the successor**, one-way, using the guards you just
  installed and proved working.

Never define the delta by a timestamp cutoff. A cutoff sweeps those four rows in
without anyone deciding to; the filter ends up making the decision.

Confirm `extra=0` on every table first. That is what makes an add-and-update-only
carry incapable of losing anything, and its absence is why this board was
destroyed three times before.

**The carry cannot converge while a writer still holds the old path** — every
message the parties send each other re-opens it. So the carry runs *after* the
fleet has moved, as the last step, not before.

---

## 8. Rollback

> **A naive `\x00` → NUL reverse pass CORRUPTS data.**
>
> At least one message body already contained the escape notation as ordinary
> prose. Un-escaping it produces **three** NUL bytes where the original had one.
> The transformation is deliberately **not** treated as invertible.
>
> Reversibility comes from the **manifest**, which records the original bytes as
> hex — and from `record_json`, which for scitex-cards holds the byte-identical
> original alongside the transformed body.

This is stated here, at the top of the rollback section, rather than only in the
marker's transformation manifest. Facts that live only where nobody looks until
it matters are stored, not recorded — and rollback is precisely the moment
someone reaches for a reverse transform.

Other rollback notes:

- If step 5 has run, the source is retired **one-way** and will refuse readers.
  Rolling back past that point is not a config change.
- Before step 5, rollback is: point readers at the source, drop the destination.
  Cheap. This is why 5 is late in the order.

---

## What "two live stores" looks like when it happens

For roughly twelve hours on 2026-07-30–31, card creations were written into both
SQLite and PostgreSQL. It was benign **only** because PostgreSQL turned out to
be a strict subset — zero rows existed there that were absent from SQLite.

That is luck, not design. The same condition destroyed this board three times
previously (2170 rows → 18, 2136 → 21, 2138 → 1), because "reconcile" deletes
rows absent from whichever store is treated as the source.

The retire-before-switch step is what makes it impossible rather than lucky.

---

## Checklist

```
[ ] preflight is READY on a snapshot taken today, not on an earlier run
[ ] every trigger and index still translates (0 uncarried)
[ ] every carried object EXECUTED against the destination and rolled back
[ ] destination has a FRESH store_uuid; predecessor recorded in the marker
[ ] destination database freshly created, old one kept for rollback
[ ] per-table counts taken BEFORE the copy, from the snapshot
[ ] copy reports ok, marker written
[ ] per-table counts AFTER: drift is zero
[ ] independent verification by the other party, by id AND content
[ ] all schema objects owned by the role the application connects as
[ ] the DSN resolves from inside a CONTAINER, not only on the host
[ ] the real CLIENT opens the destination — read, write, inbox, threads
[ ] retirement guard proven to FIRE on the source
[ ] source retired
[ ] readers repointed
[ ] restart complete, no process left on the old path
[ ] FINAL delta carry, after the restart, by id and content, never by clock
[ ] the four retirement rows explicitly NOT carried
[ ] carry verified by the party who did not apply it
```

The last four exist because the list used to end at "restart complete", and
everything after that line is what was lost on 2026-07-31.
