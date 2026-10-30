#!/bin/bash
# Dump postgres + tar volumes.
#
#   BACKUP_ROOT   where to write (default /var/backups/oof).
#                 Override to a writable dir when you can't sudo, e.g.
#                 BACKUP_ROOT=$HOME/osint-backups bash scripts/backup.sh
#   RETENTION_DAYS  delete dated sub-dirs older than this (default 30).
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

# A backup directory holds `agent.sql.gz` — every case, every entity, every
# edge the customer ever produced — plus the Keycloak volume. It was created
# world-readable (dir 775, files 644/664) because nothing here ever set a
# umask, and on a shared host that is a full data disclosure to any local
# account. The off-site copies were always 0700/0600; only the source was
# open. Restrictive umask for everything this script creates itself; the
# volume tars need an explicit chmod because a throwaway container brings
# its OWN umask, not ours.
umask 077

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/oof}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
BACKUP_DIR="$BACKUP_ROOT/$(date +%Y-%m-%d_%H%M%S)"

# Compose's volume-name prefix. MUST be derived the same way here and in
# restore.sh, or a restore silently writes to volumes this never backed up.
# A host may also run an unrelated stack with its own `n8n_data` volume
# next to `oof_n8n_data` — getting the prefix wrong reaches into someone
# else's data.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(pwd)")}"

if ! mkdir -p "$BACKUP_DIR" 2>/dev/null; then
    sudo mkdir -p "$BACKUP_DIR"
    sudo chown "$USER" "$BACKUP_DIR"
fi
chmod 700 "$BACKUP_DIR"

echo "Backing up to $BACKUP_DIR"

docker compose exec -T postgres \
    pg_dumpall -U osint | gzip > "$BACKUP_DIR/postgres.sql.gz"

# The customer agent's database — the ONLY place the actual case data lives
# (the framework's own entities table is the unused fallback path). It is
# dumped daily here, not only in the weekly DR archive, so no more than a
# day of investigative work can be lost.
#
# Addressed by direct `docker exec` on the container name rather than
# `docker compose` from data-agent/: that directory needs the dev overlay
# (-f docker-compose.local.yml) to resolve correctly, and a backup must not
# depend on remembering a flag. Same pattern make-dr-archive.sh already uses.
#
# Soft failure on purpose: in operator mode the data server is not on this
# host at all, and there its own data-agent/backup.sh is responsible.
if docker ps --format '{{.Names}}' | grep -q '^oof-agent-postgres-1$'; then
    docker exec oof-agent-postgres-1 pg_dumpall -U agent \
        | gzip > "$BACKUP_DIR/agent.sql.gz"
    if [[ $(stat -c%s "$BACKUP_DIR/agent.sql.gz") -lt 1000 ]]; then
        echo "ERROR: agent.sql.gz is suspiciously small — case data not backed up" >&2
        exit 1
    fi
else
    echo "    (no local data-agent container — case data not captured here)"
fi

# Volume tars via a throwaway container: works without sudo (the docker
# daemon has the access) and FAILS LOUDLY — a silent host-side tar once
# produced empty 20-byte archives for weeks.
# messenger_media + telegram_audit hold evidentiary data (downloaded
# Telegram media, hash-chained audit log) — never skip those.
# audit_anchors: the external anchors are what PROVE the audit chain was
# not tampered with. If they lived only in the weekly DR archive, chain and
# anchors could drift apart by up to seven days — exactly the window in
# which a dispute about the chain would arise.
# forums_cache: not evidentiary, but rebuilding it
# is a ~10 minute crawl, and it costs almost nothing to carry.
# NOT tarred on purpose: postgres_data (covered by the SQL dump above),
# redis (cache/locks only), prometheus/grafana (metrics history;
# dashboards are provisioned from monitoring/ in the code bundle).
for vol in keycloak_data n8n_data messenger_media telegram_audit audit_anchors forums_cache; do
    if ! docker volume inspect "${PROJECT}_${vol}" >/dev/null 2>&1; then
        echo "ERROR: volume ${PROJECT}_${vol} does not exist — wrong project prefix?" >&2
        exit 1
    fi
    # Der Container MUSS root bleiben — sonst liest er die Volume-Inhalte
    # gar nicht erst. Er bringt dann aber seine eigene Maske mit, und die
    # Tars gehoerten root:root 0644; ein `chmod` von aussen scheitert daran
    # still, weil dieser Nutzer sie nicht besitzt.
    #
    # 🔴 Nur `umask 077` zu setzen reicht NICHT und macht es schlimmer:
    # dann liegen dort root:root 0600 — Dateien, die dieses Skript in
    # seiner eigenen Lesbarkeitspruefung nicht mehr oeffnen kann und die
    # ein Off-site-Abgleich spaeter nicht mehr uebertragen koennte.
    #
    # Richtig ist deshalb beides: restriktive Maske UND die Uebereignung
    # an den aufrufenden Nutzer, im selben Aufruf.
    docker run --rm -v "${PROJECT}_${vol}:/vol:ro" \
        -v "$BACKUP_DIR:/out" alpine \
        sh -c "umask 077 && tar czf '/out/${vol%_data}.tgz' -C /vol . && chown $(id -u):$(id -g) '/out/${vol%_data}.tgz'"
done

# Guertel und Hosentraeger fuer alles, was diesem Nutzer gehoert. Die
# root-eigenen Tars sind durch die Container-Maske oben schon 0600; hier
# scheitert ein chmod auf sie und das ist in Ordnung — das Verzeichnis ist
# 0700, also kommt ohnehin niemand hinein.
chmod 600 "$BACKUP_DIR"/* 2>/dev/null || true

# Nachweis statt Hoffnung: nach dem Lauf darf keine Datei weltlesbar sein.
LOOSE=$(find "$BACKUP_DIR" -type f -perm -o=r | wc -l)
if [[ "$LOOSE" != "0" ]]; then
    echo "WARNUNG: $LOOSE Datei(en) in $BACKUP_DIR sind weltlesbar" >&2
    find "$BACKUP_DIR" -type f -perm -o=r -printf "    %M %p\n" >&2
fi

# Sanity: the DB dump must be non-trivial, every tar must be readable.
# (A tgz of a legitimately EMPTY volume is small but valid — size alone
# is the wrong test for those.)
if [[ $(stat -c%s "$BACKUP_DIR/postgres.sql.gz") -lt 1000 ]]; then
    echo "ERROR: postgres.sql.gz is suspiciously small — backup incomplete" >&2
    exit 1
fi
for f in "$BACKUP_DIR"/*.tgz; do
    if ! tar tzf "$f" >/dev/null 2>&1; then
        echo "ERROR: $f is not a readable archive — backup incomplete" >&2
        exit 1
    fi
done

# Retention: prune dated backup dirs older than RETENTION_DAYS so the
# disk doesn't fill up over time (mirrors data-agent/backup.sh).
if [[ -d "$BACKUP_ROOT" ]]; then
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
        -exec rm -rf {} + 2>/dev/null || true
fi

echo "Done. $(du -sh "$BACKUP_DIR" | cut -f1) used. (retention: ${RETENTION_DAYS}d)"
