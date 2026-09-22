#!/usr/bin/env bash
# upgrade_host_pg_to_latest.sh — upgrade the host PostgreSQL to the latest
# stable major, PRESERVING all data (operator chose "keep").
#
# Must run as root:  sudo bash upgrade_host_pg_to_latest.sh
#
# Safety posture:
#   * A full pg_dumpall backup already exists at
#     GITIGNORED/pg14_backup.sql (taken 2026-07-30). This script takes a
#     second, timestamp-free backup right before touching anything.
#   * pg_upgradecluster COPIES 14's data into the new cluster; it does not
#     delete 14. The old 14 cluster is LEFT IN PLACE (moved to another port)
#     so a failed upgrade is fully recoverable. Dropping 14 is a separate,
#     manual step you run only after confirming the new cluster is good.
#   * Idempotent where it can be: re-adding the repo / re-running apt is safe.
#
# What it does NOT do: it never drops the old cluster and never deletes data.
set -euo pipefail

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "ERROR: run as root:  sudo bash $0" >&2
  exit 2
fi

BACKUP=/home/ywatanabe/proj/scitex-db/GITIGNORED/pg14_backup_preupgrade.sql
echo "=== 0. fresh safety backup -> $BACKUP ==="
sudo -u postgres pg_dumpall > "$BACKUP"
echo "backup: $(wc -c < "$BACKUP") bytes, $(grep -c 'CREATE DATABASE' "$BACKUP") databases"

echo "=== 1. add the official PGDG apt repository (idempotent) ==="
install -d /usr/share/postgresql-common/pgdg
if [ ! -f /etc/apt/trusted.gpg.d/pgdg.gpg ]; then
  curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg
fi
. /etc/os-release
echo "deb https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list
apt-get update

echo "=== 2. pick the latest stable postgresql-NN available ==="
LATEST=$(apt-cache search --names-only '^postgresql-[0-9]+$' \
         | grep -oE 'postgresql-[0-9]+' | grep -oE '[0-9]+' | sort -n | tail -1)
if [ -z "$LATEST" ] || [ "$LATEST" -le 14 ]; then
  echo "ERROR: no newer postgresql than 14 found via apt; aborting." >&2
  exit 1
fi
echo "latest available major: $LATEST"

echo "=== 3. install postgresql-$LATEST ==="
DEBIAN_FRONTEND=noninteractive apt-get install -y "postgresql-$LATEST"

echo "=== 4. upgrade 14/main -> $LATEST, preserving data ==="
# apt creates an empty $LATEST/main on install; remove it so the upgraded
# cluster can take its place (and its port).
if pg_lsclusters -h | awk '{print $1"/"$2}' | grep -qx "$LATEST/main"; then
  pg_dropcluster "$LATEST" main --stop
fi
pg_upgradecluster -v "$LATEST" 14 main

echo "=== 5. result ==="
pg_lsclusters
echo
echo "NEXT (manual, only after you confirm $LATEST/main on :5432 is healthy):"
echo "  sudo pg_dropcluster 14 main    # removes the old 14 cluster"
echo "The old 14 cluster is still present (on a non-5432 port) until you do this,"
echo "and GITIGNORED/pg14_backup.sql + $BACKUP are your restore points."
# EOF
