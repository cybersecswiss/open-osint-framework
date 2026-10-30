#!/usr/bin/env bash
# =============================================================
# Disaster-recovery archive: ONE file that can rebuild this whole
# installation on a bare server.
#
# Why this exists next to the other two scripts:
#   make-bundle.sh  → code + secrets, NO database
#   backup.sh       → database + volumes, NO code
# Either one alone cannot restore the system, and the pair is easy to
# get out of sync — which matters more than it sounds: rotate APIKEY_KEK
# and a database dump from before the rotation can no longer be decrypted
# by the .env that ships with it. This packs a matched set, taken at the
# same moment, plus the instructions to put it back.
#
# Usage:  bash scripts/make-dr-archive.sh [ziel-verzeichnis]
# Output: <ziel>/osint-DR-<datum>_<zeit>.tar.gz (+ .sha256)
#
# ⚠️ CONTAINS EVERY SECRET (.env, TLS keys, database contents, the audit
# log). Move it off this machine over SFTP/SCP, or encrypt it first:
#     gpg -c osint-DR-....tar.gz
# =============================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
WORK="$(mktemp -d)"
ROOT="$WORK/osint-DR-$STAMP"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$ROOT/code" "$ROOT/data"

echo ">>> 1/4  copying code, config and history"
# --exclude'd: build output, caches, and EARLIER DR ARCHIVES. Everything
# else goes in on purpose — .git (full commit history), .env (secrets),
# certs/, the telegram session file, and the small dumps under backups/ so a
# crash does not take the project's history with it. ./data is the empty
# runtime dir.
#
# ⚠️ `data-agent/agent-image-*.tar.gz` is excluded for the same reason as an
# earlier DR archive: it is ~150 MB, it is a BUILD OUTPUT of a commit that
# is already in this archive, and scripts/release.sh reproduces it from
# that commit. Carrying it would roughly double every archive (and every
# retained copy of it) to protect nothing that is not already here.
#
# ⚠️ `backups/osint-DR-*.tar.gz` MUST stay excluded. This script used to
# assume it always writes to $HOME and therefore could never contain itself;
# pointed at the project's own backups/ instead, each archive swallows the
# previous one whole and the size doubles with every run. An earlier full archive is a
# snapshot, not project history: it does not belong inside the next one.
tar -C "$PROJECT_DIR" \
    --exclude='./node_modules' --exclude='./frontend/node_modules' \
    --exclude='./frontend/dist' --exclude='./data' \
    --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='./acme-webroot/.well-known' \
    --exclude='./backups/osint-DR-*.tar.gz' \
    --exclude='./backups/osint-DR-*.tar.gz.sha256' \
    --exclude='./data-agent/agent-image-*.tar.gz' \
    -cf - . | tar -C "$ROOT/code" -xf -

# Belt and braces: if the destination IS inside the project, say so. The
# exclude above handles it, but a silent assumption that just got broken
# deserves a line the next person can see.
case "$(readlink -f "$DEST")/" in
    "$(readlink -f "$PROJECT_DIR")"/*)
        echo "    note: writing into the project dir — earlier DR archives excluded" ;;
esac

# Maschinenzustand, der nirgendwo sonst steht: der Crontab dieser Maschine
# (z.B. Sicherung, DR-Archiv, Spiegelung, Cache-Pruning).
# Er faellt sonst durch BEIDE Netze: nicht in git (er liegt nicht im
# Projektverzeichnis) und nicht im Archiv (das nur das Projekt tart). Ohne ihn
# laeuft nach einem Neuaufbau still gar nichts mehr automatisch — und das
# faellt erst auf, wenn man eine Sicherung braucht.
crontab -l > "$ROOT/crontab.txt" 2>/dev/null || echo "(kein Crontab)" > "$ROOT/crontab.txt"
{
    echo "# Maschinenzustand zum Zeitpunkt des Archivs"
    echo "host: $(hostname)   $(date -Is)"
    echo "os:   $(. /etc/os-release; echo "$PRETTY_NAME")   kernel $(uname -r)"
    echo "docker: $(docker --version 2>/dev/null)"
    echo
    echo "## Container"
    docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null
    echo
    echo "## Volumes"
    docker volume ls --format '{{.Name}}' 2>/dev/null
} > "$ROOT/system-inventory.txt" 2>/dev/null || true

echo ">>> 2/4  dumping databases"
docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T postgres \
    pg_dumpall -U osint 2>/dev/null | gzip > "$ROOT/data/framework-all.sql.gz" \
    || { echo "!! framework dump failed" >&2; exit 1; }
# The data server runs as its own compose project; in operator mode it
# would not be here at all, hence the soft failure.
if docker ps --format '{{.Names}}' | grep -q '^oof-agent-postgres-1$'; then
    docker exec oof-agent-postgres-1 pg_dump -U agent agent \
        | gzip > "$ROOT/data/agent.sql.gz"
else
    echo "    (no local data-agent — skipped)"
fi

echo ">>> 3/4  archiving docker volumes"
# postgres_data is deliberately absent — the SQL dump above is the better
# copy of it (portable across Postgres versions). redis_data holds nothing
# but cache and scheduler locks. Everything else that carries state gets
# archived, dashboards and metrics history included.
for vol in keycloak_data n8n_data messenger_media telegram_audit forums_cache \
           audit_anchors grafana_data prometheus_data; do
    full="oof_${vol}"
    docker volume inspect "$full" >/dev/null 2>&1 || continue
    docker run --rm -v "$full":/v -v "$ROOT/data":/out alpine \
        tar czf "/out/volume-${vol}.tgz" -C /v . 2>/dev/null || true
done

cat > "$ROOT/RESTORE.md" <<'RESTORE'
# Wiederherstellung auf einem leeren Server

Dieses Archiv enthält **alles**: Code inklusive Git-Historie, `.env` mit
allen Secrets, TLS-Zertifikate, sämtliche Datenbanken und die Docker-
Volumes (Keycloak, n8n, Audit-Anker, Medien). Es ist in sich stimmig —
Code und Daten stammen aus demselben Moment. Das ist wichtig: ein
Datenbank-Dump von *vor* einer `APIKEY_KEK`-Rotation lässt sich mit einer
`.env` von *nach* der Rotation nicht mehr entschlüsseln.

## Voraussetzungen
Docker + Docker-Compose-Plugin. Sonst nichts.

## Schritte

```bash
tar xzf osint-DR-<datum>.tar.gz
cd osint-DR-<datum>

# 1. Code an seinen Platz
sudo mkdir -p /opt/oof
sudo cp -a code/. /opt/oof/
sudo chown -R "$USER" /opt/oof
cd /opt/oof

# 2. Öffentlichen Namen anpassen, FALLS der Server ein anderer ist
#    (PUBLIC_HOST, PUBLIC_HTTPS_PORT). Bleibt der Name gleich, nichts tun.
#    nano .env

# 3. Infrastruktur hochfahren und Datenbanken leer anlegen lassen
docker compose up -d postgres redis
sleep 20

# 4. Datenbanken einspielen (ERSETZT den Inhalt)
gunzip -c ../data/framework-all.sql.gz | \
  docker compose exec -T postgres psql -U osint -d postgres

# 5. Volumes zurückspielen
for f in ../data/volume-*.tgz; do
  vol="oof_$(basename "$f" .tgz | sed 's/^volume-//')"
  docker volume create "$vol" >/dev/null
  docker run --rm -v "$vol":/v -v "$(cd ../data && pwd)":/in alpine \
    sh -c "cd /v && tar xzf /in/$(basename "$f")"
done

# 6. Rest starten
docker compose up -d
sleep 60
bash scripts/health-check.sh          # muss durchgehend [OK] zeigen
```

## Kunden-Agent (nur wenn er auf demselben Server lief)
```bash
cd /opt/oof/data-agent
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
gunzip -c ../../data/agent.sql.gz | docker exec -i oof-agent-postgres-1 psql -U agent -d agent
```
Im Betreibermodus (Datenserver auf eigenem Server) gehört dieser Teil **nicht** hierher —
der Agent wird dort mit `install.sh` neu aufgesetzt und hat sein eigenes
Backup (`data-agent/backup.sh`).

## Danach prüfen
```bash
# Gespeicherte OSINT-API-Keys müssen entschlüsselbar sein
docker compose exec -T api python -c "import asyncio; from app.services import api_keys; \
  print([r['name'] for r in asyncio.run(api_keys.describe()) if r['is_set']])"

# Audit-Kette muss verifizieren (inkl. der externen Anker aus volume-audit_anchors)
#   → als Tenant-Admin: GET /api/v1/audit/verify

# Agent-Authentifizierung: der Health-Check hat dafür einen eigenen Abschnitt
bash scripts/health-check.sh | tail -5
```

Schlägt die Key-Entschlüsselung fehl, passt `APIKEY_KEK` in der `.env`
nicht zum Dump — dann stammen Code und Daten doch aus verschiedenen
Zeitpunkten (siehe `docs/operations.en.md` → „Secrets rotieren").

## Was NICHT drin ist
Docker-Images. Die werden beim ersten `docker compose up -d` neu gebaut
bzw. gezogen; dafür braucht der Server Internetzugang. Kein Netz beim
Restore? Dann vorher `docker save` der Images mitnehmen.
RESTORE

cat > "$ROOT/INHALT.txt" <<EOF
OOF — Disaster-Recovery-Archiv
Erstellt: $(date -Iseconds)
Host:     $(hostname)
Commit:   $(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo 'kein git')
          $(git -C "$PROJECT_DIR" log -1 --pretty=%s 2>/dev/null || true)

code/     vollständiges Projekt inkl. .git (Historie), .env, certs/
data/     framework-all.sql.gz  — alle Postgres-Datenbanken (osint,
                                   keycloak, n8n, license)
          agent.sql.gz          — Datenbank des Kunden-Agenten (falls lokal)
          volume-*.tgz          — Docker-Volumes
RESTORE.md  Schritt-für-Schritt-Wiederherstellung

ENTHÄLT SECRETS — verschlüsselt übertragen und aufbewahren.
EOF

echo ">>> 4/4  packing"
mkdir -p "$DEST"
OUT="$DEST/osint-DR-$STAMP.tar.gz"
tar -C "$WORK" -czf "$OUT" "osint-DR-$STAMP"
( cd "$DEST" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
chmod 600 "$OUT"

echo
echo "=== fertig ==="
ls -la "$OUT" "$OUT.sha256"
echo
echo "Off-site kopieren, z.B.:"
echo "  scp $OUT <ziel>:"
echo "Oder vorher verschlüsseln:  gpg -c $OUT"
