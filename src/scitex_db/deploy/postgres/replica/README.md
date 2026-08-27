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

## The fleet's actual shape (measured 2026-08-28)

```
                      nas-03  PRIMARY (docker/compose, the only writer)
                        |
      +---------+-------+-------+---------+
      |         |               |         |
  compute-01 compute-02   compute-03  compute-04     direct standbys (apptainer)
```

`nas-02` also held a standby until 2026-08-28 — a **cascaded** one following
compute-04 rather than the primary. It was retired on the operator's call: it
carried nothing that did not already exist on six other machines, and it made
the offsite host depend on a compute node staying up. Stopped, not deleted;
the 1.3G datadir is still on disk pending confirmation.

Seven of nine hosts. `nas-01` is not a candidate: armv7l 32-bit ARM, no
container runtime, and not on the overlay — it cannot reach the primary, whose
`pg_hba` admits replication only from `100.64.0.0/10`. It is a backup target.
The two laptops are the logical-replication case, not this one.

### A cascaded standby is invisible from the primary

`nas-02` follows **compute-04**, not nas-03. So it does **not** appear in the
primary's `pg_stat_replication` — a standby only ever shows up on its own
upstream. Reasoning "nas-03 doesn't list it, therefore it isn't replicating"
is a true premise with a false conclusion, and it cost three wrong turns to
undo. To map the tree, query `pg_stat_replication` on **every** node, not just
the root.

Note the coupling this creates: nas-02 is the offsite copy and has the longest
dependency chain. If compute-04 stops, the machine furthest from the primary
stops receiving. Repointing it directly at nas-03 with its own slot removes
that.

### Three probes that lie about whether a replica exists

Measured while mapping this, each one wrong in a different way:

- **`docker ps` filtered by an expected name.** nas-02's replica is called
  `pg18-replica`, not `scitex-*`. Filtering a population by the name you expect
  is not an enumeration.
- **`sudo test -f standby.signal && echo PRESENT || echo absent`.** On a host
  where sudo needs a password, the *sudo failure* renders as "file absent".
  Read from inside the container, where no host sudo is involved.
- **`ss -ltn | grep 55432` and `/dev/tcp` and `ping`** all reported nothing on
  the QNAP while postgres was demonstrably serving — non-root `ss` does not see
  the socket, the remote shell is `sh`, and `ping` needs root. Only running the
  real client (`pg_isready`) was correct.

`PGDATA` is also not always `/var/lib/postgresql/data`; on nas-02 it is
`/work/data`. Ask the process (`printenv PGDATA`), do not assume the image
default.

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
