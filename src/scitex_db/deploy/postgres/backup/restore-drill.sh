#!/bin/bash
# RESTORE DRILL — restore the newest dump into a THROWAWAY server and count
# what came back. Until this runs, a backup is a belief; after it runs, it is
# a control.
#
# The drill answers one question the dump lane CANNOT: pg_dump exiting 0 says
# the read succeeded, not that the artifact reloads. A dump that restores to
# an empty schema is a green backup lane and a lost database.
#
# SAFETY, checked before anything starts. The drill's whole job is to write a
# database, so it must be structurally incapable of writing the LIVE one:
#   - the drill port must differ from the live port          (refuses otherwise)
#   - the drill container name must differ from the live one (refuses otherwise)
#   - the drill container is removed on every exit path      (trap)
# These are guards, not comments: each is a hard exit before any restore runs.
set -uo pipefail

: "${SCITEX_PG_DUMP_DIR:?directory holding the dumps to drill}"
LIVE_PORT="${SCITEX_PG_PORT:-55432}"
LIVE_CTR="${SCITEX_PG_LIVE_CONTAINER:-scitex-pg18}"
DRILL_PORT="${SCITEX_PG_DRILL_PORT:-55499}"
DRILL_CTR="${SCITEX_PG_DRILL_CONTAINER:-scitex-pg-restore-drill}"
IMAGE="${SCITEX_PG_IMAGE:-postgres:18-trixie}"
DBS="${SCITEX_PG_DUMP_DBS:?space-separated databases to drill}"
MIN_ROWS="${SCITEX_PG_DRILL_MIN_ROWS:-1}"

RC=0
fail(){ echo "ALERT: $*"; RC=1; }

# --- guards: refuse to be pointed at the live server -----------------------
[ "$DRILL_PORT" = "$LIVE_PORT" ] && { echo "REFUSING: drill port $DRILL_PORT == live port"; exit 2; }
[ "$DRILL_CTR"  = "$LIVE_CTR"  ] && { echo "REFUSING: drill container == live container"; exit 2; }

cleanup(){ docker rm -f "$DRILL_CTR" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# --- 1. a throwaway server from the SAME declared image --------------------
cleanup
if ! docker run -d --name "$DRILL_CTR" --network host \
      -e POSTGRES_PASSWORD=drill -e PGPORT="$DRILL_PORT" \
      "$IMAGE" -c port="$DRILL_PORT" -c listen_addresses=127.0.0.1 >/dev/null 2>&1; then
  echo "ALERT: could not start the drill server"; exit 1
fi
for i in $(seq 1 60); do
  docker exec "$DRILL_CTR" pg_isready -h 127.0.0.1 -p "$DRILL_PORT" >/dev/null 2>&1 && break
  sleep 2
done
docker exec "$DRILL_CTR" pg_isready -h 127.0.0.1 -p "$DRILL_PORT" >/dev/null 2>&1 \
  || { echo "ALERT: drill server never became ready"; exit 1; }

# --- 2. restore the NEWEST dump of each database, and count ----------------
for db in $DBS; do
  f=$(ls -1t "$SCITEX_PG_DUMP_DIR"/${db}-*.dump 2>/dev/null | head -1)
  if [ -z "$f" ]; then fail "no dump found for $db — nothing to drill"; continue; fi

  docker exec -e PGPASSWORD=drill "$DRILL_CTR" \
    psql -h 127.0.0.1 -p "$DRILL_PORT" -U postgres -d postgres \
    -c "DROP DATABASE IF EXISTS drill_$db" -c "CREATE DATABASE drill_$db" >/dev/null 2>&1

  # -e: exit nonzero on error. Without it pg_restore reports 0 after logging
  # failures, which is exactly the silent-success shape this drill exists to
  # catch.
  if docker exec -i -e PGPASSWORD=drill "$DRILL_CTR" \
       pg_restore -h 127.0.0.1 -p "$DRILL_PORT" -U postgres -d "drill_$db" -e --no-owner --no-acl \
       < "$f" >/dev/null 2>&1; then
    :
  else
    fail "RESTORE FAILED for $db from $(basename "$f")"
    continue
  fi

  # The count is the point. A restore that "succeeds" into an empty database
  # is the failure this drill exists to detect, so an empty result is an ALERT
  # and never a pass.
  tables=$(docker exec -e PGPASSWORD=drill "$DRILL_CTR" psql -h 127.0.0.1 -p "$DRILL_PORT" \
           -U postgres -d "drill_$db" -Atc \
           "select count(*) from information_schema.tables where table_schema not in ('pg_catalog','information_schema')" 2>/dev/null | tail -1)
  rows=$(docker exec -e PGPASSWORD=drill "$DRILL_CTR" psql -h 127.0.0.1 -p "$DRILL_PORT" \
         -U postgres -d "drill_$db" -Atc \
         "select coalesce(sum(n_live_tup),0) from pg_stat_user_tables" 2>/dev/null | tail -1)
  : "${tables:=0}" "${rows:=0}"

  if [ "$tables" -ge 1 ] && [ "$rows" -ge "$MIN_ROWS" ]; then
    echo "RESTORED $db from $(basename "$f"): ${tables} tables, ${rows} rows"
  else
    fail "$db restored EMPTY or near-empty (tables=$tables rows=$rows) — the artifact does not reload"
  fi
done

[ "$RC" -eq 0 ] && echo "drill PASSED — every dump reloaded with data"
exit "$RC"
