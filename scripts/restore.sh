#!/bin/bash
# =============================================================
# Restore a dated backup produced by scripts/backup.sh
# (postgres dump + named-volume tarballs).
#
#   bash scripts/restore.sh latest              # newest backup under BACKUP_ROOT
#   bash scripts/restore.sh /path/to/YYYY-MM-DD_HHMMSS
#   bash scripts/restore.sh /path/to/YYYY-MM-DD_HHMMSS.tar.gz.gpg   # off-site
#   BACKUP_ROOT=$HOME/osint-backups bash scripts/restore.sh latest
#
# ## Verschluesselte Off-site-Kopien
#
# Wird die Tagessicherung off-site als EIN `.tar.gz.gpg` statt als offener
# Verzeichnisbaum gespiegelt, kann ein solches Archiv hier direkt
# angegeben werden — es wird in ein 0700-Verzeichnis daneben entpackt und
# nach dem Lauf restlos entfernt, auch bei Abbruch.
#
# Beide Formen bleiben lesbar, mit Absicht: nach dem Einschalten der
# Verschluesselung liegen alte Klartext-Verzeichnisse und neue Archive eine
# Weile nebeneinander, und ein Schnitt machte genau die aelteren Staende
# unbrauchbar.
#
# Entschluesselt wird mit dem privaten Schluessel im Schluesselbund dieser
# Maschine oder — bei symmetrischer Verschluesselung — mit
# `OFFSITE_GPG_PASSPHRASE_FILE`. Liegt beides nicht vor, bricht der Lauf
# ab, BEVOR irgendetwas ueberschrieben wird.
#
# DESTRUCTIVE: overwrites the live database and volume contents. Requires
# an explicit confirmation. Stops app containers during the volume swap so
# nothing writes to a half-restored volume, then brings the stack back up.
#
# Volumes restored (must match scripts/backup.sh):
#   keycloak_data, n8n_data, messenger_media, telegram_audit,
#   audit_anchors, forums_cache
# Backups that have no tarball for a volume are skipped for it with a
# note — older backups stay usable.
# postgres_data is NOT tarred — it is rebuilt from postgres.sql.gz.
# =============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/oof}"
# Compose's volume-name prefix — derived exactly as in backup.sh. A host may
# also run an unrelated stack with its own `n8n_data` volume; a wrong
# prefix reaches into someone else's data, so the names are
# verified to exist before anything is overwritten.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$(pwd)")}"
VOLUMES=(keycloak_data n8n_data messenger_media telegram_audit audit_anchors forums_cache)
# Databases owned by this stack; dropped and recreated from the dump.
DATABASES=(osint keycloak n8n license)

# ---- resolve the source dir ----
SRC="${1:-}"
if [[ -z "$SRC" ]]; then
    echo "Usage: $0 <backup-dir|latest>" >&2; exit 2
fi
if [[ "$SRC" == "latest" ]]; then
    SRC=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)
    [[ -n "$SRC" ]] || { echo "No backups found under $BACKUP_ROOT" >&2; exit 1; }
fi

# ---- an archive instead of a directory? (encrypted off-site copies) ----
# Unpacked NEXT TO the archive rather than in /tmp: a daily backup is ~50 MB
# and /tmp is small on some hosts — a restore that dies half-way through
# extraction is the worst possible moment to discover that.
UNPACK_DIR=""
trap '[[ -n "$UNPACK_DIR" && -d "$UNPACK_DIR" ]] && rm -rf "$UNPACK_DIR"' EXIT
if [[ -f "$SRC" ]]; then
    case "$SRC" in
        *.tar.gz.gpg|*.tar.gz) ;;
        *) echo "Not a backup directory, and not a .tar.gz/.tar.gz.gpg archive: $SRC" >&2; exit 1 ;;
    esac
    ARCHIVE="$SRC"
    UNPACK_DIR="$(mktemp -d "${OFFSITE_UNPACK_ROOT:-$(dirname "$ARCHIVE")}/.restore-XXXXXX")"
    chmod 700 "$UNPACK_DIR"
    if [[ "$ARCHIVE" == *.gpg ]]; then
        command -v gpg >/dev/null 2>&1 || { echo "ERROR: $ARCHIVE is encrypted but gpg is not installed" >&2; exit 1; }
        echo ">>> Decrypting $(basename "$ARCHIVE")"
        if [[ -n "${OFFSITE_GPG_PASSPHRASE_FILE:-}" ]]; then
            gpg --batch --yes --passphrase-file "$OFFSITE_GPG_PASSPHRASE_FILE" \
                -o "$UNPACK_DIR/backup.tar.gz" --decrypt "$ARCHIVE" \
                || { echo "ERROR: decryption failed — wrong passphrase file? Nothing was changed." >&2; exit 1; }
        else
            gpg --batch --yes -o "$UNPACK_DIR/backup.tar.gz" --decrypt "$ARCHIVE" \
                || { echo "ERROR: decryption failed — is the private key in this machine's keyring? Nothing was changed." >&2; exit 1; }
        fi
        tar -C "$UNPACK_DIR" -xzf "$UNPACK_DIR/backup.tar.gz"
        rm -f "$UNPACK_DIR/backup.tar.gz"
    else
        tar -C "$UNPACK_DIR" -xzf "$ARCHIVE"
    fi
    SRC=$(find "$UNPACK_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)
    [[ -n "$SRC" ]] || { echo "ERROR: $ARCHIVE contains no backup directory" >&2; exit 1; }
    echo "    unpacked to $SRC"
fi

[[ -d "$SRC" ]] || { echo "Not a directory: $SRC" >&2; exit 1; }
[[ -f "$SRC/postgres.sql.gz" ]] || { echo "Missing $SRC/postgres.sql.gz — not a backup dir" >&2; exit 1; }

# Fail before touching anything if the prefix doesn't match real volumes.
for vol in "${VOLUMES[@]}"; do
    docker volume inspect "${PROJECT}_${vol}" >/dev/null 2>&1 || {
        echo "ERROR: volume ${PROJECT}_${vol} does not exist — wrong project prefix?" >&2
        exit 1; }
done

echo "About to RESTORE from: $SRC"
echo "  → overwrites the live postgres database AND these volumes: ${VOLUMES[*]}"
echo "  → app containers will be stopped and restarted."
if [[ "${CONFIRM:-}" != "1" ]]; then
    read -r -p "Type 'restore' to proceed: " ans
    [[ "$ans" == "restore" ]] || { echo "Aborted."; exit 1; }
fi

# ---- 1. stop every service that writes to postgres or the volumes ----
# (postgres itself stays up for the SQL replay). `license` and the modules
# were missing here: license holds tenant/licence rows and would keep writing
# into a database being replaced. `framework-kc` was listed but is only a
# network alias for `keycloak`, never a service.
echo ">>> stopping app services"
docker compose stop api frontend n8n keycloak license updater 2>/dev/null || true

# ---- 2. restore the database ----
# pg_dumpall writes CREATE, never DROP. Replaying it over live databases
# therefore restores NOTHING: CREATE DATABASE/TABLE fail as "already exists"
# (tolerated by ON_ERROR_STOP=0) and every COPY then hits the OLD table and is
# rejected on primary-key conflicts. Rows deleted since the backup would stay
# deleted, rows added since would survive — a silent no-op that looks like a
# successful restore. So drop the stack's databases first and let the dump
# recreate them.
echo ">>> dropping databases: ${DATABASES[*]}"
for db in "${DATABASES[@]}"; do
    docker compose exec -T postgres psql -U osint -d postgres -v ON_ERROR_STOP=0 -q <<SQL >/dev/null 2>&1
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '${db}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${db};
SQL
done

echo ">>> restoring postgres from postgres.sql.gz"
# Roles already exist and their CREATE ROLE lines will error — tolerated.
gunzip -c "$SRC/postgres.sql.gz" | \
    docker compose exec -T postgres psql -U osint -d postgres -v ON_ERROR_STOP=0 >/dev/null
echo "    database restored."

# Sanity: every database must be back and non-empty, or we just wiped the server.
for db in "${DATABASES[@]}"; do
    n=$(docker compose exec -T postgres psql -U osint -d "$db" -tAc \
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo 0)
    if [[ "${n:-0}" -lt 1 ]]; then
        echo "ERROR: database '$db' has no tables after restore — restore FAILED." >&2
        echo "       The stack is down. Investigate before starting it." >&2
        exit 1
    fi
    echo "    $db: $n tables"
done

# ---- 3. restore each volume (stop-write already guaranteed above) ----
for vol in "${VOLUMES[@]}"; do
    tgz="$SRC/${vol%_data}.tgz"
    if [[ ! -f "$tgz" ]]; then
        echo "    skip $vol (no ${vol%_data}.tgz in backup)"; continue
    fi
    echo ">>> restoring volume $vol from $(basename "$tgz")"
    docker run --rm \
        -v "${PROJECT}_${vol}:/vol" \
        -v "$SRC:/in:ro" alpine \
        sh -c "rm -rf /vol/* /vol/..?* /vol/.[!.]* 2>/dev/null; tar xzf '/in/${vol%_data}.tgz' -C /vol"
done

# ---- 4. bring the stack back ----
echo ">>> starting the stack"
docker compose up -d
# Flush nginx DNS so it re-resolves the freshly (re)started containers.
docker compose exec -T nginx nginx -s reload 2>/dev/null || true

echo "Done. Restored from $SRC. Check the logs and app health."
