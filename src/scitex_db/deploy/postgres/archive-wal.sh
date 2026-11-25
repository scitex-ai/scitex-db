#!/bin/sh
# archive_command for the fleet primary: copy one WAL segment into the archive
# so that a PARTIAL copy can never sit under the segment's real name.
#
#   archive_command = '/usr/local/bin/scitex-pg-archive-wal "%p" "%f" /var/lib/postgresql/wal-archive'
#
# WHY THIS REPLACES `test ! -f DEST && cp SRC DEST` (incident 2026-11-24/25,
# scitex-nas-03). The disk filled while `cp` was writing segment 7D...CF. cp
# died with ENOSPC and left a TRUNCATED file under the final name. Every retry
# then ran `test ! -f DEST`, found that file, and exited 1. The archiver could
# never succeed again, so WAL piled up in pg_wal until a human intervened. The
# offsite sync then saw the truncated file's NAME and counted it as safe.
#
# The contract (PostgreSQL docs, "Setting Up WAL Archiving"):
#   - exit 0 ONLY when the segment is durably archived;
#   - never overwrite an existing archived file;
#   - an already-archived IDENTICAL file is success (a crash after the copy but
#     before the archiver recorded it makes the server ask again).
#
# How this meets it:
#   1. DEST exists      -> exit 0 if byte-identical to SRC, else fail LOUDLY.
#   2. copy to a hidden temp name in the same directory, fsync the temp file,
#      and compare it with SRC byte for byte;
#   3. publish with a HARD LINK. link(2) is atomic and fails if DEST appeared
#      meanwhile, so it is a rename that can never clobber (rename(2) itself
#      would silently replace DEST). The temp name is then removed;
#   4. fsync the directory so the new name survives a power cut.
# Any failure removes the temp file and exits non-zero, so ENOSPC leaves
# nothing behind that could block the retry.
#
# POSIX sh plus coreutils/diffutils only: it runs inside the postgres image
# (Debian trixie), not on the host.
set -u

PROG=scitex-pg-archive-wal
TMP=

die() {
  echo "$PROG: FATAL: $*" >&2
  exit 1
}

cleanup() {
  if [ -n "$TMP" ]; then rm -f -- "$TMP"; fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

[ "$#" -eq 3 ] || die "usage: $PROG <%p source> <%f name> <archive dir>"
SRC=$1
NAME=$2
DIR=$3

case "$NAME" in
  '' | . | .. | .* | */*) die "refusing segment name '$NAME' (empty, hidden, or contains '/')" ;;
esac
[ -f "$SRC" ] || die "source '$SRC' is not a regular file"
[ -d "$DIR" ] || die "archive directory '$DIR' does not exist"

DEST=$DIR/$NAME

size_of() {
  wc -c < "$1" 2>/dev/null | tr -d ' '
}

already_archived() {
  # Byte-identical: success. Anything else: refuse, and say exactly what differs.
  if cmp -s -- "$SRC" "$DEST"; then
    echo "$PROG: $NAME already archived and byte-identical; nothing to do" >&2
    exit 0
  fi
  die "$DEST already exists and DIFFERS from $SRC" \
    "(archived $(size_of "$DEST") bytes, source $(size_of "$SRC") bytes)." \
    "Refusing to overwrite. Inspect it; if the archived copy is a truncated" \
    "leftover, move it aside (do not delete it) and the archiver will retry."
}

if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  already_archived
fi

# A previous attempt killed mid-copy can leave a temp file. It was never
# published, so removing it is safe, and it would otherwise hold disk space.
for stale in "$DIR"/."$NAME".partial.*; do
  if [ -f "$stale" ]; then rm -f -- "$stale"; fi
done

TMP=$DIR/.$NAME.partial.$$
cp -- "$SRC" "$TMP" || die "copy of $NAME to $TMP failed (disk full?); nothing was published"
sync -- "$TMP" || die "fsync of $TMP failed; nothing was published"
cmp -s -- "$SRC" "$TMP" || die "copy of $NAME differs from its source after writing; nothing was published"

if ! ln -- "$TMP" "$DEST"; then
  # DEST appeared between the check above and the link: judge it like any
  # existing file. The temp file is removed on exit either way.
  if [ -e "$DEST" ]; then
    already_archived
  fi
  die "could not publish $TMP as $DEST"
fi
rm -f -- "$TMP"
TMP=
sync -- "$DIR" || die "fsync of archive directory $DIR failed after publishing $NAME"
exit 0
