#!/bin/bash
# =====================================================================
# Restore the CUSTOMER AGENT database — the actual case files.
#
#   bash scripts/restore-agent.sh latest
#   bash scripts/restore-agent.sh /path/to/backups/YYYY-MM-DD_HHMMSS
#   bash scripts/restore-agent.sh --from-dr /path/to/osint-DR-YYYY-MM-DD_HHMMSS.tar.gz
#   bash scripts/restore-agent.sh /path/to/YYYY-MM-DD_HHMMSS.tar.gz.gpg   # Off-site, verschluesselt
#
# ## Why this exists as its own script
#
# `scripts/backup.sh` captures the agent database; this script restores it.
# A restore procedure that only exists as prose in the docs has to be found
# and typed correctly while the case files are gone — a restore path that
# only exists as documentation is a restore path nobody has tested.
#
# `restore.sh` deliberately does NOT do this. It restores the operator
# side, and in operator mode the data server is not on that
# machine at all. Folding the two together would make the operator's
# restore script reach for a database it has no business touching.
#
# DESTRUCTIVE: replaces the agent database. Asks first, and takes a safety
# dump of the CURRENT state before it does — restoring the wrong backup is
# a mistake people make exactly once, at three in the morning.
# =====================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/osint-backups}"
CONTAINER="${AGENT_PG_CONTAINER:-oof-agent-postgres-1}"
SRC="${1:-}"
DUMP=""
WORK=""
trap '[[ -n "$WORK" ]] && rm -rf "$WORK"' EXIT

usage() {
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}
[[ -n "$SRC" ]] || usage

docker ps --format '{{.Names}}' | grep -qx "$CONTAINER" || {
    echo "FEHLER: Container '$CONTAINER' laeuft nicht." >&2
    echo "        All-in-one:  cd data-agent && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d" >&2
    exit 1; }

# ---- Quelle aufloesen -----------------------------------------------
if [[ "$SRC" == "--from-dr" ]]; then
    ARCHIVE="${2:-}"
    [[ -f "$ARCHIVE" ]] || { echo "FEHLER: DR-Archiv nicht gefunden: $ARCHIVE" >&2; exit 1; }
    WORK="$(mktemp -d)"
    echo ">>> Fallakten aus dem DR-Archiv auspacken (nur der Dump, nicht das ganze Paket)"
    tar xzf "$ARCHIVE" -C "$WORK" --wildcards '*/data/agent.sql.gz'
    DUMP="$(find "$WORK" -name agent.sql.gz | head -1)"
    [[ -n "$DUMP" ]] || { echo "FEHLER: Das Archiv enthaelt keine agent.sql.gz." >&2; exit 1; }
elif [[ -f "$SRC" && ( "$SRC" == *.tar.gz.gpg || "$SRC" == *.tar.gz ) ]]; then
    # Verschluesselte Off-site-Tagessicherung. Es wird NUR
    # die agent.sql.gz herausgeholt — der Rest des Archivs geht diesen
    # Wiederherstellungsweg nichts an, genau wie beim DR-Pfad darueber.
    WORK="$(mktemp -d)"
    chmod 700 "$WORK"
    if [[ "$SRC" == *.gpg ]]; then
        command -v gpg >/dev/null 2>&1 || { echo "FEHLER: $SRC ist verschluesselt, aber gpg fehlt." >&2; exit 1; }
        echo ">>> Archiv entschluesseln"
        if [[ -n "${OFFSITE_GPG_PASSPHRASE_FILE:-}" ]]; then
            gpg --batch --yes --passphrase-file "$OFFSITE_GPG_PASSPHRASE_FILE" \
                -o "$WORK/backup.tar.gz" --decrypt "$SRC" \
                || { echo "FEHLER: Entschluesselung fehlgeschlagen — falsche Passphrasendatei? Es wurde nichts veraendert." >&2; exit 1; }
        else
            gpg --batch --yes -o "$WORK/backup.tar.gz" --decrypt "$SRC" \
                || { echo "FEHLER: Entschluesselung fehlgeschlagen — liegt der private Schluessel im Schluesselbund dieser Maschine? Es wurde nichts veraendert." >&2; exit 1; }
        fi
        tar xzf "$WORK/backup.tar.gz" -C "$WORK" --wildcards '*/agent.sql.gz'
        rm -f "$WORK/backup.tar.gz"
    else
        tar xzf "$SRC" -C "$WORK" --wildcards '*/agent.sql.gz'
    fi
    DUMP="$(find "$WORK" -name agent.sql.gz | head -1)"
    [[ -n "$DUMP" ]] || { echo "FEHLER: Das Archiv enthaelt keine agent.sql.gz." >&2; exit 1; }
else
    if [[ "$SRC" == "latest" ]]; then
        SRC=$(ls -1dt "$BACKUP_ROOT"/2*_* 2>/dev/null | head -1)
        [[ -n "$SRC" ]] || { echo "FEHLER: Keine Sicherungen unter $BACKUP_ROOT" >&2; exit 1; }
    fi
    [[ -d "$SRC" ]] || { echo "FEHLER: Kein Verzeichnis: $SRC" >&2; exit 1; }
    DUMP="$SRC/agent.sql.gz"
    [[ -f "$DUMP" ]] || { echo "FEHLER: $DUMP fehlt. Diese Sicherung enthaelt keine Fallakten." >&2; exit 1; }
fi

gzip -t "$DUMP" 2>/dev/null || { echo "FEHLER: $DUMP ist kein lesbares gzip-Archiv." >&2; exit 1; }

echo "Quelle:    $DUMP  ($(du -h "$DUMP" | cut -f1))"
BEFORE=$(docker exec "$CONTAINER" psql -U agent -d agent -tAc \
    "select count(*) from entities" 2>/dev/null || echo "?")
echo "Aktuell:   $BEFORE Entitaeten in der laufenden Datenbank"
echo
echo "Das ERSETZT die Fallakten des Kunden."
if [[ "${CONFIRM:-}" != "1" ]]; then
    read -r -p "Zum Fortfahren 'restore' eingeben: " ans
    [[ "$ans" == "restore" ]] || { echo "Abgebrochen."; exit 1; }
fi

# ---- Sicherheitsnetz: der JETZIGE Stand, bevor er verschwindet -------
SAFETY="$HOME/agent-pre-restore-$(date +%Y%m%d-%H%M%S).sql.gz"
echo ">>> Sicherheitskopie des aktuellen Standes: $SAFETY"
docker exec "$CONTAINER" pg_dumpall -U agent | gzip > "$SAFETY"
[[ $(stat -c%s "$SAFETY") -gt 1000 ]] || {
    echo "FEHLER: Die Sicherheitskopie ist verdaechtig klein — nichts wurde veraendert." >&2
    exit 1; }
echo "    $(du -h "$SAFETY" | cut -f1) gesichert."

# ---- Einspielen ------------------------------------------------------
# pg_dumpall schreibt CREATE, nie DROP. Ueber eine lebende Datenbank
# gespielt stellt es NICHTS wieder her: CREATE scheitert als "existiert
# bereits", und jedes COPY trifft dann die alte Tabelle und scheitert am
# Primaerschluessel. Seit dem Backup geloeschte Zeilen blieben geloescht,
# danach hinzugefuegte ueberlebten — ein stiller Leerlauf, der wie ein
# gelungener Restore aussieht. Dieselbe Falle wie in restore.sh.
echo ">>> Datenbank 'agent' verwerfen und neu anlegen"
docker exec "$CONTAINER" psql -U agent -d postgres -v ON_ERROR_STOP=0 -q <<SQL >/dev/null 2>&1
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = 'agent' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS agent;
CREATE DATABASE agent OWNER agent;
SQL

echo ">>> Einspielen"
gunzip -c "$DUMP" | docker exec -i "$CONTAINER" \
    psql -U agent -d postgres -v ON_ERROR_STOP=0 >/dev/null 2>&1

# ---- Gegenprobe ------------------------------------------------------
AFTER=$(docker exec "$CONTAINER" psql -U agent -d agent -tAc \
    "select count(*) from entities" 2>/dev/null || echo 0)
CASES=$(docker exec "$CONTAINER" psql -U agent -d agent -tAc \
    "select count(*) from cases" 2>/dev/null || echo 0)
EDGES=$(docker exec "$CONTAINER" psql -U agent -d agent -tAc \
    "select count(*) from edges" 2>/dev/null || echo 0)

if [[ "${AFTER:-0}" -lt 1 ]]; then
    echo "FEHLER: Nach dem Einspielen sind 0 Entitaeten da — der Restore ist FEHLGESCHLAGEN." >&2
    echo "        Der vorherige Stand liegt unveraendert in: $SAFETY" >&2
    echo "        Zurueck damit:  gunzip -c '$SAFETY' | docker exec -i $CONTAINER psql -U agent -d postgres" >&2
    exit 1
fi

echo
echo "=== fertig ==="
echo "  Faelle:      $CASES"
echo "  Entitaeten:  $AFTER  (vorher: $BEFORE)"
echo "  Kanten:      $EDGES"
echo
echo "Der vorherige Stand liegt weiterhin in: $SAFETY"
echo "Erst loeschen, wenn der wiederhergestellte Stand geprueft ist."
echo
echo "Hinweis: der Agent-Container haelt Verbindungen zur alten Datenbank."
echo "Neu starten, damit er sauber verbindet:"
echo "  docker restart oof-agent-agent-1"
