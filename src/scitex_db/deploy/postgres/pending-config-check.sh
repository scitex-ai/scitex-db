#!/bin/bash
# Does this host's RUNNING postgres match its postgresql.conf?
#
# A long-lived process holds the world as it was at boot. Editing the config
# does not change the process, nothing warns, and everything looks healthy —
# the divergence materialises at the NEXT RESTART, caused by whoever happens to
# restart it: an autoheal, a reboot, or someone deploying an unrelated unit
# change. Three of this fleet's four replicas were in that state on 2026-08-27
# with an unapplied listen_addresses, found only because a rollout paused to
# read the files.
#
# WHY listen_addresses SPECIFICALLY: it is restart-only (no reload applies it)
# and it decides who can reach the database, so an unnoticed pending value
# changes network exposure at an unchosen moment. Same idea extends to any
# restart-only setting; start with the one that changes reachability.
#
# CONTRACT
#   exit 0   file and process agree (or nothing to compare)
#   exit 1   DIVERGENT — the next restart will change behaviour
#   exit 78  could not measure (EX_CONFIG) — never reported as agreement,
#            because the failure mode here IS invisibility
set -uo pipefail

DATADIR="${SCITEX_PG_DATADIR:-$HOME/.scitex/pg/18/main}"
PORT="${SCITEX_PG_PORT:-55432}"
SUDO="${SCITEX_PG_SUDO:-/usr/bin/sudo -n}"
CONF="$DATADIR/postgresql.conf"
HOSTN=$(hostname -s)

$SUDO test -r "$CONF" 2>/dev/null || { echo "$HOSTN: CANNOT READ $CONF — measured NOTHING"; exit 78; }

# LAST occurrence wins in postgresql.conf. `head -1` answers a different
# question and will happen to be right often enough to mislead.
WANT=$($SUDO grep -h "^listen_addresses" "$CONF" 2>/dev/null | tail -1 \
       | sed "s/.*=[[:space:]]*//; s/#.*//; s/[[:space:]]*$//; s/^'\(.*\)'$/\1/")
[ -n "$WANT" ] || { echo "$HOSTN: no listen_addresses in $CONF — measured NOTHING"; exit 78; }

BOUND=$(ss -ltn 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {sub(/:[0-9]+$/,"",$4); print $4}' | sort -u | paste -sd, -)
[ -n "$BOUND" ] || { echo "$HOSTN: nothing listening on $PORT — postgres down, not a config verdict"; exit 78; }

# Compare as SETS: order and formatting differ between the two sources, and a
# textual diff would cry wolf on every host.
norm(){ tr ',' '\n' <<< "$1" | sed 's/[[:space:]]//g' | grep -v '^$' | sort -u | paste -sd, -; }
W=$(norm "$WANT"); B=$(norm "$BOUND")

if [ "$W" = "$B" ]; then
  echo "$HOSTN: OK — file and process agree ($B)"
  exit 0
fi
echo "$HOSTN: DIVERGENT — the next restart WILL change what this database listens on"
echo "  postgresql.conf asks for : $W"
echo "  the running postmaster has: $B"
echo "  listen_addresses is restart-only; a reload will not apply it."
echo "  Decide and apply deliberately, or reconcile the file to the running value."
exit 1
