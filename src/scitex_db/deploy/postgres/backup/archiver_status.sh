#!/bin/bash
# Report the CURRENT PRIMARY's archiver state as simple key=value lines.
#
# WHY THIS EXISTS: compute-04's wal_sync.sh asks `psql -h 127.0.0.1`, i.e. ITS OWN
# postgres. Since the 2026-08-25 cutover that host is a STANDBY which still reads
# archive_mode='on' from its primary days, so its archive_mode check passed
# truthfully every 15 minutes for 18 hours -- about a server that is not the writer,
# while the real primary archived nothing. compute-04 cannot query the primary
# directly either: nas-03's pg_hba rejects scitex_admin from 100.64.0.1.
#
# So the query runs HERE, on the host that holds the writer, and the caller ssh's in.
# Values are emitted as bare key=value with NO quoting, deliberately: routing SQL
# through ssh -> docker exec -> psql is three quoting layers, and a mis-escaped
# literal returns a parse error that a caller can easily read as data.
#
# NULLs come back as EMPTY STRINGS on purpose. The caller distinguishes empty from
# a number; nothing here fabricates a sentinel that could be mistaken for a value.
set -uo pipefail
CTR=${ARCHIVER_CTR:-scitex-pg18}
Q(){ docker exec "$CTR" psql -U svc_replica -h 127.0.0.1 -p 55432 -d postgres -Atc "$1" 2>/dev/null | tail -1; }

echo "in_recovery=$(Q 'select pg_is_in_recovery()')"
echo "archive_mode=$(Q 'show archive_mode')"
echo "archived_count=$(Q 'select archived_count from pg_stat_archiver')"
echo "failed_count=$(Q 'select failed_count from pg_stat_archiver')"
echo "last_archived_wal=$(Q 'select last_archived_wal from pg_stat_archiver')"
echo "last_failed_wal=$(Q 'select last_failed_wal from pg_stat_archiver')"
echo "age_min=$(Q 'select round(extract(epoch from now()-last_archived_time)/60) from pg_stat_archiver')"
echo "timeline_now=$(Q 'select timeline_id from pg_control_checkpoint()')"
echo "timeline_archived=$(Q 'select substr(last_archived_wal,1,8) from pg_stat_archiver')"
# COUNT INSIDE THE CONTAINER. The archive dir is 700 owned by uid 999, so an `ls`
# as ywatanabe returns permission-denied and `wc -l` counts ZERO -- indistinguishable
# from an empty archive. That false zero fooled me once today already.
echo "archive_files=$(docker exec "$CTR" sh -c 'ls -1 /var/lib/postgresql/wal-archive 2>/dev/null | wc -l' 2>/dev/null | tail -1)"
