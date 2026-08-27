#!/bin/bash
# Nightly LOGICAL dumps of the primary, pushed offsite, each artifact verified
# THERE by name and size.
#
# A logical dump is not the PITR chain (see wal-sync-primary.sh) and the PITR
# chain is not a dump: pg_dump restores anywhere without WAL; PITR replays to
# a moment. Keeping both is deliberate, not redundancy.
#
# Ported failure discipline (compute-04's scitex-pg-backup.sh + pitr_anchor.sh,
# whose headers record what each rule cost):
#   - any dump failure fails the unit; a push failure fails the unit AFTER the
#     local dumps exist (local-first: a broken offsite host never costs a dump)
#   - offsite verification asks about THIS run's files BY NAME AND SIZE —
#     counting *.dump would pass forever once any older artifact existed
#   - globals fallback is deliberate loud ABSENCE, never silent
set -uo pipefail

: "${SCITEX_PG_EXEC:?command prefix that runs a client in the server context}"
: "${SCITEX_PG_DUMP_DIR:?host directory for local dumps}"
: "${SCITEX_PG_OFFSITE_HOST:?ssh target, e.g. user@host}"
: "${SCITEX_PG_OFFSITE_DUMP_PATH:?remote dir for dumps}"
DBS="${SCITEX_PG_DUMP_DBS:?space-separated databases to dump}"
PGUSER="${SCITEX_PG_DUMP_USER:-svc_backup}"
PGHOST="${SCITEX_PG_DUMP_HOST:-127.0.0.1}"
PGPORT="${SCITEX_PG_PORT:-55432}"
KEEP_DAYS="${SCITEX_PG_DUMP_KEEP_DAYS:-7}"
SSH_KEY="${SCITEX_PG_SSH_KEY:-}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
[ -n "$SSH_KEY" ] && SSH_OPTS+=(-i "$SSH_KEY")

DATE=$(date -u +%F)
RC=0
fail(){ echo "ALERT: $*"; RC=1; }
mkdir -p "$SCITEX_PG_DUMP_DIR"; chmod 700 "$SCITEX_PG_DUMP_DIR"

# --- 1. dump each database, streaming out of the server context ------------
for db in $DBS; do
  f="$SCITEX_PG_DUMP_DIR/${db}-${DATE}.dump"
  if $SCITEX_PG_EXEC pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$db" -Fc > "$f" 2>/dev/null \
     && [ -s "$f" ]; then
    echo "dumped $db -> $(basename "$f") ($(stat -c %s "$f") B)"
  else
    rm -f "$f"   # a zero-byte artifact is worse than an absent one
    fail "DUMP FAILED: $db"
  fi
done

# --- 2. globals: fallback is loud absence, not silence ---------------------
g="$SCITEX_PG_DUMP_DIR/globals-${DATE}.sql"
if $SCITEX_PG_EXEC pg_dumpall -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" --globals-only > "$g" 2>/dev/null && [ -s "$g" ]; then
  echo "globals -> $(basename "$g")"
else
  rm -f "$g"
  echo "globals dump not permitted to $PGUSER (expected: pg_authid is superuser-only); ABSENT, recorded"
fi

# --- 3. local retention ----------------------------------------------------
find "$SCITEX_PG_DUMP_DIR" -maxdepth 1 -type f -mtime "+$KEEP_DAYS" -print -delete | sed 's/^/pruned /'

# --- 4. push (idempotent; never rewrite a shipped artifact) ----------------
ssh "${SSH_OPTS[@]}" "$SCITEX_PG_OFFSITE_HOST" "mkdir -p $SCITEX_PG_OFFSITE_DUMP_PATH" >/dev/null 2>&1 \
  || { fail "offsite mkdir failed"; exit "$RC"; }
if rsync -a --ignore-existing -e "ssh ${SSH_OPTS[*]}" "$SCITEX_PG_DUMP_DIR/" \
     "$SCITEX_PG_OFFSITE_HOST:$SCITEX_PG_OFFSITE_DUMP_PATH/" >/dev/null 2>&1; then
  echo "pushed"
else
  fail "offsite push FAILED — dumps exist locally only"
  exit "$RC"
fi

# --- 5. verify THIS run's artifacts offsite, by name and size --------------
for db in $DBS; do
  b="${db}-${DATE}.dump"
  lb=$(stat -c %s "$SCITEX_PG_DUMP_DIR/$b" 2>/dev/null || echo missing-local)
  rb=$(ssh "${SSH_OPTS[@]}" "$SCITEX_PG_OFFSITE_HOST" "stat -c %s $SCITEX_PG_OFFSITE_DUMP_PATH/$b 2>/dev/null" 2>/dev/null | tail -1)
  if [ "$lb" = "${rb:-absent}" ]; then
    echo "CONFIRMED offsite: $b ($lb B)"
  else
    fail "$b NOT offsite intact (local=$lb remote=${rb:-absent})"
  fi
done

exit "$RC"
