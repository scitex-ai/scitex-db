# The replica side, declared

The primary is declared in `../docker-compose.yml`. This is the other half:
the four streaming replicas that follow it.

Until this directory existed, a replica could only be rebuilt by whoever
remembered how the last one was made. The configuration lived in running
processes and in `postgresql.auto.conf` on each host — which is the condition
the operator ruled against: *「Postgres の中で手作業があるとこういうことができない」*.

## What runs

| | primary | replica |
|---|---|---|
| host | scitex-nas-03 | compute-01..04 |
| runtime | docker + compose | **apptainer** + systemd user unit |
| image | `postgres:18-trixie` | `~/.scitex/pg/postgres18.sif` |
| port | 55432 | 55432 |
| role | writer | physical standby (read-only) |

Same intent, two runtimes, because the compute hosts run rootless with no
docker daemon. The mechanism is a parameter of the deployment, not a property
of the database.

### Do not identify the runtime by asking the runtime

`apptainer exec` **registers no instance**, so `apptainer instance list` is
empty while a replica runs; apptainer also shares the host PID and network
namespaces, so the postmaster shows up in the host process table with a
host-visible listener. `docker ps` empty **plus** `apptainer instance list`
empty reads exactly like "not containerised", and is wrong. Read the unit:

    systemctl --user cat scitex-cards-pg.service

## Per-host values

Only two, measured across all four replicas 2026-08-27:

- `SCITEX_PG_SLOT` — this replica's slot on the primary (`replica_c01`…`c04`)
- `SCITEX_PG_LISTEN` — this host's own overlay address

Everything else is identical. Copy `replica.env.compute-01.example`, change
those two.

## Building a replica from nothing

1. **On the primary**, create the slot. The slot is what makes a partition
   self-healing: the primary retains WAL for a disconnected replica so it
   catches up on return instead of needing a rebuild.

       SELECT pg_create_physical_replication_slot('replica_cNN');

2. **On the replica host**, take a base backup as `svc_replica`. `-R` writes
   `standby.signal` and `primary_conninfo` for you — that is where the running
   replicas' `postgresql.auto.conf` came from:

       pg_basebackup -h scitex-primary -p 55432 -U svc_replica \
         -D ~/.scitex/pg/18/main -R -S replica_cNN -X stream -P

3. Set `listen_addresses` and `port` in `postgresql.conf`.

4. Install `preflight_datadir.sh` to `~/.scitex/pg/bin/`, the env file to
   `~/.scitex/pg/replica.env`, the unit to `~/.config/systemd/user/`, then
   `systemctl --user enable --now scitex-cards-pg.service`.

## Verify — from the replica, not from the primary

The primary's `pg_stat_replication` shows a row per replica, but
`state`/`sync_state`/lag come back **empty** for `svc_replica`, which lacks
`pg_read_all_stats`. Four blank rows are a permission artifact, not four broken
standbys. Ask the replica about itself:

    pgrep -af walreceiver     # -> postgres: walreceiver streaming 4/60000148

Two replicas reporting the *same* LSN is good corroboration that the value is
live rather than a stale process title.

## Retiring a replica

**Drop its slot on the primary.** A slot for a replica that never returns pins
WAL forever and will fill the primary's disk. The property that makes a
partition survivable is the same one that makes an abandoned slot dangerous.

## Preconditions that are easy to miss

- `scitex-primary` must resolve on the replica host (`/etc/hosts` or DNS).
  `primary_conninfo` names it rather than addressing it; when resolution breaks,
  replication stops with what looks like a network fault.
- `~/.pgpass` must carry the `svc_replica` row, mode 0600.
- pg_hba on the primary admits replication over loopback and the overlay
  (`100.64.0.0/10`) only — not over the LAN.
