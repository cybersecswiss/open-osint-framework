#!/bin/bash
# =====================================================================
# OOF — Data Server Backup (customer side)
#
#     cd /opt/oof-agent && sudo ./backup.sh
#
# Dumps the whole database: the case files AND the login realm (both live
# in the same Postgres). This is the ONLY copy of that data — the
# operator has none.
#
# Retention: the 30 most recent backups.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p backups
TS="$(date +%Y%m%d-%H%M%S)"
OUT="backups/agent-$TS.sql.gz"

docker compose exec -T postgres pg_dumpall -U agent | gzip > "$OUT"

# Two checks, not one. A file can be large and still unreadable — and an
# unreadable backup is discovered exactly when it is needed.
if [[ ! -s "$OUT" ]] || [[ $(stat -c%s "$OUT") -lt 1000 ]]; then
    echo "ERROR: $OUT is suspiciously small — the backup is incomplete." >&2
    exit 1
fi
if ! gzip -t "$OUT" 2>/dev/null; then
    echo "ERROR: $OUT is not readable." >&2
    exit 1
fi

echo "Backup: $OUT  ($(du -h "$OUT" | cut -f1))"

REMOVED=$(ls -t backups/agent-*.sql.gz 2>/dev/null | tail -n +31 | wc -l)
ls -t backups/agent-*.sql.gz 2>/dev/null | tail -n +31 | xargs -r rm -f
[[ "$REMOVED" -gt 0 ]] && echo "Older backups removed: $REMOVED"

echo
echo "!  This backup sits on the SAME server as the data."
echo "   Against a disk failure only a copy elsewhere helps:"
echo "     scp $(pwd)/$OUT <destination>:"
