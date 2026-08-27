#!/usr/bin/env bash
# Pre-start gate for the fleet card store's PostgreSQL 18 datadir.
#
# WHY THIS EXISTS
#   2026-08-18/19 the fleet card store crash-looped 1222 times and was
#   unreachable for every agent on the host. Three successive FATALs, each
#   masking the next:
#       1. data directory has invalid permissions      (775; PG needs 0700/0750)
#       2. could not open directory "pg_notify"        (No such file or directory)
#       3. could not open directory "pg_logical/snapshots"
#   Every missing path was an EMPTY directory. base/ global/ pg_wal/ survived
#   with all their real data. Something that does not preserve empty
#   directories restored the tree and recreated what it did restore under
#   umask 002. Nothing repaired it and nothing alerted; it spun until a human
#   noticed they could not read their own cards.
#
#   PostgreSQL will not create these itself and will not start without them,
#   so the failure is permanent until repaired by hand. This script makes it
#   self-healing: the same defect now costs one restart, not 1222.
#
# THE REQUIRED SET IS MEASURED, NOT RECALLED
#   REQUIRED_EMPTY_DIRS below was enumerated from a live, healthy PG18 datadir
#   (scitex-compute-02, 2026-08-19) by listing every directory with zero
#   entries. The by-hand repair applied during the incident created 12 of them
#   and MISSED three -- pg_dynshmem, pg_wal/archive_status, pg_wal/summaries --
#   which is exactly the failure mode this script removes.
#
# CONTRACT
#   argv[1]  datadir (default: /home/ywatanabe/.scitex/pg/18/main)
#   exit 0   datadir verified startable (repaired first, if it needed it)
#   exit 69  datadir absent or not a directory        (EX_UNAVAILABLE)
#   exit 78  datadir present but unrepairable         (EX_CONFIG)
#   Declared codes, never bare 1/2: those already mean "generic failure" and
#   "usage error" to every caller, so a renamed or missing verb would
#   impersonate one of ours.
#
# Idempotent. Only ever creates empty directories and tightens the datadir
# mode. Never writes, moves or deletes anything holding data.

set -uo pipefail

readonly EX_OK=0
readonly EX_UNAVAILABLE=69
readonly EX_CONFIG=78

readonly DATADIR="${1:-/home/ywatanabe/.scitex/pg/18/main}"

# Directories PostgreSQL 18 requires to exist but leaves empty in steady state.
# Measured from a healthy datadir -- see header.
readonly REQUIRED_EMPTY_DIRS=(
  base/pgsql_tmp
  pg_commit_ts
  pg_dynshmem
  pg_logical/mappings
  pg_logical/snapshots
  pg_notify
  pg_replslot
  pg_serial
  pg_snapshots
  pg_stat
  pg_stat_tmp
  pg_tblspc
  pg_twophase
  pg_wal/archive_status
  pg_wal/summaries
)

log() { printf '[pg-preflight] %s\n' "$*" >&2; }

die() {
  local code="$1"; shift
  log "FAIL($code): $*"
  exit "$code"
}

# --- 1. the datadir itself must be there -------------------------------------
[[ -e "$DATADIR" ]] || die "$EX_UNAVAILABLE" \
  "datadir does not exist: $DATADIR
   HINT: this is the fleet card store on 55432. Do NOT initdb over it -- that
   would discard the cards. Restore base/ global/ pg_wal/ from the hourly
   snapshot first, then re-run this script to recreate the empty dirs."

[[ -d "$DATADIR" ]] || die "$EX_UNAVAILABLE" \
  "datadir exists but is not a directory: $DATADIR"

# It must be a PostgreSQL datadir, not merely a directory that exists. Adopted
# from the inline gate found on ywata-note-win 2026-08-19 -- a good idea this
# script was missing. Without it, an empty or wrong directory sails through
# every check below (we would happily create 15 empty dirs inside it) and the
# failure surfaces later as something far less obvious than "this is not a
# datadir".
[[ -f "$DATADIR/PG_VERSION" ]] || die "$EX_UNAVAILABLE" \
  "$DATADIR has no PG_VERSION -- this is not a PostgreSQL datadir
   HINT: check the path. Do NOT initdb here on the assumption it is empty; if
   this IS the card store's path then the datadir was lost and must be restored
   from the hourly snapshot, not recreated."

# --- 2. mode must be 0700 or 0750 --------------------------------------------
# PostgreSQL refuses to start on anything looser. A restore under umask 002
# leaves 775, which is the first FATAL in the incident chain.
mode="$(stat -c %a "$DATADIR")" || die "$EX_CONFIG" "cannot stat $DATADIR"
if [[ "$mode" != "700" && "$mode" != "750" ]]; then
  orig_mode="$mode"
  log "datadir mode is $mode; PostgreSQL requires 0700 or 0750 -- tightening to 0700"
  chmod 0700 "$DATADIR" || die "$EX_CONFIG" \
    "cannot chmod 0700 $DATADIR (owner is $(stat -c %U "$DATADIR"), we are $(id -un))
     HINT: run as the datadir's owner, or fix ownership first."
  repaired_mode=1
fi

# --- 3. required empty directories must be there -----------------------------
created=()
for rel in "${REQUIRED_EMPTY_DIRS[@]}"; do
  abs="$DATADIR/$rel"
  if [[ -d "$abs" ]]; then
    continue
  fi
  if [[ -e "$abs" ]]; then
    die "$EX_CONFIG" \
      "$rel exists but is not a directory: $abs
       HINT: PostgreSQL needs a directory here. Inspect it by hand -- this
       script will not delete anything."
  fi
  mkdir -p -m 0700 "$abs" || die "$EX_CONFIG" \
    "cannot create $abs
     HINT: check ownership and free space/inodes on the filesystem holding $DATADIR."
  chmod 0700 "$abs"
  created+=("$rel")
done

# --- 4. verify the end state, do not trust the repair -------------------------
# The whole point of the incident was that an action's exit code was believed
# instead of its result. Re-read what is actually on disk.
mode="$(stat -c %a "$DATADIR")"
[[ "$mode" == "700" || "$mode" == "750" ]] || die "$EX_CONFIG" \
  "post-repair verification failed: datadir mode is still $mode"

missing=()
for rel in "${REQUIRED_EMPTY_DIRS[@]}"; do
  [[ -d "$DATADIR/$rel" ]] || missing+=("$rel")
done
(( ${#missing[@]} == 0 )) || die "$EX_CONFIG" \
  "post-repair verification failed: still missing ${missing[*]}"

# --- 5. report, and RAISE A REPAIR AS AN EVENT --------------------------------
#
# A silently self-healing gate is worse than no gate for the defect UPSTREAM of
# it. scitex-cards (package owner) put it exactly right on the incident card,
# 2026-08-19: "if ExecStartPre fixes it quietly, the 1223rd occurrence looks
# identical to a clean boot and the actual defect -- the restore path -- never
# gets found." The store must still come up, so the repair is not fatal; but it
# files a card, because a datadir does not lose directories on its own.
if (( ${#created[@]} > 0 )) || [[ -n "${repaired_mode:-}" ]]; then
  detail=""
  [[ -n "${repaired_mode:-}" ]] && detail+="  mode was ${orig_mode:-?}, tightened to 0700 (PostgreSQL requires 0700/0750)"$'\n'
  (( ${#created[@]} > 0 )) && detail+="  recreated ${#created[@]} missing empty dir(s): ${created[*]}"$'\n'

  log "REPAIRED datadir $DATADIR"
  printf '%s' "$detail" >&2
  log "  raising this as an alert: the repair succeeded, the RESTORE PATH did not"

  ALERTER=/home/ywatanabe/.scitex/pg/alert_card_store.sh
  if [[ -x "$ALERTER" ]]; then
    # Non-fatal by design: the datadir IS startable now, and refusing to start
    # postgres because we could not raise a card would turn a repaired store
    # into an outage. Failure to alert is itself logged.
    PREFLIGHT_REPAIR_DETAIL="$detail" "$ALERTER" datadir-repaired \
      || log "  WARNING: could not raise the repair alert (exit $?) -- it is in this journal only"
  else
    log "  WARNING: $ALERTER missing -- repair is in this journal only, nobody is paged"
  fi
else
  log "OK $DATADIR (mode $mode, all ${#REQUIRED_EMPTY_DIRS[@]} required dirs present)"
fi

exit "$EX_OK"
