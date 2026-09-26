# Primary WAL offsite lane

## The hole this closes

Measured 2026-08-27 on scitex-nas-03 (the fleet primary): archiver healthy,
208 segments archived — every one of them on the same disk as the database
they exist to protect. `archive_command` copies to a local directory and
nothing shipped it anywhere. One disk failure loses the database AND its
recovery chain together. (Standing card:
`pg-live-primary-wal-has-no-offsite-copy-20260826`.)

## What it is

- `wal-sync-primary.sh` — ports compute-04's production `wal_sync.sh` verdict
  rules (its header records the audits that paid for them): archiver health
  first and it FAILS the unit; prune only files individually confirmed
  offsite BY NAME; zero segments with archiving on is an emergency; staleness
  and timeline gates because `failed=0` forever is what a disabled archiver
  looks like.
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
