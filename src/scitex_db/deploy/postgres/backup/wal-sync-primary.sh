#!/bin/bash
# Push the PRIMARY's archived WAL offsite, prune only what is confirmed there BY
# CONTENT, and FAIL LOUDLY when anything about the archive is wrong.
#
# WHY THIS EXISTS. WAL sitting only on the primary is worth nothing the moment
# the primary is what failed. Measured 2026-08-27 on scitex-nas-03: 208
# archived segments, all on the same disk as the database they protect.
#
# This is a PORT of compute-04's wal_sync.sh, which paid for its verdict rules
# in production (its own header records the audits). The rules it inherits:
#   - archiver health is checked FIRST and FAILS the run -- an alert that
#     cannot fail the unit is a printout, not an alarm (2026-08-25 defect #1)
#   - prune compares IDENTITY, never counts (2026-08-25 defect #2)
#   - zero local segments with archiving ON is an emergency (2026-08-25 #3)
#   - staleness and timeline are gated: archived=0/failed=0 forever is what a
#     disabled archiver looks like
#
# HARDENED AFTER THE 2026-11-24/25 OUTAGE (the disk under scitex-pg18 filled):
#   - "offsite" was confirmed by NAME. A segment truncated by ENOSPC was pushed,
#     its name appeared on the far side, and it counted as safe. Now a file is
#     confirmed only when the far-side SIZE and SHA-256 equal the local file's.
#     Each file is hashed once on each side and the match is recorded in a
#     ledger; the files about to be pruned are hashed AGAIN on both sides
#     immediately before deletion.
#   - the run kept PRUNING while its own health check was alerting. Now any
#     alert in a run (archiver unhealthy, DB unreachable, push failed, a
#     truncated segment, a conflict) means NOTHING is pruned that run.
#   - the push used `rsync -a`, which replaces a good remote copy with a bad
#     local one. Now the push never overwrites (--ignore-existing). A remote
#     file that differs from the local one is reported as a CONFLICT, both
#     copies are kept (the local one is uploaded beside the remote one as
#     NAME.conflict-<sha12>), and neither is ever pruned.
#   - a segment whose size is not the WAL segment size is a truncated copy:
#     alert, do not push it, do not prune it.
#   - every alert makes the run exit non-zero.
#
# Usage: wal-sync-primary.sh [--dry-run]
#   --dry-run (or SCITEX_PG_DRY_RUN=1): measure and verify, report what would
#   be pushed and pruned, change nothing (no push, no upload, no ledger write,
#   no deletion). Exit status still reflects alerts.
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
SEGMENT_BYTES="${SCITEX_PG_WAL_SEGMENT_BYTES:-16777216}"
# Files hashed (each side) per run. Bounds the first runs after deployment,
# when nothing is in the ledger yet; later runs only hash new segments.
# Measured on nas-03 -> nas-02 (2026-11-25): 256 files took ~3.5 min, too
# close to the unit's 300 s timeout; 64 is ~50 s, and steady state archives
# ~3 segments per 15-minute run.
VERIFY_MAX="${SCITEX_PG_VERIFY_MAX:-64}"
STATE_DIR="${SCITEX_PG_STATE_DIR:-$HOME/.scitex/pg/wal-sync-state}"
LEDGER="$STATE_DIR/verified.tsv"
DRY_RUN="${SCITEX_PG_DRY_RUN:-0}"

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done
case "$DRY_RUN" in 1|true|yes) DRY_RUN=1 ;; *) DRY_RUN=0 ;; esac

RC=0; ALERTS=0
STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
fail(){ echo "$STAMP ALERT: $*"; RC=1; ALERTS=$((ALERTS+1)); }
note(){ echo "$STAMP $*"; }
[ "$DRY_RUN" = 1 ] && note "DRY RUN: nothing will be pushed, uploaded, recorded, or deleted"

# --- transport ---------------------------------------------------------------
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
# SCITEX_PG_RSH replaces ssh entirely (same calling convention: HOST CMD...).
# The tests use it to run the far side in a local directory.
if [ -n "${SCITEX_PG_RSH:-}" ]; then
  read -r -a RSH <<< "$SCITEX_PG_RSH"
else
  RSH=(ssh "${SSH_OPTS[@]}")
fi
RSYNC_RSH="${RSH[*]}"
HOST="$SCITEX_PG_OFFSITE_HOST"
RPATH=$(printf '%q' "$SCITEX_PG_OFFSITE_PATH")
# </dev/null: ssh otherwise reads the caller's stdin (a piped script, a heredoc)
# and swallows it -- measured on the first manual run of this version.
remote(){ "${RSH[@]}" "$HOST" "$1" < /dev/null; }

# Names this lane will handle. WAL segments, timeline history and backup
# labels all fit; anything else is held and reported, never pushed or pruned.
safe_name(){ [[ "$1" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]]; }
is_segment(){ [[ "$1" =~ ^[0-9A-F]{24}$ ]]; }

# --- 1. archiver health FIRST, on the PRIMARY, and it can fail the run -----
PS=$($SCITEX_PG_ARCHIVER_STATUS 2>/dev/null)
pv(){ printf '%s\n' "$PS" | sed -n "s/^$1=//p" | head -1; }
INREC=$(pv in_recovery); MODE=$(pv archive_mode); FAILED=$(pv failed_count)
AGE=$(pv age_min); TLNOW=$(pv timeline_now); TLARCH=$(pv timeline_archived)
if [ -z "$PS" ] || [ -z "$INREC$MODE$FAILED$AGE" ]; then
  # An all-empty answer is what the status script prints when psql cannot
  # reach the server: the database is DOWN or unreachable, not "fine".
  fail "archiver status unreadable -- the database is down or unreachable; archiving state is UNKNOWN"
else
  note "archiver mode=$MODE failed=$FAILED age_min=$AGE tl_now=$TLNOW tl_arch=$TLARCH in_recovery=$INREC"
  [ "$INREC" = "f" ] || fail "this host reports pg_is_in_recovery='$INREC' -- it is NOT the writer; this lane is pointed at the wrong server"
  [ "$MODE" = "on" ] || fail "archive_mode is '$MODE', not on -- the writer is archiving NOTHING"
  case "$FAILED" in ''|*[!0-9]*) fail "failed_count unreadable ('$FAILED')";; 0) : ;; *) fail "archiving has FAILED $FAILED time(s) -- PITR has a hole from that point";; esac
  case "$AGE" in
    '') fail "NEVER archived a segment (last_archived_time NULL) -- archiving is not running" ;;
    *[!0-9]*) fail "last_archived age unreadable ('$AGE')" ;;
    *) [ "$AGE" -le "$STALE_MIN" ] || fail "last archived segment is ${AGE}m old (threshold ${STALE_MIN}m) -- the archive stopped growing" ;;
  esac
  if [ -n "${TLARCH:-}" ] && [ -n "${TLNOW:-}" ]; then
    case "$TLARCH" in *[!0-9]*) fail "archived timeline unreadable ('$TLARCH')";; *)
      [ "$((10#$TLARCH))" = "$TLNOW" ] || fail "archive is on timeline $((10#$TLARCH)) but the cluster is on $TLNOW -- archiving stopped when the role moved";; esac
  fi
fi

# --- 2. enumerate the local archive (via sudo where it is container-owned) --
if ! ARCHIVE_ROOT=$($SUDO realpath -- "$SCITEX_PG_ARCHIVE_DIR" 2>/dev/null); then
  fail "cannot resolve the archive dir '$SCITEX_PG_ARCHIVE_DIR' (even via '\$SUDO') -- this run measured NOTHING"
  exit "$RC"
fi
if ! WORK=$(mktemp -d); then
  fail "cannot create a private work dir -- this run measured NOTHING"
  exit 1
fi
trap 'rm -rf -- "$WORK"' EXIT

if ! $SUDO find "$ARCHIVE_ROOT" -maxdepth 1 -mindepth 1 -type f -printf '%T@\t%s\t%f\0' > "$WORK/local" 2>/dev/null; then
  fail "archive dir unreadable even via '\$SUDO' -- this run measured NOTHING"
  exit "$RC"
fi

declare -A LSIZE=() EXCLUDE=()
ORDER=()   # local names, oldest first
while IFS=$'\t' read -r mtime size name; do
  if [[ "$name" == .* ]]; then
    continue   # an in-progress archive_command or rsync temp file: not ours to move
  fi
  if ! safe_name "$name"; then
    fail "unexpected file name in the archive: $(printf '%q' "$name") -- held, not pushed"
    continue
  fi
  LSIZE["$name"]=$size
  ORDER+=("$mtime"$'\t'"$name")
  if is_segment "$name" && [ "$size" != "$SEGMENT_BYTES" ]; then
    fail "segment $name is $size bytes, not $SEGMENT_BYTES -- a TRUNCATED copy; not pushed, never pruned. Move it aside after checking pg_wal still holds the original"
    EXCLUDE["$name"]=1
  fi
done < <(tr '\0' '\n' < "$WORK/local")
mapfile -t ORDER < <(printf '%s\n' "${ORDER[@]+"${ORDER[@]}"}" | grep . | sort -n | cut -f2-)
LOCAL_N=${#ORDER[@]}
note "local files=$LOCAL_N"
if [ "$LOCAL_N" -eq 0 ]; then
  fail "archive_mode=on but the archive directory is EMPTY -- nothing is being produced"
  exit "$RC"
fi

# --- 3. push: never overwrite anything already on the far side --------------
: > "$WORK/exclude"
for name in "${!EXCLUDE[@]}"; do printf '/%s\n' "$name" >> "$WORK/exclude"; done
if [ "$DRY_RUN" = 1 ]; then
  note "push skipped (dry run)"
else
  if ! remote "mkdir -p $RPATH" >/dev/null 2>&1; then
    fail "could not create $HOST:$SCITEX_PG_OFFSITE_PATH. WAL remains on the primary only."
    note "exiting before prune -- never prune on a failed push"
    exit 1
  fi
  # --ignore-existing: a name already on the far side is NEVER rewritten, so a
  # bad local copy cannot replace a good offsite one. rsync writes to a temp
  # name and renames, so the far side never shows a partial file either.
  if $SUDO rsync -a --ignore-existing --timeout=180 -e "$RSYNC_RSH" \
       --exclude='.*' --exclude-from="$WORK/exclude" \
       "$ARCHIVE_ROOT/" "$HOST:$SCITEX_PG_OFFSITE_PATH/" >/dev/null 2>&1; then
    note "push ok"
  else
    fail "rsync to $HOST FAILED. WAL remains on the primary only."
    note "exiting before prune -- never prune on a failed push"
    exit 1
  fi
fi

# --- 4. far-side SIZES (busybox on the NAS: ls -ln, not find -printf) -------
if ! remote "cd $RPATH && LC_ALL=C ls -ln" > "$WORK/remote" 2>/dev/null; then
  if [ "$DRY_RUN" = 1 ]; then
    : > "$WORK/remote"
    note "remote archive not listable (dry run: treating as empty)"
  else
    fail "remote archive listing failed -- pruning nothing this pass"
    exit 1
  fi
fi
declare -A RSIZE=()
while read -r perms _ _ _ size _ _ _ name rest; do
  [ -z "${rest:-}" ] || continue
  case "$perms" in -*) ;; *) continue ;; esac
  [ -n "${name:-}" ] && RSIZE["$name"]=$size
done < "$WORK/remote"
note "remote files=${#RSIZE[@]}"

# --- 5. confirm BY CONTENT: size always, SHA-256 once per file -------------
declare -A LEDGER_OK=()
if [ -r "$LEDGER" ]; then
  while IFS=$'\t' read -r name size sha; do
    [ -n "${name:-}" ] && [ -n "${sha:-}" ] && LEDGER_OK["$name"]="$size"$'\t'"$sha"
  done < "$LEDGER"
fi

# hash_local/hash_remote NAME... -> "sha<TAB>name" lines. Names are safe_name()
# validated, so they pass through the remote shell without quoting.
hash_local(){
  local paths=() n
  for n in "$@"; do paths+=("$ARCHIVE_ROOT/$n"); done
  $SUDO sha256sum -- "${paths[@]}" 2>/dev/null | while read -r sha path; do
    printf '%s\t%s\n' "$sha" "${path##*/}"
  done
}
hash_remote(){
  remote "cd $RPATH && sha256sum -- $*" 2>/dev/null | while read -r sha path; do
    printf '%s\t%s\n' "$sha" "${path##*/}"
  done
}
# verify_batch NAME... : fills VSHA_L / VSHA_R for the given names (64 per call).
declare -A VSHA_L=() VSHA_R=()
verify_batch(){
  local -a names=("$@") chunk
  local i sha name
  for ((i=0; i<${#names[@]}; i+=64)); do
    chunk=("${names[@]:i:64}")
    while IFS=$'\t' read -r sha name; do VSHA_L["$name"]=$sha; done < <(hash_local "${chunk[@]}")
    while IFS=$'\t' read -r sha name; do VSHA_R["$name"]=$sha; done < <(hash_remote "${chunk[@]}")
  done
}

declare -A CONFLICT=() VERIFIED=()
TO_HASH=(); MISSING=0; PENDING=0
for name in "${ORDER[@]}"; do
  [ -n "${EXCLUDE[$name]+x}" ] && continue
  lsize=${LSIZE[$name]}
  if [ -z "${RSIZE[$name]+x}" ]; then
    MISSING=$((MISSING+1))
    if [ "$DRY_RUN" = 1 ]; then
      note "would push $name ($lsize bytes)"
    else
      fail "$name is not on the far side after a successful push"
    fi
    continue
  fi
  if [ "${RSIZE[$name]}" != "$lsize" ]; then
    CONFLICT["$name"]="size: local $lsize bytes, offsite ${RSIZE[$name]} bytes"
    continue
  fi
  if [ -n "${LEDGER_OK[$name]+x}" ] && [ "${LEDGER_OK[$name]%%$'\t'*}" = "$lsize" ]; then
    VERIFIED["$name"]=1
  elif [ "${#TO_HASH[@]}" -lt "$VERIFY_MAX" ]; then
    TO_HASH+=("$name")
  else
    PENDING=$((PENDING+1))
  fi
done
[ "${#TO_HASH[@]}" -gt 0 ] && verify_batch "${TO_HASH[@]}"
NEWLY=0
for name in "${TO_HASH[@]+"${TO_HASH[@]}"}"; do
  l=${VSHA_L[$name]:-}; r=${VSHA_R[$name]:-}
  if [ -z "$l" ] || [ -z "$r" ]; then
    fail "could not hash $name (local='${l:-?}' offsite='${r:-?}') -- not confirmed"
  elif [ "$l" = "$r" ]; then
    VERIFIED["$name"]=1
    LEDGER_OK["$name"]="${LSIZE[$name]}"$'\t'"$l"
    NEWLY=$((NEWLY+1))
  else
    CONFLICT["$name"]="sha256: local $l, offsite $r (same size ${LSIZE[$name]})"
  fi
done
note "verified=${#VERIFIED[@]} (newly hashed=$NEWLY) pending_verification=$PENDING conflicts=${#CONFLICT[@]} truncated=${#EXCLUDE[@]}"

# --- 6. conflicts: alert, keep BOTH copies, never prune either --------------
for name in "${!CONFLICT[@]}"; do
  fail "CONFLICT $name -- the offsite copy DIFFERS from the local one (${CONFLICT[$name]}). Neither is pruned or overwritten."
  if [ "$DRY_RUN" = 1 ]; then
    note "would upload the local copy beside it as $name.conflict-<sha12>"
    continue
  fi
  lsha=$(hash_local "$name" | cut -f1)
  if [ -z "$lsha" ]; then
    fail "could not hash local $name to preserve it offsite"
    continue
  fi
  side="$name.conflict-${lsha:0:12}"
  if $SUDO rsync -a --ignore-existing --timeout=180 -e "$RSYNC_RSH" \
       "$ARCHIVE_ROOT/$name" "$HOST:$SCITEX_PG_OFFSITE_PATH/$side" >/dev/null 2>&1; then
    note "kept both: the local copy of $name is now also offsite as $side"
  else
    fail "could not upload the local copy of $name as $side"
  fi
done

# --- 7. the ledger: names verified by content, for the next run -------------
write_ledger(){
  [ "$DRY_RUN" = 1 ] && return 0
  mkdir -p -- "$STATE_DIR" || { fail "cannot create $STATE_DIR"; return 1; }
  local tmp="$LEDGER.tmp.$$" name
  {
    for name in "${!LEDGER_OK[@]}"; do
      if [ -n "${LSIZE[$name]+x}" ]; then printf '%s\t%s\n' "$name" "${LEDGER_OK[$name]}"; fi
    done
  } | sort > "$tmp" && mv -f -- "$tmp" "$LEDGER" || { rm -f -- "$tmp"; fail "cannot write $LEDGER"; return 1; }
}
write_ledger

# --- 8. prune: ONLY on a clean run, ONLY re-confirmed content ---------------
if [ "$RC" -ne 0 ]; then
  note "NOT pruning: $ALERTS alert(s) this run. Nothing is deleted while anything is wrong."
  exit "$RC"
fi

if ! $SUDO find "$ARCHIVE_ROOT" -maxdepth 1 -type f -mtime "+$KEEP_DAYS" -printf '%f\0' > "$WORK/aged" 2>/dev/null; then
  fail "aged candidate enumeration failed -- pruning nothing"
  exit 1
fi
CANDIDATES=(); HELD=0
while IFS= read -r -d '' name; do
  if [ -n "${VERIFIED[$name]+x}" ] && [ "${#CANDIDATES[@]}" -lt "$VERIFY_MAX" ]; then
    CANDIDATES+=("$name")
  else
    HELD=$((HELD+1))
    [ -n "${VERIFIED[$name]+x}" ] || note "holding $(printf '%q' "$name") -- aged >${KEEP_DAYS}d but NOT confirmed offsite by size+sha256 yet"
  fi
done < "$WORK/aged"

# Hash the candidates AGAIN, both sides, right before deleting: the ledger
# says they matched once; this says they still match now.
VSHA_L=(); VSHA_R=()
[ "${#CANDIDATES[@]}" -gt 0 ] && verify_batch "${CANDIDATES[@]}"
DELETE=()
for name in "${CANDIDATES[@]+"${CANDIDATES[@]}"}"; do
  l=${VSHA_L[$name]:-}; r=${VSHA_R[$name]:-}
  if [ -n "$l" ] && [ "$l" = "$r" ] && [ "$l" = "${LEDGER_OK[$name]#*$'\t'}" ]; then
    DELETE+=("$ARCHIVE_ROOT/$name")
  else
    HELD=$((HELD+1))
    fail "$name failed its pre-prune re-check (local='${l:-?}' offsite='${r:-?}') -- held"
  fi
done

PRUNED=0; CHANGED=0; : > "$WORK/deleted_all"
if [ "$DRY_RUN" = 1 ]; then
  note "would prune ${#DELETE[@]} file(s), each re-confirmed offsite by size+sha256"
elif [ "${#DELETE[@]}" -gt 0 ]; then
  for ((i=0; i<${#DELETE[@]}; i+=128)); do
    batch=("${DELETE[@]:i:128}")
    # GNU find rechecks file type and the SAME retention predicate just before
    # unlinking; a refreshed file or a replacement symlink is held.
    # maxdepth=0 forbids traversing replacements.
    if ! $SUDO find "${batch[@]}" -maxdepth 0 -type f -mtime "+$KEEP_DAYS" -delete -print0 > "$WORK/deleted" 2>/dev/null; then
      fail "confirmed aged-file batch deletion failed -- inspect partial progress"
      break
    fi
    deleted=$(tr -cd '\0' < "$WORK/deleted" | wc -c)
    cat "$WORK/deleted" >> "$WORK/deleted_all"
    PRUNED=$((PRUNED+deleted)); CHANGED=$((CHANGED+${#batch[@]}-deleted))
  done
  # Forget what is gone so the ledger tracks only what is on the primary.
  while IFS= read -r -d '' path; do
    gone=${path##*/}; unset "LSIZE[$gone]"
  done < "$WORK/deleted_all"
  write_ledger
fi
note "pruned=$PRUNED held=$HELD changed=$CHANGED (each pruned file re-confirmed offsite by size+sha256)"
exit "$RC"
