#!/bin/bash
# =====================================================================
# OOF — Data Server Update (customer side)
#
#     cd /opt/oof-agent && sudo ./update.sh
#     sudo ./update.sh --yes      (no questions, e.g. from cron)
#     sudo ./update.sh --check    (look only, change nothing)
#
# Why this is more than "docker compose pull"
# -------------------------------------------
# The previous version of this script was three lines with three silent
# holes:
#
#   * It pulled only the IMAGE. A changed compose file — a new environment
#     variable, a new service — never arrived. The new program ran against
#     the old wiring.
#   * It never said what changes, or whether you were current. "Did the
#     update work?" had no answer.
#   * It started a possibly broken image with no way back.
#
# So: compare versions, back up, verify checksums, start, wait for health
# — and roll back automatically if it does not come up.
#
# Your investigation data is not touched. What gets updated is the program
# and its wiring; the database keeps its contents and migrates its own
# schema at startup.
# =====================================================================
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/oof-agent}"
BACKUP_DIR="$INSTALL_DIR/backups/update-$(date -u +%Y%m%d-%H%M%S)"
ASSUME_YES=0
CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y)  ASSUME_YES=1 ;;
        --check)   CHECK_ONLY=1 ;;
        --help|-h) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'; C_CYAN=$'\033[1;36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_BLUE=''; C_GREEN=''
    C_YELLOW=''; C_RED=''; C_CYAN=''
fi
GUIDE_STEP=0; GUIDE_TOTAL=6
banner() {
    printf '\n%s╔══════════════════════════════════════════════════════════════════╗%s\n' "$C_BLUE" "$C_RESET"
    printf '%s║%s %-64s %s║%s\n' "$C_BLUE" "$C_BOLD" "$1" "$C_BLUE" "$C_RESET"
    [[ -n "${2:-}" ]] && printf '%s║%s %-64s %s║%s\n' "$C_BLUE" "$C_DIM" "$2" "$C_BLUE" "$C_RESET"
    printf '%s╚══════════════════════════════════════════════════════════════════╝%s\n' "$C_BLUE" "$C_RESET"
}
step() { GUIDE_STEP=$((GUIDE_STEP+1))
    printf '\n%s──[ Step %d/%d ]── %s%s%s\n' "$C_CYAN" "$GUIDE_STEP" "$GUIDE_TOTAL" "$C_BOLD" "$1" "$C_RESET"; }
info() { printf '   %s\n' "$*"; }
note() { printf '   %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()   { printf '   %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '   %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '\n   %s✗ STOPPED%s %s\n\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

jq_get() { python3 -c "
import json,sys
try: d=json.loads(sys.stdin.read() or '{}')
except Exception: d={}
for k in '$1'.split('.'):
    d = d.get(k, {}) if isinstance(d, dict) else {}
print(d if isinstance(d,str) else (json.dumps(d) if d else ''))"; }

banner "OOF — Data Server Update"

[[ $EUID -eq 0 ]] || fail "Please run as root:  sudo ./update.sh"
cd "$INSTALL_DIR" 2>/dev/null || fail "$INSTALL_DIR not found — is the data server installed here?"
[[ -f .env ]] || fail "$INSTALL_DIR/.env is missing — not a complete installation."
# shellcheck disable=SC1091
set -a; source .env; set +a
[[ -n "${FRAMEWORK_URL:-}" ]] || fail "FRAMEWORK_URL is missing from .env. Add it:
          echo 'FRAMEWORK_URL=https://<framework-host>' >> $INSTALL_DIR/.env"

# =====================================================================
step "Comparing versions"
# =====================================================================
LOCAL_VERSION="$(cat .installed-version.json 2>/dev/null | jq_get version || true)"
[[ -n "$LOCAL_VERSION" ]] || LOCAL_VERSION="unknown"
FW_K=""; [[ "${FRAMEWORK_INSECURE:-0}" == "1" ]] && FW_K="-k"
REMOTE="$(curl -sf $FW_K --max-time 20 "$FRAMEWORK_URL/agent/version.json" || echo '')"
[[ -n "$REMOTE" ]] || fail "Version manifest unreachable:
          $FRAMEWORK_URL/agent/version.json
          Does this server reach the framework? Is it running?"
REMOTE_VERSION="$(jq_get version <<<"$REMOTE")"
REMOTE_IMAGE="$(jq_get agent_image <<<"$REMOTE")"
REMOTE_NOTES="$(jq_get notes <<<"$REMOTE")"
REMOTE_DATE="$(jq_get released_at <<<"$REMOTE")"

printf '   %-20s %s\n' "Installed:" "$LOCAL_VERSION"
printf '   %-20s %s   %s\n' "Available:" "$REMOTE_VERSION" "${C_DIM}(${REMOTE_DATE})${C_RESET}"
[[ -n "$REMOTE_NOTES" ]] && printf '   %-20s %s\n' "Change:" "$REMOTE_NOTES"

if [[ "$LOCAL_VERSION" == "$REMOTE_VERSION" ]]; then
    ok "Already up to date."
    [[ $CHECK_ONLY -eq 1 ]] && exit 0
    if [[ $ASSUME_YES -eq 0 ]]; then
        printf '   %s?%s Re-deploy anyway (repair)? [y/N]: ' "$C_YELLOW" "$C_RESET"
        read -r a; [[ "$a" =~ ^[yYjJ]$ ]] || exit 0
    else
        exit 0
    fi
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
    printf '\n   %sAn update is available.%s  Install it with:  sudo ./update.sh\n\n' "$C_YELLOW" "$C_RESET"
    exit 0
fi

if [[ $ASSUME_YES -eq 0 ]]; then
    printf '   %s?%s Update to %s? [Y/n]: ' "$C_YELLOW" "$C_RESET" "$REMOTE_VERSION"
    read -r a; a="${a:-Y}"; [[ "$a" =~ ^[yYjJ]$ ]] || fail "Aborted. Nothing was changed."
fi

# =====================================================================
step "Backing up (before anything changes)"
# =====================================================================
mkdir -p "$BACKUP_DIR"
cp -a .env "$BACKUP_DIR/.env"
cp -a docker-compose.yml "$BACKUP_DIR/docker-compose.yml"
[[ -f Caddyfile ]] && cp -a Caddyfile "$BACKUP_DIR/Caddyfile"
[[ -f .installed-version.json ]] && cp -a .installed-version.json "$BACKUP_DIR/"
if docker compose ps postgres 2>/dev/null | grep -q Up; then
    info "Dumping the database …"
    docker compose exec -T postgres pg_dump -U agent agent 2>/dev/null | gzip > "$BACKUP_DIR/agent.sql.gz" \
        || warn "Database dump failed — continuing, but without a safety net."
    if [[ -s "$BACKUP_DIR/agent.sql.gz" ]]; then
        ok "Case files backed up ($(du -h "$BACKUP_DIR/agent.sql.gz" | cut -f1))"
    fi
else
    warn "Database not running — no data backup possible."
fi
PREV_IMAGE="$(grep -E '^\s*image:.*oof-data-agent' docker-compose.yml | head -1 | awk '{print $2}')"
ok "Backup written to $BACKUP_DIR"

# =====================================================================
step "Fetching the new files and verifying checksums"
# =====================================================================
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for f in docker-compose.yml postgres-init.sh Caddyfile.template keycloak/realm-template.json update.sh backup.sh; do
    mkdir -p "$TMP/$(dirname "$f")"
    curl -sf $FW_K --max-time 60 "$FRAMEWORK_URL/agent/$f" -o "$TMP/$f" \
        || fail "Could not download $f. Nothing was changed."
    WANT="$(python3 -c "
import json,sys
print(json.loads(sys.stdin.read()).get('files',{}).get('$f',''))" <<<"$REMOTE")"
    GOT="$(sha256sum "$TMP/$f" | cut -d' ' -f1)"
    if [[ -n "$WANT" && "$WANT" != "$GOT" ]]; then
        fail "Checksum of $f does not match the manifest.
          NOTHING was changed. Please contact the operator."
    fi
    printf '   %s✓%s %-34s %s\n' "$C_GREEN" "$C_RESET" "$f" "${WANT:+checksum verified}"
done

# Re-render the Caddyfile from the (possibly new) template — otherwise a
# changed TLS configuration sits unused and nobody notices.
if [[ -n "${KC_HOSTNAME:-}" ]]; then
    if [[ "${TLS_MODE:-letsencrypt}" == "internal" ]]; then
        CADDY_GLOBAL="default_sni $KC_HOSTNAME"; CADDY_TLS="tls internal"
    else
        CADDY_GLOBAL="email ${ACME_EMAIL:-}"; CADDY_TLS=""
    fi
    sed -e "s|__PUBLIC_HOST__|$KC_HOSTNAME|g" -e "s|__GLOBAL_OPTIONS__|$CADDY_GLOBAL|" \
        -e "s|__TLS_DIRECTIVE__|$CADDY_TLS|" -e "s|__HTTPS_PORT__|${PROXY_HTTPS_PORT:-443}|g" \
        "$TMP/Caddyfile.template" > "$TMP/Caddyfile"
fi

# Adopt. `.env` and the imported realm stay untouched: they hold the
# secrets and the login realm that already exists.
for f in docker-compose.yml postgres-init.sh Caddyfile.template keycloak/realm-template.json update.sh backup.sh; do
    mkdir -p "$(dirname "$f")"; cp -f "$TMP/$f" "$f"
done
[[ -f "$TMP/Caddyfile" ]] && cp -f "$TMP/Caddyfile" Caddyfile
chmod +x postgres-init.sh update.sh backup.sh
ok "Program files adopted"

# =====================================================================
step "Starting the new version"
# =====================================================================
# The manifest says how the image is delivered. In tarball mode a
# `docker compose pull` would reach for a registry that does not exist,
# and the `|| true` would swallow it — leaving the old image running while
# every file around it says the update succeeded.
DELIVERY="$(python3 -c "
import json,sys
try: print(json.loads(sys.stdin.read()).get('delivery','registry'))
except Exception: print('registry')" <<<"$REMOTE" 2>/dev/null || echo registry)"
TARBALL="$(python3 -c "
import json,sys
try: print(json.loads(sys.stdin.read()).get('agent_tarball','') or '')
except Exception: print('')" <<<"$REMOTE" 2>/dev/null || echo '')"

if [[ "$DELIVERY" == "tarball" && -n "$TARBALL" ]]; then
    info "Downloading the program image ($TARBALL) …"
    curl -fsSL $FW_K --max-time 1800 "$FRAMEWORK_URL/agent/$TARBALL" -o "$TMP/$TARBALL" \
        || fail "Could not download the program image. Nothing was changed."
    WANT="$(python3 -c "
import json,sys
print(json.loads(sys.stdin.read()).get('files',{}).get('$TARBALL',''))" <<<"$REMOTE")"
    GOT="$(sha256sum "$TMP/$TARBALL" | cut -d' ' -f1)"
    if [[ -n "$WANT" && "$WANT" != "$GOT" ]]; then
        fail "Checksum of the program image does not match the manifest.
          NOTHING was changed. Please contact the operator."
    fi
    printf '   %s✓%s %-34s %s\n' "$C_GREEN" "$C_RESET" "$TARBALL" "checksum verified"
    # `docker load` ADDS an image, it never removes one. The previous
    # image therefore stays on disk under its own tag, which is what makes
    # the rollback below more than a hope.
    gunzip -c "$TMP/$TARBALL" | docker load 2>&1 | sed 's/^/     /' \
        || fail "The program image could not be loaded. Nothing was changed."
    ok "New program image loaded"
else
    docker compose pull -q 2>&1 | sed 's/^/     /' || true
fi
docker compose up -d --quiet-pull 2>&1 | sed "s/^/     /"
info "Waiting for the data server to report healthy (up to 2 minutes) …"
HEALTHY=no
AGENT_PORT_EFF="${AGENT_PORT:-9000}"
for _ in $(seq 1 24); do
    if curl -fsS --max-time 5 "http://127.0.0.1:${AGENT_PORT_EFF}/health" 2>/dev/null | grep -q ok; then
        HEALTHY=yes; break
    fi
    sleep 5
done

# =====================================================================
step "Verifying — and rolling back on failure"
# =====================================================================
if [[ "$HEALTHY" == "yes" ]]; then
    ok "Data server reports healthy"
    for svc in postgres keycloak proxy; do
        if docker compose ps "$svc" 2>/dev/null | grep -q Up; then
            printf '   %s✓%s %s running\n' "$C_GREEN" "$C_RESET" "$svc"
        else
            printf '   %s!%s %s NOT running\n' "$C_YELLOW" "$C_RESET" "$svc"
        fi
    done
    echo "$REMOTE" > .installed-version.json
    printf '\n%s══ Updated to %s ══%s\n\n' "$C_GREEN" "$REMOTE_VERSION" "$C_RESET"
    info "Backup of this run: $BACKUP_DIR"
    note "It can be deleted once the system has been stable for a few days."
    # Housekeeping: keep the ten most recent update backups.
    ls -1dt "$INSTALL_DIR"/backups/update-* 2>/dev/null | tail -n +11 | xargs -r rm -rf
    echo
else
    warn "The data server does not report healthy after the update."
    info "Rolling back to the previous state automatically …"
    # Restoring the previous compose file restores the previous image
    # reference with it. In tarball mode that image is still on disk —
    # `docker load` adds, it does not replace — so this actually rolls
    # back rather than restarting the same broken version.
    cp -f "$BACKUP_DIR/docker-compose.yml" docker-compose.yml
    [[ -f "$BACKUP_DIR/Caddyfile" ]] && cp -f "$BACKUP_DIR/Caddyfile" Caddyfile
    docker compose up -d 2>&1 | sed 's/^/     /'
    BACK=no
    for _ in $(seq 1 24); do
        if curl -fsS --max-time 5 "http://127.0.0.1:${AGENT_PORT_EFF}/health" 2>/dev/null | grep -q ok; then
            BACK=yes; break
        fi
        sleep 5
    done
    if [[ "$BACK" == "yes" ]]; then
        printf '\n%s══ Rolled back — the previous version is running again ══%s\n\n' "$C_YELLOW" "$C_RESET"
        info "Previous image: ${PREV_IMAGE:-unknown}"
        info "Please contact the operator and include this log:"
        note "  cd $INSTALL_DIR && docker compose logs --tail 100 agent"
        exit 1
    fi
    printf '\n%s══ Rollback failed as well ══%s\n\n' "$C_RED" "$C_RESET"
    info "The backup is at: $BACKUP_DIR"
    info "Restore the database by hand:"
    note "  cd $INSTALL_DIR"
    note "  gunzip -c $BACKUP_DIR/agent.sql.gz | docker compose exec -T postgres psql -U agent -d agent"
    info "Please contact the operator immediately."
    exit 1
fi
