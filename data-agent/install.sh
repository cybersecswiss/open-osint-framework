#!/bin/bash
# =====================================================================
# OOF — data server setup (customer side)
#
# Run on the organisation's own server as root:
#
#     curl -fsSL https://<framework>/agent/install.sh -o install.sh
#     sudo bash install.sh
#
# (Framework with a self-signed certificate: curl -k … and answer "yes"
#  to the question about the framework's certificate.)
#
# What this sets up, and why it lives on YOUR server
# --------------------------------------------------
# The investigation data does NOT live with the framework operator. It
# lives here: own database, own Keycloak for the organisation's user
# accounts, own TLS certificate. The operator has no administrative
# access to any of it — and therefore cannot reset a password for you.
#
# Safe to re-run: existing secrets are never regenerated.
#
# Unattended (all values as flags, --yes takes every default):
#   sudo bash install.sh --lang en --framework-url https://fw.example.org \
#        --license-key KEY --host data.example.org --email it@example.org \
#        --admin-email admin@example.org --yes
#
# Options:
#   --lang en|de             language of this installer
#   --framework-url URL      address of the framework (operator)
#   --license-key KEY        licence key issued by the operator
#   --host NAME|IP           public address of THIS server
#   --tls letsencrypt|internal
#                            letsencrypt: real certificate, needs a DNS name
#                            and port 80 reachable (default)
#                            internal: self-signed (IP address / LAN / test)
#   --https-port N / --http-port N   (default 443 / 80)
#   --email ADDR             certificate notices (letsencrypt)
#   --admin-user NAME / --admin-email ADDR   first administrator
#   --insecure-framework     accept a self-signed framework certificate
#   --install-dir DIR        default /opt/oof-agent
#   --yes                    unattended: take every default
# =====================================================================
set -euo pipefail
# shellcheck disable=SC2154  # rc is assigned inside the trap string
trap 'rc=$?; printf "\n   \033[1;31m✗ install.sh: unexpected error (exit %s) at line %s: %s\033[0m\n   Re-running is safe: sudo bash install.sh\n\n" "$rc" "$LINENO" "$BASH_COMMAND" >&2' ERR

INSTALL_DIR="${INSTALL_DIR:-/opt/oof-agent}"
CRED_FILE="/root/oof-agent-credentials.txt"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lang)               SW_LANG="$2"; shift 2 ;;
        --framework-url)      FRAMEWORK_URL="$2"; shift 2 ;;
        --license-key)        LICENSE_KEY="$2"; shift 2 ;;
        --host)               KC_HOSTNAME="$2"; shift 2 ;;
        --tls)                TLS_MODE="$2"; shift 2 ;;
        --https-port)         PROXY_HTTPS_PORT="$2"; shift 2 ;;
        --http-port)          PROXY_HTTP_PORT="$2"; shift 2 ;;
        --email)              ACME_EMAIL="$2"; shift 2 ;;
        --admin-user)         INITIAL_ADMIN_USERNAME="$2"; shift 2 ;;
        --admin-email)        INITIAL_ADMIN_EMAIL="$2"; shift 2 ;;
        --insecure-framework) FRAMEWORK_INSECURE=1; shift ;;
        --install-dir)        INSTALL_DIR="$2"; shift 2 ;;
        --yes|-y)             ASSUME_YES=1; shift ;;
        --help|-h)            sed -n '2,45p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# ── Presentation — copy of scripts/lib/guide.sh (this script must run
#    from a single download, so it cannot source anything) ───────────────
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'
    C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'; C_CYAN=$'\033[1;36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_CYAN=''
fi
GUIDE_STEP=0; GUIDE_TOTAL=10; GUIDE_FAILED=0; ASSUME_YES="${ASSUME_YES:-0}"
L() { if [[ "${SW_LANG:-en}" == "de" ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
banner() {
    printf '\n%s══════════════════════════════════════════════════════════════════%s\n' "$C_BLUE" "$C_RESET"
    printf '  %s%s%s\n' "$C_BOLD" "$1" "$C_RESET"
    [[ -n "${2:-}" ]] && printf '  %s%s%s\n' "$C_DIM" "$2" "$C_RESET"
    printf '%s══════════════════════════════════════════════════════════════════%s\n\n' "$C_BLUE" "$C_RESET"
}
step() { GUIDE_STEP=$((GUIDE_STEP+1))
    printf '\n%s──[ %s %d/%d ]── %s%s%s\n' "$C_CYAN" "$(L Step Schritt)" "$GUIDE_STEP" "$GUIDE_TOTAL" "$C_BOLD" "$1" "$C_RESET"; }
info() { printf '   %s\n' "$*"; }
note() { printf '   %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()   { printf '   %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '   %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '\n   %s✗ %s%s %s\n\n' "$C_RED" "$(L STOPPED ABGEBROCHEN)" "$C_RESET" "$*" >&2; exit 1; }
check() { local l="$1"; shift
    if "$@" >/dev/null 2>&1; then printf '   %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$l"
    else printf '   %s✗%s %s\n' "$C_RED" "$C_RESET" "$l"; GUIDE_FAILED=$((GUIDE_FAILED+1)); fi; return 0; }
ask() {
    local __v="$1" p="$2" d="${3:-}" a=""
    if [[ "$ASSUME_YES" == "1" ]]; then
        [[ -n "$d" ]] || fail "$(L "No value for" "Kein Wert für"): $p"
        printf '   %s?%s %s: %s\n' "$C_YELLOW" "$C_RESET" "$p" "$d" >&2; printf -v "$__v" '%s' "$d"; return 0
    fi
    while true; do
        if [[ -n "$d" ]]; then printf '   %s?%s %s [%s]: ' "$C_YELLOW" "$C_RESET" "$p" "$d" >&2
        else printf '   %s?%s %s: ' "$C_YELLOW" "$C_RESET" "$p" >&2; fi
        read -r a || fail "$(L "No input — use --yes with flags for unattended runs." "Keine Eingabe — für unbeaufsichtigte Läufe --yes und Optionen nutzen.")"
        a="${a:-$d}"; [[ -n "$a" ]] && break
        printf '     %s%s%s\n' "$C_RED" "$(L "This one is required." "Diese Angabe ist Pflicht.")" "$C_RESET" >&2
    done
    printf -v "$__v" '%s' "$a"
}
confirm() {
    local p="$1" d="${2:-N}" a="" h; h="$(L "[y/N]" "[j/N]")"; [[ "$d" == "Y" ]] && h="$(L "[Y/n]" "[J/n]")"
    if [[ "$ASSUME_YES" == "1" ]]; then printf '   %s?%s %s %s %s\n' "$C_YELLOW" "$C_RESET" "$p" "$h" "$d" >&2; [[ "$d" == "Y" ]]; return; fi
    printf '   %s?%s %s %s: ' "$C_YELLOW" "$C_RESET" "$p" "$h" >&2
    read -r a || a=""; a="${a:-$d}"; [[ "$a" =~ ^[yYjJ]$ ]]
}
is_ip() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }

if [[ -z "${SW_LANG:-}" ]]; then
    if [[ "$ASSUME_YES" == "1" ]]; then SW_LANG=en
    else
        printf '\n   Language / Sprache  [en/de] (en): '; read -r SW_LANG || SW_LANG=en
        [[ "$SW_LANG" == "de" ]] || SW_LANG=en
    fi
fi

banner "OOF — $(L "Data server setup" "Einrichtung Datenserver")" "$(L "Your investigation data stays on this server" "Ihre Ermittlungsdaten bleiben auf diesem Server")"

# =====================================================================
step "$(L "Checking prerequisites" "Voraussetzungen prüfen")"
# =====================================================================
[[ $EUID -eq 0 ]] || fail "$(L "Please run as root:  sudo bash install.sh" "Bitte als root starten:  sudo bash install.sh")"
command -v apt-get >/dev/null || fail "$(L "This script requires Debian or Ubuntu." "Dieses Skript benötigt Debian oder Ubuntu.")"
# The installer itself needs these (python3 parses the framework's JSON
# answers) — install them before anything else, minimal images lack them.
export DEBIAN_FRONTEND=noninteractive
if ! command -v python3 >/dev/null || ! command -v curl >/dev/null || ! command -v ss >/dev/null || ! command -v openssl >/dev/null; then
    info "$(L "Installing base packages …" "Basispakete werden installiert …")"
    apt-get update -qq >/dev/null 2>&1
    apt-get install -y -qq curl ca-certificates openssl python3 iproute2 >/dev/null 2>&1 \
        || fail "$(L "apt-get install failed (curl, openssl, python3, iproute2)." "apt-get install fehlgeschlagen (curl, openssl, python3, iproute2).")"
fi
RAM_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)
DISK_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
check "$(L "Memory ≥ 4 GB" "Arbeitsspeicher ≥ 4 GB") (${RAM_MB} MB)"       test "$RAM_MB" -ge 3800
check "$(L "Free disk ≥ 20 GB" "Freier Speicher ≥ 20 GB") (${DISK_GB} GB)"  test "$DISK_GB" -ge 20
check "$(L "Internet access" "Internetzugang")"                             bash -c 'curl -sfI --max-time 10 https://deb.debian.org >/dev/null'
if [[ $GUIDE_FAILED -gt 0 ]]; then
    confirm "$(L "Continue anyway?" "Trotzdem fortfahren?")" N || fail "$(L "Aborted." "Abgebrochen.")"
fi
GUIDE_FAILED=0

# =====================================================================
step "$(L "Detecting an existing installation" "Bestehende Installation erkennen")"
# =====================================================================
RESUME=no
if [[ -f "$INSTALL_DIR/.env" ]]; then
    RESUME=yes
    warn "$(L "An installation already exists in" "Es besteht bereits eine Installation in") $INSTALL_DIR."
    note "$(L "Existing passwords are NOT regenerated — only files and containers are refreshed." "Bestehende Passwörter werden NICHT neu erzeugt — nur Dateien und Container werden erneuert.")"
    confirm "$(L "Repair / continue the existing installation?" "Bestehende Installation reparieren / fortsetzen?")" Y \
        || fail "$(L "Aborted. Nothing was changed." "Abgebrochen. Es wurde nichts verändert.")"
    # shellcheck disable=SC1091
    set -a; source "$INSTALL_DIR/.env"; set +a
    ok "$(L "Continuing — secrets left untouched" "Fortsetzung — Geheimnisse bleiben unverändert")"
else
    ok "$(L "Fresh installation" "Neuinstallation")"
fi

# =====================================================================
step "$(L "Collecting details" "Angaben erfassen")"
# =====================================================================
[[ -n "${FRAMEWORK_URL:-}" ]] || ask FRAMEWORK_URL "$(L "Framework address (from the operator, e.g. https://osint.example.org)" "Framework-Adresse (vom Betreiber, z. B. https://osint.example.org)")"
FRAMEWORK_URL="${FRAMEWORK_URL%/}"
[[ "$FRAMEWORK_URL" == https://* ]] || fail "$(L "The framework address must start with https://" "Die Framework-Adresse muss mit https:// beginnen")"
[[ -n "${LICENSE_KEY:-}" ]] || ask LICENSE_KEY "$(L "Licence key (from the operator)" "Lizenzschlüssel (vom Betreiber)")"

FRAMEWORK_INSECURE="${FRAMEWORK_INSECURE:-0}"
CURL_FW=(curl -sf --max-time 30)
if ! curl -sf --max-time 20 -o /dev/null "$FRAMEWORK_URL/agent/version.json"; then
    if curl -skf --max-time 20 -o /dev/null "$FRAMEWORK_URL/agent/version.json"; then
        warn "$(L "The framework answers, but its TLS certificate is not trusted (self-signed?)." "Das Framework antwortet, aber sein TLS-Zertifikat ist nicht vertrauenswürdig (selbstsigniert?).")"
        if [[ "$FRAMEWORK_INSECURE" == "1" ]] || confirm "$(L "Accept it anyway? Only if the operator confirmed the self-signed certificate." "Trotzdem akzeptieren? Nur wenn der Betreiber das selbstsignierte Zertifikat bestätigt hat.")" N; then
            FRAMEWORK_INSECURE=1
        else
            fail "$(L "Framework certificate not accepted." "Framework-Zertifikat nicht akzeptiert.")"
        fi
    else
        fail "$(L "The framework is unreachable at" "Das Framework ist nicht erreichbar unter") $FRAMEWORK_URL/agent/version.json
          $(L "Is the address right, and has the operator published a release (scripts/release.sh)?" "Stimmt die Adresse, und hat der Betreiber ein Release veröffentlicht (scripts/release.sh)?")"
    fi
fi
[[ "$FRAMEWORK_INSECURE" == "1" ]] && CURL_FW=(curl -skf --max-time 30)

DEFAULT_HOST="$(curl -sf --max-time 8 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
[[ -n "${KC_HOSTNAME:-}" ]] || ask KC_HOSTNAME "$(L "Public address of THIS server (DNS name, or IP address)" "Öffentliche Adresse DIESES Servers (DNS-Name oder IP-Adresse)")" "$DEFAULT_HOST"
if [[ -z "${TLS_MODE:-}" ]]; then
    if is_ip "$KC_HOSTNAME"; then
        TLS_MODE=internal
        note "$(L "An IP address gets a self-signed certificate (Let's Encrypt needs a DNS name)." "Eine IP-Adresse erhält ein selbstsigniertes Zertifikat (Let's Encrypt braucht einen DNS-Namen).")"
    elif confirm "$(L "Obtain a Let's Encrypt certificate for" "Let's-Encrypt-Zertifikat beziehen für") $KC_HOSTNAME?" Y; then
        TLS_MODE=letsencrypt
    else
        TLS_MODE=internal
    fi
fi
[[ "$TLS_MODE" == "letsencrypt" || "$TLS_MODE" == "internal" ]] || fail "--tls letsencrypt|internal"
is_ip "$KC_HOSTNAME" && [[ "$TLS_MODE" == "letsencrypt" ]] && fail "$(L "Let's Encrypt needs a DNS name, not an IP address." "Let's Encrypt braucht einen DNS-Namen, keine IP-Adresse.")"

port_busy() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }
PROXY_HTTP_PORT="${PROXY_HTTP_PORT:-80}"
if [[ -z "${PROXY_HTTPS_PORT:-}" ]]; then
    PROXY_HTTPS_PORT=443
    if port_busy 443 && [[ "$RESUME" == "no" ]]; then
        warn "$(L "Port 443 is in use." "Port 443 ist belegt.")"
        ask PROXY_HTTPS_PORT "$(L "HTTPS port for the data server" "HTTPS-Port für den Datenserver")" "8443"
    fi
fi
if [[ "$TLS_MODE" == "letsencrypt" ]]; then
    [[ "$PROXY_HTTP_PORT" == "80" ]] || fail "$(L "Let's Encrypt (HTTP-01) needs port 80." "Let's Encrypt (HTTP-01) braucht Port 80.")"
    [[ "$RESUME" == "yes" ]] || ! port_busy 80 || fail "$(L "Port 80 is in use — Let's Encrypt needs it." "Port 80 ist belegt — Let's Encrypt braucht ihn.")"
    [[ -n "${ACME_EMAIL:-}" ]] || ask ACME_EMAIL "$(L "Email for certificate notices" "E-Mail für Zertifikatsmeldungen")"
else
    ACME_EMAIL="${ACME_EMAIL:-}"
    if port_busy "$PROXY_HTTP_PORT" && [[ "$RESUME" == "no" ]]; then PROXY_HTTP_PORT=8080; port_busy 8080 && PROXY_HTTP_PORT=18080; fi
fi
[[ "$RESUME" == "yes" ]] || ! port_busy "$PROXY_HTTPS_PORT" || fail "$(L "Port is in use:" "Port ist belegt:") $PROXY_HTTPS_PORT"
[[ -n "${INITIAL_ADMIN_USERNAME:-}" ]] || ask INITIAL_ADMIN_USERNAME "$(L "Username of the first administrator" "Benutzername des ersten Administrators")" "admin"
[[ -n "${INITIAL_ADMIN_EMAIL:-}" ]] || ask INITIAL_ADMIN_EMAIL "$(L "Email of that administrator" "E-Mail dieses Administrators")"

PUBLIC_BASE="https://$KC_HOSTNAME"; [[ "$PROXY_HTTPS_PORT" != "443" ]] && PUBLIC_BASE="$PUBLIC_BASE:$PROXY_HTTPS_PORT"

if [[ "$TLS_MODE" == "letsencrypt" ]]; then
    info "$(L "Checking whether" "Prüfe, ob") $KC_HOSTNAME $(L "points at this server …" "auf diesen Server zeigt …")"
    RESOLVED="$(getent hosts "$KC_HOSTNAME" 2>/dev/null | awk '{print $1}' | head -1 || true)"
    if [[ -n "$RESOLVED" && ( " $(hostname -I) " == *" $RESOLVED "* || "$RESOLVED" == "$DEFAULT_HOST" ) ]]; then
        ok "$KC_HOSTNAME → $RESOLVED"
    else
        warn "$KC_HOSTNAME → ${RESOLVED:-$(L "nothing" "nichts")} ($(L "this server" "dieser Server"): $DEFAULT_HOST)"
        confirm "$(L "Continue anyway? Certificate issuance will fail." "Trotzdem fortfahren? Die Zertifikatsausstellung wird scheitern.")" N \
            || fail "$(L "Please create the DNS A record first." "Bitte zuerst den DNS-A-Eintrag anlegen.")"
    fi
fi

# =====================================================================
step "$(L "Validating the licence" "Lizenz prüfen")"
# =====================================================================
VALIDATION="$("${CURL_FW[@]}" "$FRAMEWORK_URL/api/v1/license/validate" -H "X-License-Key: $LICENSE_KEY" 2>/dev/null || echo '{}')"
TENANT="$(python3 -c "import json,sys;d=json.loads(sys.stdin.read() or '{}');print(d.get('tenant','') if d.get('valid') else '')" <<<"$VALIDATION" 2>/dev/null || true)"
[[ -n "$TENANT" ]] || fail "$(L "Licence invalid, or the framework refused it." "Lizenz ungültig, oder das Framework hat sie abgelehnt.")"
ok "$(L "Licence valid — tenant:" "Lizenz gültig — Mandant:") $TENANT"
FRAMEWORK_KEY="$("${CURL_FW[@]}" "$FRAMEWORK_URL/api/v1/license/agent-key" -H "X-License-Key: $LICENSE_KEY" \
    | python3 -c "import json,sys;print(json.load(sys.stdin).get('api_key',''))" 2>/dev/null || true)"
[[ -n "$FRAMEWORK_KEY" ]] || fail "$(L "Could not fetch the access key." "Zugriffsschlüssel konnte nicht abgerufen werden.")"
ok "$(L "Access key received" "Zugriffsschlüssel erhalten")"

# =====================================================================
step "$(L "Preparing the system (Docker)" "System vorbereiten (Docker)")"
# =====================================================================
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates openssl python3 iproute2 cron >/dev/null 2>&1
systemctl enable --now cron >/dev/null 2>&1 || true
if ! command -v docker >/dev/null; then
    info "$(L "Installing Docker …" "Docker wird installiert …")"
    curl -fsSL https://get.docker.com | sh >/dev/null
    systemctl enable --now docker >/dev/null 2>&1 || true
fi
docker compose version >/dev/null 2>&1 || apt-get install -y -qq docker-compose-plugin >/dev/null
docker info >/dev/null 2>&1 || fail "$(L "Docker is installed but not running." "Docker ist installiert, läuft aber nicht.")"
ok "Docker $(docker --version | awk '{print $3}' | tr -d ,)"

# =====================================================================
step "$(L "Downloading and verifying the program files" "Programmdateien laden und prüfen")"
# =====================================================================
mkdir -p "$INSTALL_DIR/keycloak/import"
cd "$INSTALL_DIR"
MANIFEST="$("${CURL_FW[@]}" "$FRAMEWORK_URL/agent/version.json")" || fail "$(L "No release manifest at" "Kein Release-Manifest unter") $FRAMEWORK_URL/agent/version.json"
mf() { python3 -c "import json,sys;d=json.loads(sys.argv[1]);print(eval(sys.argv[2]))" "$MANIFEST" "$1"; }
REL_VERSION="$(mf "d.get('version','unknown')")"
info "$(L "Release:" "Release:") $REL_VERSION"
for f in docker-compose.yml postgres-init.sh Caddyfile.template keycloak/realm-template.json update.sh backup.sh; do
    mkdir -p "$(dirname "$f")"
    "${CURL_FW[@]}" "$FRAMEWORK_URL/agent/$f" -o "$f.new" || fail "$(L "Could not download" "Download fehlgeschlagen:") $f"
    WANT="$(mf "d.get('files',{}).get('$f','')")"
    GOT="$(sha256sum "$f.new" | cut -d' ' -f1)"
    [[ -n "$WANT" && "$WANT" == "$GOT" ]] || { rm -f "$f.new"; fail "$(L "Checksum mismatch:" "Prüfsumme stimmt nicht:") $f"; }
    mv -f "$f.new" "$f"
    printf '   %s✓%s %-34s %s\n' "$C_GREEN" "$C_RESET" "$f" "$(L "checksum verified" "Prüfsumme bestätigt")"
done
chmod +x postgres-init.sh update.sh backup.sh
printf '%s\n' "$MANIFEST" > .installed-version.json

# =====================================================================
step "$(L "Configuration and secrets" "Konfiguration und Geheimnisse")"
# =====================================================================
render_caddy() {
    local global tlsd
    if [[ "$TLS_MODE" == "letsencrypt" ]]; then
        global="email $ACME_EMAIL"; tlsd=""
    else
        global="default_sni $KC_HOSTNAME"; tlsd="tls internal"
    fi
    sed -e "s|__PUBLIC_HOST__|$KC_HOSTNAME|g" -e "s|__GLOBAL_OPTIONS__|$global|" \
        -e "s|__TLS_DIRECTIVE__|$tlsd|" -e "s|__HTTPS_PORT__|$PROXY_HTTPS_PORT|g" \
        Caddyfile.template > Caddyfile
}
render_caddy
ok "$(L "TLS configuration for" "TLS-Konfiguration für") $PUBLIC_BASE ($TLS_MODE)"

KC_HOSTNAME_PORT=-1; [[ "$PROXY_HTTPS_PORT" != "443" ]] && KC_HOSTNAME_PORT="$PROXY_HTTPS_PORT"
setenv() {  # setenv KEY VALUE — update or append in .env, keep everything else
    python3 - "$INSTALL_DIR/.env" "$1" "$2" <<'PY'
import pathlib, sys
p, k, v = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = p.read_text().splitlines() if p.exists() else []
for i, line in enumerate(lines):
    if line.startswith(k + "="):
        lines[i] = f"{k}={v}"; break
else:
    lines.append(f"{k}={v}")
p.write_text("\n".join(lines) + "\n")
PY
}
if [[ "$RESUME" == "no" ]]; then
    POSTGRES_PW="$(openssl rand -hex 24)"
    KC_ADMIN_PW="$(openssl rand -hex 16)"
    INITIAL_ADMIN_PW="$(openssl rand -base64 18 | tr -d '=+/' | head -c 16)Aa1!"
    umask 077
    cat > .env <<EOF
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ) — do not share.
POSTGRES_PASSWORD=$POSTGRES_PW
POSTGRES_KEYCLOAK_PASSWORD=$(openssl rand -hex 24)
DATABASE_URL=postgresql+asyncpg://agent:$POSTGRES_PW@postgres:5432/agent
KC_ADMIN_USER=admin
KC_ADMIN_PASSWORD=$KC_ADMIN_PW
INITIAL_ADMIN_USERNAME=$INITIAL_ADMIN_USERNAME
INITIAL_ADMIN_EMAIL=$INITIAL_ADMIN_EMAIL
AGENT_PORT=9000
KC_PORT=9080
EOF
    sed -e "s|__REALM_NAME__|$TENANT|g" \
        -e "s|__BACKEND_CLIENT_SECRET__|$(openssl rand -hex 32)|g" \
        -e "s|__INITIAL_ADMIN_USERNAME__|$INITIAL_ADMIN_USERNAME|g" \
        -e "s|__INITIAL_ADMIN_EMAIL__|$INITIAL_ADMIN_EMAIL|g" \
        -e "s|__INITIAL_ADMIN_PASSWORD__|$INITIAL_ADMIN_PW|g" \
        -e "s|__FRAMEWORK_FRONTEND_ORIGIN__|$FRAMEWORK_URL|g" \
        keycloak/realm-template.json > keycloak/import/realm.json
    # Holds the first admin's password and a client secret: readable only
    # by the Keycloak container user (uid 1000), not by everybody.
    chown 1000:0 keycloak/import/realm.json; chmod 600 keycloak/import/realm.json
    ok "$(L "Secrets generated, login realm" "Geheimnisse erzeugt, Login-Realm") '$TENANT' $(L "prepared" "vorbereitet")"
else
    KC_ADMIN_PW="$(L "(unchanged — see" "(unverändert — siehe") $CRED_FILE)"
    INITIAL_ADMIN_PW="$KC_ADMIN_PW"
fi
[[ -f keycloak/import/realm.json ]] && { chown 1000:0 keycloak/import/realm.json; chmod 600 keycloak/import/realm.json; }
for kv in "FRAMEWORK_KEY=$FRAMEWORK_KEY" "FRAMEWORK_URL=$FRAMEWORK_URL" "FRAMEWORK_INSECURE=$FRAMEWORK_INSECURE" \
          "KC_HOSTNAME=$KC_HOSTNAME" "KC_HOSTNAME_PORT=$KC_HOSTNAME_PORT" "TLS_MODE=$TLS_MODE" \
          "ACME_EMAIL=$ACME_EMAIL" "PROXY_HTTP_PORT=$PROXY_HTTP_PORT" "PROXY_HTTPS_PORT=$PROXY_HTTPS_PORT" "SW_LANG=$SW_LANG"; do
    setenv "${kv%%=*}" "${kv#*=}"
done
chmod 600 .env
ok ".env $(L "written (root only)" "geschrieben (nur root)")"

# =====================================================================
step "$(L "Starting the services" "Dienste starten")"
# =====================================================================
DELIVERY="$(mf "d.get('delivery','registry')")"
TARBALL="$(mf "d.get('agent_tarball','') or ''")"
IMAGE="$(mf "d.get('agent_image','')")"
if [[ "$DELIVERY" == "tarball" && -n "$TARBALL" ]]; then
    if docker image inspect "$IMAGE" >/dev/null 2>&1; then
        ok "$(L "Image already present:" "Image bereits vorhanden:") $IMAGE"
    else
        info "$(L "Downloading the program image" "Programm-Image wird geladen") ($TARBALL) …"
        "${CURL_FW[@]}" --max-time 1800 "$FRAMEWORK_URL/agent/$TARBALL" -o "$TARBALL" || fail "$(L "Image download failed." "Image-Download fehlgeschlagen.")"
        WANT="$(mf "d.get('files',{}).get('$TARBALL','')")"
        [[ "$(sha256sum "$TARBALL" | cut -d' ' -f1)" == "$WANT" ]] || { rm -f "$TARBALL"; fail "$(L "Image checksum mismatch — nothing installed." "Image-Prüfsumme stimmt nicht — nichts installiert.")"; }
        gunzip -c "$TARBALL" | docker load | sed 's/^/     /'
        rm -f "$TARBALL"
        ok "$(L "Image verified and loaded" "Image geprüft und geladen")"
    fi
else
    docker compose pull -q agent 2>&1 | sed 's/^/     /' || fail "$(L "Could not pull the image" "Image konnte nicht geladen werden"): $IMAGE"
fi
docker compose up -d --quiet-pull >/var/log/oof-agent-up.log 2>&1 \
    || { tail -15 /var/log/oof-agent-up.log | sed 's/^/     /'; fail "docker compose up — /var/log/oof-agent-up.log"; }
ok "$(L "Containers started" "Container gestartet")"
info "$(L "Waiting for the login service (up to 4 minutes) …" "Warte auf den Login-Dienst (bis zu 4 Minuten) …")"
KC_UP=no
for _ in $(seq 1 48); do
    curl -fsS "http://127.0.0.1:9080/auth/realms/$TENANT/.well-known/openid-configuration" >/dev/null 2>&1 && { KC_UP=yes; break; }
    sleep 5
done
[[ "$KC_UP" == "yes" ]] && ok "$(L "Login service ready" "Login-Dienst bereit") (realm $TENANT)" \
    || warn "$(L "Login service not answering yet — logs:" "Login-Dienst antwortet noch nicht — Logs:") docker compose logs keycloak"

# =====================================================================
step "$(L "Scheduling daily backups" "Tägliche Sicherung einplanen")"
# =====================================================================
CRON_LINE="15 2 * * * cd $INSTALL_DIR && ./backup.sh >> $INSTALL_DIR/backups/backup.log 2>&1"
mkdir -p "$INSTALL_DIR/backups"
if grep -Fq "cd $INSTALL_DIR && ./backup.sh" <<<"$(crontab -l 2>/dev/null || true)"; then
    ok "$(L "Daily backup already scheduled" "Tägliche Sicherung bereits eingeplant")"
elif confirm "$(L "Back up every day at 02:15 (30 kept)?" "Jeden Tag um 02:15 sichern (30 werden behalten)?")" Y; then
    if { crontab -l 2>/dev/null || true; echo "$CRON_LINE"; } | crontab - 2>/dev/null; then
        ok "$(L "Scheduled — see: crontab -l" "Eingeplant — siehe: crontab -l")"
    else
        warn "$(L "Could not write the crontab — add it by hand:" "Crontab konnte nicht geschrieben werden — bitte von Hand eintragen:") $CRON_LINE"
    fi
else
    warn "$(L "Skipped. Without backups a disk failure is a total loss." "Übersprungen. Ohne Sicherung ist ein Plattendefekt ein Totalverlust.")"
fi
note "$(L "Backups are written to THIS server — copy" "Sicherungen liegen auf DIESEM Server — kopieren Sie") $INSTALL_DIR/backups/ $(L "elsewhere regularly." "regelmässig an einen anderen Ort.")"

# =====================================================================
step "$(L "Final verification" "Abschlussprüfung")"
# =====================================================================
GUIDE_FAILED=0
check "$(L "Database running" "Datenbank läuft")"            bash -c "docker compose ps postgres | grep -q Up"
check "$(L "Data server answering" "Datenserver antwortet")"  bash -c "curl -fsS http://127.0.0.1:9000/health | grep -q ok"
check "$(L "Login service running" "Login-Dienst läuft")"     bash -c "docker compose ps keycloak | grep -q Up"
check "$(L "TLS proxy running" "TLS-Proxy läuft")"            bash -c "docker compose ps proxy | grep -q Up"
info "$(L "Waiting for HTTPS on" "Warte auf HTTPS unter") $PUBLIC_BASE …"
TLS_OK=no; CK=(curl -fsS --max-time 8); [[ "$TLS_MODE" == "internal" ]] && CK=(curl -kfsS --max-time 8)
for _ in $(seq 1 24); do
    "${CK[@]}" --resolve "$KC_HOSTNAME:$PROXY_HTTPS_PORT:127.0.0.1" "$PUBLIC_BASE/health" >/dev/null 2>&1 && { TLS_OK=yes; break; }
    is_ip "$KC_HOSTNAME" && "${CK[@]}" "$PUBLIC_BASE/health" >/dev/null 2>&1 && { TLS_OK=yes; break; }
    sleep 5
done
if [[ "$TLS_OK" == "yes" ]]; then
    ok "$PUBLIC_BASE/health $(L "answers" "antwortet")"
else
    GUIDE_FAILED=$((GUIDE_FAILED+1))
    warn "$PUBLIC_BASE $(L "is not answering yet." "antwortet noch nicht.")"
    note "$(L "Usual causes: DNS not pointing here, port 80/443 blocked upstream, Let's Encrypt still working." "Übliche Ursachen: DNS zeigt nicht hierher, Port 80/443 vorgelagert gesperrt, Let's Encrypt arbeitet noch.")"
    note "$(L "Logs:" "Logs:")  cd $INSTALL_DIR && docker compose logs proxy"
fi

AGENT_URL="$PUBLIC_BASE"
IDP_URL="$PUBLIC_BASE/auth/realms/$TENANT"
{
    echo "OOF — data server credentials"
    echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)   Release: $REL_VERSION"
    echo
    echo "SEND TO THE OPERATOR (no secrets):"
    echo "  Data server URL : $AGENT_URL"
    echo "  Login URL       : $IDP_URL"
    echo "  Tenant          : $TENANT"
    echo "  TLS             : $TLS_MODE"
    echo
    echo "SECRET — DO NOT SHARE:"
    echo "  Keycloak master administrator (https://.../auth/admin/)"
    echo "    username : admin"
    echo "    password : $KC_ADMIN_PW"
    echo "  First administrator of your organisation"
    echo "    username : $INITIAL_ADMIN_USERNAME"
    echo "    password : $INITIAL_ADMIN_PW   (must be changed at first login)"
    echo
    echo "The operator holds NO copy of these passwords."
} > "$CRED_FILE"
chmod 600 "$CRED_FILE"

if [[ $GUIDE_FAILED -eq 0 ]]; then
    printf '\n%s══ %s ══%s\n' "$C_GREEN" "$(L "Setup complete" "Einrichtung abgeschlossen")" "$C_RESET"
else
    printf '\n%s══ %s — %d %s ══%s\n' "$C_YELLOW" "$(L "Setup complete" "Einrichtung abgeschlossen")" "$GUIDE_FAILED" "$(L "item(s) open" "Punkt(e) offen")" "$C_RESET"
fi
cat <<EOF

 ${C_BOLD}$(L "Send these to the operator" "Diese Angaben an den Betreiber senden")${C_RESET}
   $(L "Data server:" "Datenserver:") $AGENT_URL
   Login:        $IDP_URL
   $(L "Tenant:" "Mandant:")      $TENANT
EOF
[[ "$TLS_MODE" == "internal" ]] && cat <<EOF
   ${C_YELLOW}$(L "Self-signed certificate: the operator must set TLS_VERIFY_AGENT=false and TLS_VERIFY_IDP=false." "Selbstsigniertes Zertifikat: der Betreiber muss TLS_VERIFY_AGENT=false und TLS_VERIFY_IDP=false setzen.")${C_RESET}
EOF
cat <<EOF

 ${C_BOLD}$(L "Credentials" "Zugangsdaten")${C_RESET}
   $CRED_FILE   ($(L "root only — move them into a password manager, then delete the file" "nur root — in einen Passwort-Manager übernehmen, dann Datei löschen"))

 ${C_BOLD}$(L "Day-to-day" "Betrieb")${C_RESET}
   Status:   cd $INSTALL_DIR && docker compose ps
   Logs:     cd $INSTALL_DIR && docker compose logs -f agent
   Update:   cd $INSTALL_DIR && sudo ./update.sh
   Backup:   cd $INSTALL_DIR && sudo ./backup.sh

EOF
