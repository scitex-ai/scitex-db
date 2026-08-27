# The fleet's PostgreSQL, declared

## Why this exists

On 2026-08-27 the fleet's intended primary (scitex-nas-03) was found running
as a hand-typed `docker run`: `docker inspect` showed an empty label set,
which is the fingerprint of a container no compose file manages. The server
worked; nobody could recreate it. The operator's ruling the same day:

> Postgres の中で手作業があるとこういうことができない
> (manual steps inside Postgres make this architecture impossible)

"This architecture" is: **primary on scitex-nas-03; a replica on every other
host; an isolated host keeps working alone and resyncs on return; sync logic
belongs to each leaf package** (scitex-cards syncs cards, etc.). A server
nobody can recreate cannot be the base of that.

## What this is, and is not

- `docker-compose.yml` — the SERVER, byte-equivalent to what ran hand-typed
  on nas-03 (same image, port, listen shape, WAL archiving, hot_standby).
- `env.<host>.example` — per-host values. Copy to `.env`, adjust, `up -d`.
- NOT here: replication topology, promotion, per-package sync. Those are
  separate concerns; declaring the server is the precondition for all of them.

## Deploying

    cp -f env.nas-03.example .env    # edit for this host
    docker compose up -d

`SCITEX_PG_LISTEN` has no default on purpose: an address baked into a shared
file is correct on exactly one host and silently wrong on the rest — the
failure mode that made vpn.scitex.ai's predecessor painful. The compose
REFUSES to start without it (`:?`), which is a declaration failing loudly
rather than evaporating.

## Verifying — a check that can fail

    docker inspect scitex-pg18 --format '{{.State.Health.Status}}'   # healthy
    psql "host=127.0.0.1 port=55432 dbname=postgres" -c 'select 1'   # from the host

`docker ps` says "Up" for a crash-looping server; `systemctl is-active` was
measured lying the same way for headscale on 2026-08-27. `pg_isready` (the
healthcheck) and an actual query are the honest instruments.

## Known state at time of writing

- nas-03's live container is named `scitex-cards-pg18` and is UNMANAGED.
  Adopting it into this compose is a restart (seconds), but it is the fleet's
  ONLY primary, so do it deliberately, not casually.
- The name here is `scitex-pg18`, not `scitex-cards-pg18`: the operator's
  correction of 2026-08-27 — cards is ONE SCOPE inside the database, and the
  container's old name commits the same vendor-name-as-scope error the
  constitution warns about.
- compute-01..04 run per-host instances under `scitex-cards-pg.service`
  (apptainer, not docker) — a second mechanism for the same intent. Unifying
  them onto one declaration is follow-up work, not this file.
