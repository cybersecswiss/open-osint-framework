#!/bin/bash
# =============================================================
# Build a single tar.gz containing the full project, ready for FTP
# transfer. Includes the .env (REAL SECRETS) — bundle is sensitive.
#
# Usage:
#   bash scripts/make-bundle.sh                # default: $HOME
#   OUT_DIR=/tmp bash scripts/make-bundle.sh   # custom output dir
#
# Exits with:
#   - tar.gz path
#   - SHA256 sidecar
# =============================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/oof}"
SPECS_DIR="${SPECS_DIR:-}"   # optional extra directory to include
OUT_DIR="${OUT_DIR:-$HOME}"
# Keep the last N bundles (versioned by timestamp); 0 disables rotation.
BUNDLE_RETENTION="${BUNDLE_RETENTION:-8}"

# Timestamp (not just the date) so several bundles on the same day are
# kept as distinct VERSIONS instead of silently overwriting each other.
DATE=$(date +%Y-%m-%d_%H%M%S)
STAGE="$(mktemp -d)/oof-bundle-$DATE"
ARCHIVE="$OUT_DIR/oof-backup-$DATE.tar.gz"

mkdir -p "$STAGE"

echo ">>> staging code from $PROJECT_DIR"
mkdir -p "$STAGE/code"
# NOTE the './' on data and dist. A bare --exclude='data' matches EVERY
# directory of that name at any depth, which silently dropped the forums
# module's committed seed datasets (linkbase_index.json,
# threat_actors.json.gz — the 830k known-actor index) from every bundle. A
# restore from such a bundle rebuilds module-forums without its indexes.
# Only the project-root runtime dirs are meant to be excluded, exactly as
# .gitignore spells it (`/data/`).
tar -C "$PROJECT_DIR" \
    --exclude='./data' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='node_modules' --exclude='./frontend/dist' \
    -cf - . | tar -C "$STAGE/code" -xf -

if [[ -d "$SPECS_DIR/specs" ]]; then
    echo ">>> staging docs"
    cp -r "$SPECS_DIR/specs" "$STAGE/docs-specs"
    cp -r "$SPECS_DIR/plans" "$STAGE/docs-plans"
fi

cat > "$STAGE/RESTORE.txt" <<EOF
OOF — full backup bundle ($DATE)
===============================================

Contents
--------
  code/          contents of $PROJECT_DIR (incl. .env, .git, certs/)
  docs-specs/    design document (if present at bundle time)
  docs-plans/    implementation plans 01..06 (if present)
  RESTORE.txt    this file

SECURITY
--------
SENSITIVE FILES INSIDE:
  code/.env                    real passwords/secrets (chmod 600)
  code/certs/server.key        TLS private key

Do NOT transfer over plain FTP. Use SFTP/SCP/rsync-over-ssh, or
encrypt first:  gpg -c oof-backup-*.tar.gz

Restore on a new server
-----------------------
  tar xzf oof-backup-*.tar.gz
  sudo cp -a oof-bundle-*/code/. /opt/oof/
  sudo chown -R \$USER:\$USER /opt/oof
  cd /opt/oof
  sudo PUBLIC_HOST=<new-ip-or-domain> FORCE_CERT_REGEN=1 bash scripts/setup-server.sh
  bash scripts/configure-keycloak.sh   # optional dev seed

See code/CHANGELOG.md for the build state at bundling time.
EOF

echo ">>> creating archive"
tar czf "$ARCHIVE" -C "$(dirname "$STAGE")" "$(basename "$STAGE")"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
rm -rf "$(dirname "$STAGE")"

# Rotation: keep only the newest $BUNDLE_RETENTION bundles (+ their .sha256)
# so versioned bundles don't fill the disk. Newest are kept.
if [[ "$BUNDLE_RETENTION" -gt 0 ]]; then
    mapfile -t OLD < <(ls -1t "$OUT_DIR"/oof-backup-*.tar.gz 2>/dev/null | tail -n +"$((BUNDLE_RETENTION + 1))")
    for f in "${OLD[@]}"; do
        echo ">>> rotating out old bundle: $(basename "$f")"
        rm -f "$f" "$f.sha256"
    done
fi

echo
echo "=== Bundle ready ==="
ls -la "$ARCHIVE" "$ARCHIVE.sha256"
echo
echo "Sensitive files inside:"
tar tzf "$ARCHIVE" | grep -E '(\.env$|server\.key$)' | sed 's/^/  /'
