# Primary WAL offsite lane

## The hole this closes

Measured 2026-08-27 on scitex-nas-03 (the fleet primary): archiver healthy,
208 segments archived — every one of them on the same disk as the database
they exist to protect. `archive_command` copies to a local directory and
nothing shipped it anywhere. One disk failure loses the database AND its
recovery chain together. (Standing card:
`pg-live-primary-wal-has-no-offsite-copy-20260826`.)

## What it is

- `wal-sync-primary.sh` ports compute-04's production `wal_sync.sh` verdict
  rules. Its header records the audits that paid for them. Archiver health is
  checked first, and a failure fails the unit. Zero segments with archiving on
  is an emergency. Staleness and timeline are gated, because `failed=0`
  forever is also what a disabled archiver looks like.
  Hardened after the 2026-11-24/25 outage:
  - **Offsite is confirmed by content, not by name.** A file counts as
    offsite only when the far side has the same size AND the same SHA-256.
    Each file is hashed once per side (at most `SCITEX_PG_VERIFY_MAX` per
    run), and the match is recorded in `$SCITEX_PG_STATE_DIR/verified.tsv`.
    Files about to be pruned are hashed again on both sides just before
    deletion.
  - **No pruning on a bad run.** Any alert in a run means nothing is deleted
    that run: archiver unhealthy, database unreachable, push failed, a
    truncated segment, or a conflict.
  - **The push never overwrites.** It uses `rsync --ignore-existing`. A far
    side file that differs from the local one is a CONFLICT. The run alerts,
    keeps both (the local copy is uploaded beside it as
    `NAME.conflict-<sha12>`), and prunes neither.
  - **A segment whose size is not 16 MiB is a truncated copy.** The run
    alerts, does not push it, and does not prune it.
  - **Every alert exits non-zero.** `--dry-run` measures and verifies but
    changes nothing.
- `scitex-pg-wal-sync.{service,timer}` — user units, every 15 minutes.
- `wal-sync.env.<host>.example` — per-host values. Nothing is baked in; the
  script refuses to run without its declarations (`:?`).

## Installing (nas-03)

    mkdir -p ~/.scitex/pg/bin ~/.scitex/pg/logs
    cp -f wal-sync-primary.sh ~/.scitex/pg/bin/
    cp -f wal-sync.env.nas-03.example ~/.scitex/pg/wal-sync.env   # edit
    cp -f scitex-pg-wal-sync.{service,timer} ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now scitex-pg-wal-sync.timer

## Verifying — checks that can fail

    # load the env file the way systemd's EnvironmentFile= does (values are unquoted)
    while IFS= read -r l; do case "$l" in ''|'#'*) ;; *) export "$l" ;; esac; done < ~/.scitex/pg/wal-sync.env
    ~/.scitex/pg/bin/wal-sync-primary.sh --dry-run; echo rc=$?   # changes nothing
    systemctl --user start scitex-pg-wal-sync.service; echo rc=$?
    tail ~/.scitex/pg/logs/wal-sync.log
    ssh -i ~/.ssh/id_mesh scitex-nas-02 'ls pg-backups/nas-03/wal-archive | wc -l'

The far-side count must match the local archive. The unit exits non-zero on
a broken archiver, a failed push, or an unreadable archive dir — an
unreadable dir and an empty dir both read as 0, so the script distinguishes
them explicitly (that exact confusion produced a false "files: 0" reading
during the survey that led to this file).

## Trust prerequisites, stated rather than assumed

- nas-03 → nas-02 ssh as `id_mesh` (authorized 2026-08-27; the alias without
  `-i` selects a different identity and is DENIED — hence the explicit key).
- sudo on nas-03 (the archive dir is uid-70-owned, mode 700).
