#!/bin/bash
# Push the PRIMARY's archived WAL offsite, prune only what is individually
# confirmed there, and FAIL LOUDLY when the archiver itself is broken.
#
# WHY THIS EXISTS. WAL sitting only on the primary is worth nothing the moment
# the primary is what failed. Measured 2026-08-27 on scitex-nas-03: 208
# archived segments, all on the same disk as the database they protect.
#
# This is a PORT of compute-04's wal_sync.sh, which paid for its verdict rules
# in production (its own header records the audits). The rules it inherits:
#   - archiver health is checked FIRST and FAILS the run — an alert that
#     cannot fail the unit is a printout, not an alarm (2026-08-25 defect #1)
#   - prune compares IDENTITY, never counts — remote_count >= local_count can
#     hold while the two sets name different files (2026-08-25 defect #2)
#   - zero local segments with archiving ON is an emergency, not quiet
#     success (2026-08-25 defect #3)
#   - staleness and timeline are gated: archived=0/failed=0 forever is what a
#     disabled archiver looks like, and no failure-count test catches it
#
# Everything host-specific arrives from the environment (see env example
# beside this file). No address, path, or host is baked in.
set -uo pipefail

: "${SCITEX_PG_ARCHIVE_DIR:?path of the primary WAL archive dir}"
: "${SCITEX_PG_OFFSITE_HOST:?ssh host to push to, e.g. scitex-nas-02}"
: "${SCITEX_PG_OFFSITE_PATH:?remote path, e.g. pg-backups/nas-03/wal-archive}"
: "${SCITEX_PG_ARCHIVER_STATUS:?command printing key=value archiver status}"
SSH_KEY="${SCITEX_PG_SSH_KEY:-}"           # explicit identity; alias-default otherwise
SUDO="${SCITEX_PG_SUDO:-}"                 # e.g. "/usr/bin/sudo -n" when the archive
                                           # is owned by the container uid; empty if not needed
KEEP_DAYS="${SCITEX_PG_KEEP_DAYS:-14}"
STALE_MIN="${SCITEX_PG_ARCHIVE_STALE_MIN:-30}"

RC=0
STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
fail(){ echo "$STAMP ALERT: $*"; RC=1; }
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
[ -n "$SSH_KEY" ] && SSH_OPTS+=(-i "$SSH_KEY")
# When the push runs under sudo, ssh runs as ROOT: it does not read the login
# user's ~/.ssh/config or known_hosts, so an alias that resolves for the user
# does not resolve for the transfer (measured on the first live run: sudo
# rsync failed while the same alias worked unprivileged). Carry both files
# explicitly so the privileged and unprivileged halves see the same world.
SSH_CONFIG="${SCITEX_PG_SSH_CONFIG:-$HOME/.ssh/config}"
KNOWN_HOSTS="${SCITEX_PG_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"
[ -f "$SSH_CONFIG" ] && SSH_OPTS+=(-F "$SSH_CONFIG")
[ -f "$KNOWN_HOSTS" ] && SSH_OPTS+=(-o "UserKnownHostsFile=$KNOWN_HOSTS")

# --- 1. archiver health FIRST, on the PRIMARY, and it can fail the run -----
PS=$($SCITEX_PG_ARCHIVER_STATUS 2>/dev/null)
if [ -z "$PS" ]; then
  fail "archiver status unreadable — archiving state is UNKNOWN, not fine"
else
  pv(){ printf '%s\n' "$PS" | sed -n "s/^$1=//p" | head -1; }
  INREC=$(pv in_recovery); MODE=$(pv archive_mode); FAILED=$(pv failed_count)
  AGE=$(pv age_min); TLNOW=$(pv timeline_now); TLARCH=$(pv timeline_archived)
  echo "$STAMP archiver mode=$MODE failed=$FAILED age_min=$AGE tl_now=$TLNOW tl_arch=$TLARCH in_recovery=$INREC"
  [ "$INREC" = "f" ] || fail "this host reports pg_is_in_recovery='$INREC' — it is NOT the writer; this lane is pointed at the wrong server"
  [ "$MODE" = "on" ] || fail "archive_mode is '$MODE', not on — the writer is archiving NOTHING"
  case "$FAILED" in ''|*[!0-9]*) fail "failed_count unreadable ('$FAILED')";; 0) : ;; *) fail "archiving has FAILED $FAILED time(s) — PITR has a hole from that point";; esac
  case "$AGE" in
    '') fail "NEVER archived a segment (last_archived_time NULL) — archiving is not running" ;;
    *[!0-9]*) fail "last_archived age unreadable ('$AGE')" ;;
    *) [ "$AGE" -le "$STALE_MIN" ] || fail "last archived segment is ${AGE}m old (threshold ${STALE_MIN}m) — the archive stopped growing" ;;
  esac
  if [ -n "${TLARCH:-}" ] && [ -n "${TLNOW:-}" ]; then
    case "$TLARCH" in *[!0-9]*) fail "archived timeline unreadable ('$TLARCH')";; *)
      [ "$((10#$TLARCH))" = "$TLNOW" ] || fail "archive is on timeline $((10#$TLARCH)) but the cluster is on $TLNOW — archiving stopped when the role moved";; esac
  fi
fi

# --- 2. enumerate (via sudo where the archive is container-owned) ----------
LOCAL_LIST=$($SUDO ls -1 "$SCITEX_PG_ARCHIVE_DIR" 2>/dev/null)
LOCAL_N=$(printf '%s\n' "$LOCAL_LIST" | grep -c . || true)
echo "$STAMP local segments=$LOCAL_N"
if [ "$LOCAL_N" -eq 0 ]; then
  # an unreadable dir and an empty dir produce the same 0 — tell them apart
  if ! $SUDO test -r "$SCITEX_PG_ARCHIVE_DIR"; then
    fail "archive dir unreadable even via '\$SUDO' — this run measured NOTHING"
  else
    fail "archive_mode=on but the archive directory is EMPTY — nothing is being produced"
  fi
  exit "$RC"
fi

# --- 3. push. rsync is idempotent; segments are immutable once archived ----
ssh "${SSH_OPTS[@]}" "$SCITEX_PG_OFFSITE_HOST" "mkdir -p $SCITEX_PG_OFFSITE_PATH" >/dev/null 2>&1
if $SUDO rsync -a --timeout=180 -e "ssh ${SSH_OPTS[*]}" \
     "$SCITEX_PG_ARCHIVE_DIR/" "$SCITEX_PG_OFFSITE_HOST:$SCITEX_PG_OFFSITE_PATH/" >/dev/null 2>&1; then
  echo "$STAMP push ok"
else
  fail "rsync to $SCITEX_PG_OFFSITE_HOST FAILED. WAL remains on the primary only."
  echo "$STAMP exiting before prune — never prune on a failed push"
  exit 1
fi

# --- 4. confirm from the FAR SIDE, BY NAME ---------------------------------
REMOTE_LIST=$(ssh "${SSH_OPTS[@]}" "$SCITEX_PG_OFFSITE_HOST" "ls -1 $SCITEX_PG_OFFSITE_PATH 2>/dev/null" 2>/dev/null)
REMOTE_N=$(printf '%s\n' "$REMOTE_LIST" | grep -c . || true)
echo "$STAMP remote segments=$REMOTE_N"
if [ -z "$REMOTE_LIST" ]; then
  echo "$STAMP holding: could not list the remote archive; pruning nothing this pass"
  exit "$RC"
fi

# --- 5. prune only what is BOTH aged out AND individually confirmed --------
PRUNED=0; HELD=0
while IFS= read -r b; do
  [ -n "$b" ] || continue
  if printf '%s\n' "$REMOTE_LIST" | grep -qxF "$b"; then
    $SUDO rm -f "$SCITEX_PG_ARCHIVE_DIR/$b" && PRUNED=$((PRUNED+1))
  else
    HELD=$((HELD+1))
    echo "$STAMP holding $b — aged >${KEEP_DAYS}d but NOT found offsite by name"
  fi
done < <($SUDO find "$SCITEX_PG_ARCHIVE_DIR" -maxdepth 1 -type f -mtime "+$KEEP_DAYS" -printf '%f\n' 2>/dev/null)
echo "$STAMP pruned=$PRUNED held=$HELD (each pruned file confirmed offsite BY NAME)"

exit "$RC"
