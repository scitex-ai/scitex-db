#!/usr/bin/env bash
# inspect_host_pg.sh — READ-ONLY inventory of the host's PostgreSQL.
#
# Answers "is the host PG (the scitex-hub WSL leftover on :5432) empty?"
# without changing anything. Prints, per non-template database, the number of
# public tables and the top live-row tables. Size alone is misleading — an
# empty table still occupies a few MB — so this reports table and row counts,
# which are the definitive signal.
#
# Connects over the local socket as the invoking OS user (ywatanabe, which is a
# superuser role) via peer auth: no sudo, no password. Nothing here writes,
# drops, or upgrades. The upgrade itself is a separate, destructive,
# operator-decided step and is deliberately NOT in this script.
#
# Usage (on the host):
#   bash /home/ywatanabe/proj/scitex-db/GITIGNORED/inspect_host_pg.sh
set -euo pipefail

echo "=== version ==="
psql -d postgres -Atc "SELECT version();"

echo
echo "=== database sizes ==="
psql -d postgres -c "SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size
                     FROM pg_database ORDER BY pg_database_size(datname) DESC;"

echo
echo "=== per-database table/row inventory (the emptiness verdict) ==="
dbs=$(psql -d postgres -Atc \
  "SELECT datname FROM pg_database WHERE datistemplate=false AND datname<>'postgres';")
for db in $dbs; do
  t=$(psql -d "$db" -Atc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
  echo "--- $db : $t public table(s) ---"
  psql -d "$db" -c \
    "SELECT relname, n_live_tup FROM pg_stat_user_tables
     WHERE n_live_tup>0 ORDER BY n_live_tup DESC LIMIT 10;"
done

echo
echo "=== interpretation ==="
echo "If every database shows 0 public table(s) and no rows above, the host PG"
echo "is effectively empty and safe to drop/reinstall as PG16 (path A in the DM)."
echo "A database with real rows means choose path B (pg_upgradecluster) or keep it."
# EOF
