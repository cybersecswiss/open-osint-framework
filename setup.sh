#!/bin/bash
# =====================================================================
# OOF — guided installation
#
#     sudo ./setup.sh
#
# Two ways to run OOF:
#
#   allinone   Everything on ONE server: the framework (web app, search
#              modules, login) AND the data server that stores the case
#              files. Users log in through the framework's own Keycloak.
#              Right for a single organisation, a team, an evaluation.
#
#   operator   The framework only, for several organisations. Each
#              organisation runs its own data server (data-agent/install.sh)
#              with its own database and its own user directory, so the
#              operator never holds case data. Organisations are created
#              in the operator console /glbadmin.
#
# Safe to re-run: secrets are generated once and kept; a second run
# repairs and updates the installation (`--reconfigure` re-asks the
# address and ports).
#
# Unattended:
#   sudo ./setup.sh --lang en --mode allinone --host 203.0.113.10 \
#        --admin-email admin@example.org --yes
#
# Options:
#   --lang en|de                  language of this installer
#   --mode allinone|operator
#   --host NAME|IP                public address (default: detected IP)
#   --tls selfsigned|letsencrypt  letsencrypt needs a DNS name + port 80
#   --http-port N --https-port N  default 80/443 (8080/8443 if taken)
#   --email ADDR                  operator contact (certificates, notices)
#   --owner-user NAME             product-owner login for /glbadmin (owner)
#   --tenant NAME                 allinone: organisation id (main)
#   --admin-user NAME             allinone: first user (admin)
#   --admin-email ADDR            allinone: that user's email — login is by email
#   --email-domains a.org,b.org   allinone: domains whose users belong here
#   --no-firewall                 leave the firewall alone
#   --skip-datasets               do not download the forum indexes
#   --skip-release                operator: do not publish a data-server release
#   --reconfigure                 ask address/ports/TLS again on a re-run
#   --check                       check the server only, change nothing
#   --yes                         unattended: take every default
# =====================================================================
set -euo pipefail
# shellcheck disable=SC2154  # rc is assigned inside the trap string
trap 'rc=$?; printf "\n   \033[1;31m✗ setup.sh: unexpected error (exit %s) at line %s: %s\033[0m\n   Re-running is safe: sudo ./setup.sh\n\n" "$rc" "$LINENO" "$BASH_COMMAND" >&2' ERR

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
LANG_FROM_ENV="${SW_LANG:-}"
# shellcheck source=scripts/lib/guide.sh
source "$PROJECT_DIR/scripts/lib/guide.sh"

ENV_FILE="$PROJECT_DIR/.env"
STATE_FILE="$PROJECT_DIR/.setup-state"      # non-secret choices of the last run
SECRETS_FILE="$PROJECT_DIR/.setup-secrets"  # generated login passwords (600)
CRED_FILE="/root/oof-credentials.txt"

CHECK_ONLY=0; RECONFIGURE=0; FIREWALL=ask; SKIP_DATASETS=0; SKIP_RELEASE=0
OPT_MODE=""; OPT_HOST=""; OPT_TLS=""; OPT_HTTP=""; OPT_HTTPS=""; OPT_EMAIL=""
OPT_OWNER=""; OPT_TENANT=""; OPT_ADMIN=""; OPT_ADMIN_EMAIL=""; OPT_DOMAINS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lang)          SW_LANG="$2"; LANG_FROM_ENV="$2"; shift 2 ;;
        --mode)          OPT_MODE="$2"; shift 2 ;;
        --host)          OPT_HOST="$2"; shift 2 ;;
        --tls)           OPT_TLS="$2"; shift 2 ;;
        --http-port)     OPT_HTTP="$2"; shift 2 ;;
        --https-port)    OPT_HTTPS="$2"; shift 2 ;;
        --email)         OPT_EMAIL="$2"; shift 2 ;;
        --owner-user)    OPT_OWNER="$2"; shift 2 ;;
        --tenant)        OPT_TENANT="$2"; shift 2 ;;
        --admin-user)    OPT_ADMIN="$2"; shift 2 ;;
        --admin-email)   OPT_ADMIN_EMAIL="$2"; shift 2 ;;
        --email-domains) OPT_DOMAINS="$2"; shift 2 ;;
        --no-firewall)   FIREWALL=no; shift ;;
        --skip-datasets) SKIP_DATASETS=1; shift ;;
        --skip-release)  SKIP_RELEASE=1; shift ;;
        --reconfigure)   RECONFIGURE=1; shift ;;
        --check)         CHECK_ONLY=1; shift ;;
        --yes|-y)        ASSUME_YES=1; shift ;;
        --help|-h)       sed -n '2,48p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1  (see --help)" >&2; exit 2 ;;
    esac
done

# Previous choices (re-run)
PREV_MODE=""; PREV_TENANT=""; PREV_ADMIN=""; PREV_ADMIN_EMAIL=""; PREV_DOMAINS=""
PREV_TLS=""; PREV_OWNER=""; PREV_LANG=""; PREV_FIREWALL=""
# shellcheck disable=SC1090
[[ -f "$STATE_FILE" ]] && source "$STATE_FILE"
[[ -z "$LANG_FROM_ENV" ]] && SW_LANG="$PREV_LANG"
[[ -n "$LANG_FROM_ENV" ]] && SW_LANG="$LANG_FROM_ENV"
if [[ -z "$SW_LANG" ]]; then
    if [[ "$ASSUME_YES" == "1" ]]; then SW_LANG=en
    else
        printf '\n   Language / Sprache  [en/de] (en): '; read -r SW_LANG || SW_LANG=en
    fi
fi
[[ "$SW_LANG" == "de" ]] || SW_LANG=en

envget() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true; }
is_ip() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }
port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }
dc() { docker compose "$@"; }
public_url() { local u="https://$PUBLIC_HOST"; [[ "$PUBLIC_HTTPS_PORT" != "443" ]] && u="$u:$PUBLIC_HTTPS_PORT"; printf '%s' "$u"; }

banner "OOF — $(L "Guided installation" "Geführte Installation")" "Version $(cat VERSION 2>/dev/null || echo '?')"
[[ $CHECK_ONLY -eq 1 ]] && note "$(L "Check mode — nothing will be changed." "Prüfmodus — es wird nichts verändert.")"

GUIDE_TOTAL=12
[[ $CHECK_ONLY -eq 1 ]] && GUIDE_TOTAL=1

# =====================================================================
step "$(L "Checking prerequisites" "Voraussetzungen prüfen")"
# =====================================================================
if [[ $CHECK_ONLY -eq 0 && $EUID -ne 0 ]]; then
    fail "$(L "Please run as root:  sudo ./setup.sh   (check only: ./setup.sh --check)" "Bitte als root starten:  sudo ./setup.sh   (nur prüfen: ./setup.sh --check)")"
fi
command -v apt-get >/dev/null || fail "$(L "Debian or Ubuntu is required." "Debian oder Ubuntu wird benötigt.")"
for f in docker-compose.yml .env.example VERSION keycloak/realm-export.json data-agent/docker-compose.customer.yml scripts/configure-keycloak.sh; do
    [[ -f "$f" ]] || fail "$(L "Missing file — is the repository complete?" "Datei fehlt — ist das Repository vollständig?") $f"
done
if [[ $CHECK_ONLY -eq 0 ]] && { ! command -v python3 >/dev/null || ! command -v curl >/dev/null || ! command -v ss >/dev/null; }; then
    info "$(L "Installing base packages …" "Basispakete werden installiert …")"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates python3 iproute2 openssl >/dev/null 2>&1 || fail "apt-get install failed"
fi
RAM_MB=$(awk '/MemTotal/{printf "%d",$2/1024}' /proc/meminfo)
DISK_GB=$(df -BG --output=avail "$PROJECT_DIR" | tail -1 | tr -dc '0-9')
CPUS=$(nproc)
check "$(L "Memory ≥ 8 GB" "Arbeitsspeicher ≥ 8 GB") (${RAM_MB} MB)"            test "$RAM_MB" -ge 7600
check "$(L "CPU cores ≥ 2" "CPU-Kerne ≥ 2") (${CPUS})"                          test "$CPUS" -ge 2
check "$(L "Free disk ≥ 40 GB" "Freier Speicher ≥ 40 GB") (${DISK_GB} GB)"      test "$DISK_GB" -ge 40
check "$(L "Internet access" "Internetzugang")"                                 bash -c 'curl -sfI --max-time 10 https://deb.debian.org >/dev/null'
check "$(L "CPU architecture x86_64 or arm64" "CPU-Architektur x86_64 oder arm64") ($(uname -m))" bash -c '[[ "$(uname -m)" =~ ^(x86_64|aarch64)$ ]]'
if [[ $CHECK_ONLY -eq 1 ]]; then
    check "Docker"                    command -v docker
    check "Docker Compose"            bash -c 'docker compose version'
    check "$(L "Port 443 free" "Port 443 frei")"  bash -c "! ss -ltnH 'sport = :443' | grep -q ."
    check "$(L "Port 80 free" "Port 80 frei")"    bash -c "! ss -ltnH 'sport = :80' | grep -q ."
    if [[ $GUIDE_FAILED -eq 0 ]]; then summary_ok "$(L "Server is suitable" "Server ist geeignet")"; exit 0; fi
    summary_bad "$GUIDE_FAILED $(L "item(s) to look at (Docker is installed by setup.sh; busy ports get alternatives)" "Punkt(e) zu prüfen (Docker installiert setup.sh selbst; für belegte Ports gibt es Ausweichports)")"
    exit 1
fi
if [[ $GUIDE_FAILED -gt 0 ]]; then
    warn "$GUIDE_FAILED $(L "recommendation(s) not met." "Empfehlung(en) nicht erfüllt.")"
    note "$(L "About 30 containers run. With less than 8 GB modules get killed under load," "Es laufen rund 30 Container. Unter 8 GB werden Module unter Last beendet,")"
    note "$(L "which shows up as missing search results rather than as an error." "was sich als fehlende Suchergebnisse zeigt statt als Fehler.")"
    confirm "$(L "Continue anyway?" "Trotzdem fortfahren?")" N || fail "$(L "Aborted." "Abgebrochen.")"
fi
GUIDE_FAILED=0

# =====================================================================
step "$(L "Collecting details" "Angaben erfassen")"
# =====================================================================
RESUME=no; [[ -f "$ENV_FILE" && -n "$(envget PUBLIC_HOST)" ]] && RESUME=yes
if [[ "$RESUME" == "yes" ]]; then
    warn "$(L "An installation exists — secrets are kept, this run repairs/updates it." "Eine Installation besteht — Geheimnisse bleiben erhalten, dieser Lauf repariert/aktualisiert sie.")"
fi

MODE="${OPT_MODE:-$PREV_MODE}"
if [[ -z "$MODE" ]]; then
    info "$(L "allinone = everything on this server (one organisation, team, evaluation)" "allinone = alles auf diesem Server (eine Organisation, Team, Evaluation)")"
    info "$(L "operator = framework for several organisations, each with its own data server" "operator = Framework für mehrere Organisationen, jede mit eigenem Datenserver")"
    choose MODE "$(L "Installation type" "Installationsart")" allinone allinone operator
fi
[[ "$MODE" == "allinone" || "$MODE" == "operator" ]] || fail "--mode allinone|operator"
[[ -n "$PREV_MODE" && "$PREV_MODE" != "$MODE" ]] && fail "$(L "This server was installed as" "Dieser Server wurde installiert als") '$PREV_MODE'. $(L "Changing the type is not supported." "Ein Wechsel der Art wird nicht unterstützt.")"
ok "$(L "Type:" "Art:") $MODE"

ASK_NET=1
if [[ "$RESUME" == "yes" && $RECONFIGURE -eq 0 && -z "$OPT_HOST$OPT_HTTPS$OPT_HTTP$OPT_TLS" ]]; then
    ASK_NET=0
    PUBLIC_HOST="$(envget PUBLIC_HOST)"; PUBLIC_HTTP_PORT="$(envget PUBLIC_HTTP_PORT)"
    PUBLIC_HTTPS_PORT="$(envget PUBLIC_HTTPS_PORT)"; TLS_MODE="${PREV_TLS:-selfsigned}"
    ADMIN_EMAIL="${OPT_EMAIL:-$(envget ADMIN_EMAIL)}"
    ok "$(L "Address kept:" "Adresse beibehalten:") $(public_url)  (TLS: $TLS_MODE — $(L "change with --reconfigure" "ändern mit --reconfigure"))"
fi
if [[ $ASK_NET -eq 1 ]]; then
    DETECTED="$(curl -sf --max-time 8 https://api.ipify.org 2>/dev/null || true)"
    [[ -n "$DETECTED" ]] || DETECTED="$(hostname -I | awk '{print $1}')"
    PUBLIC_HOST="${OPT_HOST:-}"
    [[ -n "$PUBLIC_HOST" ]] || ask PUBLIC_HOST "$(L "Public address — DNS name or IP address" "Öffentliche Adresse — DNS-Name oder IP-Adresse")" "$(envget PUBLIC_HOST | grep . || echo "$DETECTED")"
    PUBLIC_HOST="${PUBLIC_HOST#https://}"; PUBLIC_HOST="${PUBLIC_HOST%%/*}"
    [[ "$PUBLIC_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || fail "$(L "Not a valid host name or IPv4 address:" "Kein gültiger Hostname / keine IPv4-Adresse:") $PUBLIC_HOST"

    TLS_MODE="${OPT_TLS:-}"
    if [[ -z "$TLS_MODE" ]]; then
        if is_ip "$PUBLIC_HOST"; then
            TLS_MODE=selfsigned
            note "$(L "IP address → self-signed certificate (browsers warn once; Let's Encrypt needs a DNS name)." "IP-Adresse → selbstsigniertes Zertifikat (Browser warnen einmal; Let's Encrypt braucht einen DNS-Namen).")"
        elif confirm "$(L "Obtain a free Let's Encrypt certificate for" "Kostenloses Let's-Encrypt-Zertifikat beziehen für") $PUBLIC_HOST?" Y; then
            TLS_MODE=letsencrypt
        else
            TLS_MODE=selfsigned
        fi
    fi
    [[ "$TLS_MODE" == "selfsigned" || "$TLS_MODE" == "letsencrypt" ]] || fail "--tls selfsigned|letsencrypt"
    is_ip "$PUBLIC_HOST" && [[ "$TLS_MODE" == "letsencrypt" ]] && fail "$(L "Let's Encrypt needs a DNS name." "Let's Encrypt braucht einen DNS-Namen.")"

    # Ports. A port held by our own nginx (re-run) counts as free.
    OWN_PORTS=" $( { dc ps nginx --format '{{.Publishers}}' 2>/dev/null || true; } | { grep -oE ':[0-9]+->' || true; } | tr -d ':->' | tr '\n' ' ') "
    port_ok() { [[ "$OWN_PORTS" == *" $1 "* ]] || ! port_busy "$1"; }
    PUBLIC_HTTPS_PORT="${OPT_HTTPS:-}"
    if [[ -z "$PUBLIC_HTTPS_PORT" ]]; then
        PUBLIC_HTTPS_PORT=443
        if ! port_ok 443; then
            warn "$(L "Port 443 is taken by another program." "Port 443 ist von einem anderen Programm belegt.")"
            ask PUBLIC_HTTPS_PORT "$(L "HTTPS port to use instead" "Stattdessen zu nutzender HTTPS-Port")" 8443
        fi
    fi
    PUBLIC_HTTP_PORT="${OPT_HTTP:-}"
    if [[ -z "$PUBLIC_HTTP_PORT" ]]; then
        PUBLIC_HTTP_PORT=80
        if ! port_ok 80; then
            [[ "$TLS_MODE" == "letsencrypt" ]] && fail "$(L "Port 80 is taken — Let's Encrypt needs it. Free it or use --tls selfsigned." "Port 80 ist belegt — Let's Encrypt braucht ihn. Freigeben oder --tls selfsigned verwenden.")"
            PUBLIC_HTTP_PORT=8080; port_ok 8080 || PUBLIC_HTTP_PORT=18080
            note "$(L "Port 80 is taken — HTTP (redirect only) moves to" "Port 80 ist belegt — HTTP (nur Weiterleitung) weicht aus auf") $PUBLIC_HTTP_PORT"
        fi
    fi
    port_ok "$PUBLIC_HTTPS_PORT" || fail "$(L "Port is taken:" "Port ist belegt:") $PUBLIC_HTTPS_PORT"
    port_ok "$PUBLIC_HTTP_PORT"  || fail "$(L "Port is taken:" "Port ist belegt:") $PUBLIC_HTTP_PORT"
    [[ "$TLS_MODE" == "letsencrypt" && "$PUBLIC_HTTP_PORT" != "80" ]] && fail "$(L "Let's Encrypt (HTTP-01) needs port 80." "Let's Encrypt (HTTP-01) braucht Port 80.")"

    ADMIN_EMAIL="${OPT_EMAIL:-$(envget ADMIN_EMAIL)}"
    if [[ -z "$ADMIN_EMAIL" ]]; then
        if [[ "$TLS_MODE" == "letsencrypt" ]]; then
            ask ADMIN_EMAIL "$(L "Operator email (certificate notices)" "E-Mail des Betreibers (Zertifikatsmeldungen)")"
        else
            ask ADMIN_EMAIL "$(L "Operator email (notices; optional)" "E-Mail des Betreibers (Meldungen; optional)")" "-"
            [[ "$ADMIN_EMAIL" == "-" ]] && ADMIN_EMAIL=""
        fi
    fi
fi

PLATFORM_USER="${OPT_OWNER:-${PREV_OWNER:-}}"
[[ -n "$PLATFORM_USER" ]] || ask PLATFORM_USER "$(L "Login name of the product owner (operator console /glbadmin)" "Login-Name des Product Owners (Betreiberkonsole /glbadmin)")" owner
PLATFORM_EMAIL="${ADMIN_EMAIL:-$PLATFORM_USER@platform.invalid}"

if [[ "$MODE" == "allinone" ]]; then
    TENANT="${OPT_TENANT:-$PREV_TENANT}"
    [[ -n "$TENANT" ]] || ask TENANT "$(L "Short id of your organisation (lowercase, e.g. main)" "Kurz-ID Ihrer Organisation (Kleinbuchstaben, z. B. main)")" main
    [[ "$TENANT" =~ ^[a-z0-9][a-z0-9-]{1,30}$ ]] || fail "$(L "Organisation id: lowercase letters, digits and '-' (2–31)." "Organisations-ID: Kleinbuchstaben, Ziffern und '-' (2–31).")"
    TENANT_ADMIN_USER="${OPT_ADMIN:-$PREV_ADMIN}"
    [[ -n "$TENANT_ADMIN_USER" ]] || ask TENANT_ADMIN_USER "$(L "Login name of the first user (administrator)" "Login-Name des ersten Benutzers (Administrator)")" admin
    TENANT_ADMIN_EMAIL="${OPT_ADMIN_EMAIL:-$PREV_ADMIN_EMAIL}"
    if [[ -z "$TENANT_ADMIN_EMAIL" ]]; then
        note "$(L "Users sign in with their email address; its domain decides the organisation." "Benutzer melden sich mit ihrer E-Mail-Adresse an; deren Domain bestimmt die Organisation.")"
        ask TENANT_ADMIN_EMAIL "$(L "Email of that user" "E-Mail dieses Benutzers")" "${ADMIN_EMAIL:-}"
    fi
    [[ "$TENANT_ADMIN_EMAIL" == *@*.* ]] || fail "$(L "Not an email address:" "Keine E-Mail-Adresse:") $TENANT_ADMIN_EMAIL"
    EMAIL_DOMAINS="${OPT_DOMAINS:-$PREV_DOMAINS}"
    [[ -n "$EMAIL_DOMAINS" ]] || ask EMAIL_DOMAINS "$(L "Email domains of your users (comma-separated)" "E-Mail-Domains Ihrer Benutzer (durch Komma getrennt)")" "${TENANT_ADMIN_EMAIL##*@}"
fi

if [[ "$TLS_MODE" == "letsencrypt" ]]; then
    RESOLVED="$(getent ahostsv4 "$PUBLIC_HOST" 2>/dev/null | awk '{print $1}' | head -1 || true)"
    MYIP="$(curl -sf --max-time 8 https://api.ipify.org 2>/dev/null || true)"
    if [[ -n "$RESOLVED" && ( "$RESOLVED" == "$MYIP" || " $(hostname -I) " == *" $RESOLVED "* ) ]]; then
        ok "$PUBLIC_HOST → $RESOLVED ($(L "this server" "dieser Server"))"
    else
        warn "$PUBLIC_HOST → ${RESOLVED:-?}  ($(L "this server" "dieser Server"): ${MYIP:-?})"
        confirm "$(L "DNS does not point here; the certificate will fail. Continue?" "DNS zeigt nicht hierher; das Zertifikat wird scheitern. Fortfahren?")" N \
            || fail "$(L "Create the DNS A record first, then run setup.sh again." "Zuerst den DNS-A-Eintrag anlegen, dann setup.sh erneut starten.")"
    fi
fi
umask 022
cat > "$STATE_FILE" <<EOF
# Choices of the last setup.sh run (no secrets). Used for re-runs.
PREV_LANG=$SW_LANG
PREV_MODE=$MODE
PREV_TLS=$TLS_MODE
PREV_OWNER=$PLATFORM_USER
PREV_TENANT=${TENANT:-}
PREV_ADMIN=${TENANT_ADMIN_USER:-}
PREV_ADMIN_EMAIL=${TENANT_ADMIN_EMAIL:-}
PREV_DOMAINS=${EMAIL_DOMAINS:-}
EOF
ok "$(L "Address:" "Adresse:") $(public_url)   TLS: $TLS_MODE"

# =====================================================================
step "$(L "Preparing the system" "System vorbereiten")"
# =====================================================================
export DEBIAN_FRONTEND=noninteractive
info "$(L "Installing packages …" "Pakete werden installiert …")"
apt-get update -qq >/dev/null
apt-get install -y -qq ca-certificates curl git jq openssl python3 iproute2 cron gzip >/dev/null 2>&1 || fail "apt-get install failed"
[[ "$TLS_MODE" == "letsencrypt" ]] && { apt-get install -y -qq certbot >/dev/null 2>&1 || fail "apt-get install certbot failed"; }
if ! command -v docker >/dev/null; then
    info "$(L "Installing Docker (get.docker.com) …" "Docker wird installiert (get.docker.com) …")"
    curl -fsSL https://get.docker.com | sh >/dev/null 2>&1 || fail "$(L "Docker installation failed." "Docker-Installation fehlgeschlagen.")"
    systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
fi
docker compose version >/dev/null 2>&1 || apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 || true
docker compose version >/dev/null 2>&1 || fail "$(L "Docker Compose plugin missing." "Docker-Compose-Plugin fehlt.")"
docker info >/dev/null 2>&1 || fail "$(L "Docker is installed but not running (systemctl start docker)." "Docker ist installiert, läuft aber nicht (systemctl start docker).")"
ok "Docker $(docker --version | awk '{print $3}' | tr -d ,), Compose $(docker compose version --short)"
DEPLOY_USER="${SUDO_USER:-root}"
if [[ "$DEPLOY_USER" != "root" ]] && ! id -nG "$DEPLOY_USER" | grep -qw docker; then
    usermod -aG docker "$DEPLOY_USER" && note "$DEPLOY_USER $(L "added to group docker (takes effect at next login)" "zur Gruppe docker hinzugefügt (wirkt ab nächster Anmeldung)")"
fi

# =====================================================================
step "$(L "Firewall" "Firewall")"
# =====================================================================
SSH_PORT="$(ss -ltnpH 2>/dev/null | awk '/sshd/{split($4,a,":"); print a[length(a)]; exit}')"; SSH_PORT="${SSH_PORT:-22}"
[[ "$FIREWALL" == "ask" && -n "$PREV_FIREWALL" && $RECONFIGURE -eq 0 ]] && FIREWALL="kept"
if [[ "$FIREWALL" == "kept" ]]; then
    note "$(L "Unchanged since the last run" "Seit dem letzten Lauf unverändert") ($PREV_FIREWALL; $(L "change with --reconfigure" "ändern mit --reconfigure"))."
    FW_STATE="$PREV_FIREWALL"
elif [[ "$FIREWALL" == "no" ]]; then
    FW_STATE=off
    note "$(L "Skipped (--no-firewall)." "Übersprungen (--no-firewall).")"
elif confirm "$(L "Set up the ufw firewall (open only SSH $SSH_PORT, $PUBLIC_HTTP_PORT, $PUBLIC_HTTPS_PORT)?" "ufw-Firewall einrichten (nur SSH $SSH_PORT, $PUBLIC_HTTP_PORT, $PUBLIC_HTTPS_PORT offen)?")" Y; then
    apt-get install -y -qq ufw >/dev/null 2>&1 || true
    if ufw --force reset >/dev/null 2>&1 && ufw default deny incoming >/dev/null && ufw default allow outgoing >/dev/null \
       && ufw allow "$SSH_PORT/tcp" >/dev/null && ufw allow "$PUBLIC_HTTP_PORT/tcp" >/dev/null \
       && ufw allow "$PUBLIC_HTTPS_PORT/tcp" >/dev/null && ufw --force enable >/dev/null 2>&1; then
        ok "ufw: $SSH_PORT, $PUBLIC_HTTP_PORT, $PUBLIC_HTTPS_PORT"; FW_STATE=ufw
        note "$(L "Note: Docker-published ports bypass ufw — OOF publishes only these two." "Hinweis: von Docker veröffentlichte Ports umgehen ufw — OOF veröffentlicht nur diese zwei.")"
    else
        FW_STATE=off; warn "$(L "ufw could not be configured here (container/VPS without netfilter?) — skipped." "ufw liess sich hier nicht einrichten (Container/VPS ohne Netfilter?) — übersprungen.")"
    fi
else
    FW_STATE=off; note "$(L "Skipped. Ports $PUBLIC_HTTP_PORT and $PUBLIC_HTTPS_PORT must be reachable." "Übersprungen. Die Ports $PUBLIC_HTTP_PORT und $PUBLIC_HTTPS_PORT müssen erreichbar sein.")"
fi

echo "PREV_FIREWALL=${FW_STATE:-off}" >> "$STATE_FILE"

# =====================================================================
step "$(L "Configuration and secrets" "Konfiguration und Geheimnisse")"
# =====================================================================
[[ -f "$ENV_FILE" ]] || { cp .env.example "$ENV_FILE"; chmod 600 "$ENV_FILE"; }
TLS_VERIFY_AGENT="$(envget TLS_VERIFY_AGENT)"; TLS_VERIFY_AGENT="${TLS_VERIFY_AGENT:-true}"
python3 - "$ENV_FILE" "$PROJECT_DIR/.env.example" <<PY
import os, pathlib, secrets, string, sys, uuid
env, example = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
def pw(n=28): return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))
hex32 = lambda: secrets.token_hex(32)
GEN = {
    "POSTGRES_PASSWORD": pw, "POSTGRES_KEYCLOAK_PASSWORD": pw, "POSTGRES_N8N_PASSWORD": pw,
    "POSTGRES_LICENSE_PASSWORD": pw, "REDIS_PASSWORD": pw, "API_SECRET_KEY": hex32,
    "KEYCLOAK_ADMIN_PASSWORD": pw, "KEYCLOAK_CLIENT_SECRET": lambda: str(uuid.uuid4()),
    "PLATFORM_KC_CLIENT_SECRET": lambda: str(uuid.uuid4()), "N8N_PASSWORD": pw,
    "N8N_API_KEY": hex32, "N8N_ENCRYPTION_KEY": lambda: secrets.token_hex(16),
    "LICENSE_SECRET_KEY": hex32, "GRAFANA_PASSWORD": pw, "INTERNAL_KEY": hex32,
    "UPDATER_KEY": hex32, "AUDIT_HMAC_KEY": hex32, "APIKEY_KEK": hex32, "LICENSE_KEK": hex32,
}
SET = {
    "PUBLIC_HOST": "$PUBLIC_HOST", "PUBLIC_SCHEME": "https",
    "PUBLIC_HTTP_PORT": "$PUBLIC_HTTP_PORT", "PUBLIC_HTTPS_PORT": "$PUBLIC_HTTPS_PORT",
    "ADMIN_EMAIL": "$ADMIN_EMAIL", "ENVIRONMENT": "production",
    "AGENT_URL_DEFAULT": "", "TLS_VERIFY_AGENT": "$TLS_VERIFY_AGENT",
    "PUBLIC_ORIGIN": "$(public_url)",
    "KC_HOSTNAME_PORT": "-1" if "$PUBLIC_HTTPS_PORT" == "443" else "$PUBLIC_HTTPS_PORT",
}
lines = env.read_text().splitlines()
keys = {l.partition("=")[0] for l in lines if "=" in l and not l.lstrip().startswith("#")}
# New variables of a newer release: append them from the template.
for l in example.read_text().splitlines():
    if "=" in l and not l.lstrip().startswith("#") and l.partition("=")[0] not in keys:
        lines.append(l); keys.add(l.partition("=")[0])
for k in list(GEN) + list(SET):
    if k not in keys:
        lines.append(f"{k}=")
out, made = [], 0
for l in lines:
    if "=" in l and not l.lstrip().startswith("#"):
        k, _, v = l.partition("=")
        if k in SET:
            l = f"{k}={SET[k]}"
        elif k in GEN and (not v.strip() or v.startswith("changeme")):
            l = f"{k}={GEN[k]()}"; made += 1
    out.append(l)
env.write_text("\n".join(out) + "\n")
os.chmod(env, 0o600)
print(f"   {made} " + ("neue Geheimnisse erzeugt, bestehende behalten" if "$SW_LANG" == "de" else "new secret(s) generated, existing ones kept"))
PY
ok ".env $(L "ready (chmod 600 — never commit it)" "bereit (chmod 600 — niemals einchecken)")"

if [[ "$PUBLIC_HTTPS_PORT" != "443" ]]; then
    printf '# Generated by setup.sh — HTTPS is on port %s\nreturn 301 https://$host:%s$request_uri;\n' \
        "$PUBLIC_HTTPS_PORT" "$PUBLIC_HTTPS_PORT" > nginx/conf.d/https-redirect.inc
else
    rm -f nginx/conf.d/https-redirect.inc
fi
mkdir -p data-agent/dist
[[ -f data-agent/dist/version.json ]] || echo '{"version":"none","files":{}}' > data-agent/dist/version.json

# Login passwords, generated once.
touch "$SECRETS_FILE"; chmod 600 "$SECRETS_FILE"
# shellcheck disable=SC1090
source "$SECRETS_FILE"
genpw() { printf '%sAa1!' "$(openssl rand -base64 24 | tr -d '=+/' | head -c 18)"; }
PLATFORM_PASSWORD="${PLATFORM_PASSWORD:-$(genpw)}"
TENANT_ADMIN_PASSWORD="${TENANT_ADMIN_PASSWORD:-$(genpw)}"
printf 'PLATFORM_PASSWORD=%q\nTENANT_ADMIN_PASSWORD=%q\n' "$PLATFORM_PASSWORD" "$TENANT_ADMIN_PASSWORD" > "$SECRETS_FILE"

# =====================================================================
step "$(L "TLS certificate" "TLS-Zertifikat")"
# =====================================================================
mkdir -p certs acme-webroot/.well-known/acme-challenge
CERT_HOST_OK=no
if [[ -s certs/server.crt ]]; then
    if is_ip "$PUBLIC_HOST"; then
        openssl x509 -in certs/server.crt -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:$PUBLIC_HOST" && CERT_HOST_OK=yes
    else
        openssl x509 -in certs/server.crt -noout -ext subjectAltName 2>/dev/null | grep -q "DNS:$PUBLIC_HOST" && CERT_HOST_OK=yes
    fi
fi
if [[ "$CERT_HOST_OK" == "yes" ]] && openssl x509 -in certs/server.crt -noout -checkend 2592000 >/dev/null; then
    ok "$(L "Existing certificate for" "Bestehendes Zertifikat für") $PUBLIC_HOST $(L "kept" "beibehalten")"
else
    SAN="DNS:$PUBLIC_HOST,DNS:localhost,IP:127.0.0.1"; is_ip "$PUBLIC_HOST" && SAN="IP:$PUBLIC_HOST,DNS:localhost,IP:127.0.0.1"
    DAYS=825; [[ "$TLS_MODE" == "letsencrypt" ]] && DAYS=30
    openssl req -x509 -nodes -newkey rsa:3072 -days "$DAYS" -keyout certs/server.key -out certs/server.crt \
        -subj "/O=OOF/CN=$PUBLIC_HOST" -addext "subjectAltName=$SAN" 2>/dev/null
    chmod 600 certs/server.key; chmod 644 certs/server.crt
    if [[ "$TLS_MODE" == "letsencrypt" ]]; then ok "$(L "Interim certificate (replaced by Let's Encrypt in step 8)" "Übergangszertifikat (wird in Schritt 8 durch Let's Encrypt ersetzt)")"
    else ok "$(L "Self-signed certificate for" "Selbstsigniertes Zertifikat für") $PUBLIC_HOST ($DAYS $(L "days" "Tage"))"; fi
fi

# =====================================================================
step "$(L "Building and starting the stack" "Stack bauen und starten")"
# =====================================================================
info "$(L "First run builds ~20 images — 15 to 40 minutes depending on the server." "Der erste Lauf baut ~20 Images — je nach Server 15 bis 40 Minuten.")"
BUILD_LOG=/var/log/oof-build.log
dc pull -q --ignore-buildable >>"$BUILD_LOG" 2>&1 || dc pull -q --ignore-pull-failures >>"$BUILD_LOG" 2>&1 || true
if ! dc build >>"$BUILD_LOG" 2>&1; then
    tail -25 "$BUILD_LOG" | sed 's/^/     /'
    fail "$(L "Build failed — full log:" "Build fehlgeschlagen — vollständiges Log:") $BUILD_LOG"
fi
ok "$(L "Images built" "Images gebaut") ($(L "log:" "Log:") $BUILD_LOG)"
dc up -d --remove-orphans >>"$BUILD_LOG" 2>&1 || { tail -15 "$BUILD_LOG" | sed 's/^/     /'; fail "docker compose up — $BUILD_LOG"; }
info "$(L "Waiting for the services (up to 5 minutes) …" "Warte auf die Dienste (bis zu 5 Minuten) …")"
URL_LOCAL="https://127.0.0.1:$PUBLIC_HTTPS_PORT"
for _ in $(seq 1 60); do
    curl -skf "$URL_LOCAL/api/v1/health" >/dev/null 2>&1 \
      && curl -skf "$URL_LOCAL/auth/realms/osint/.well-known/openid-configuration" >/dev/null 2>&1 && break
    sleep 5
done
# n8n imports its bundled workflows only once its schema exists, i.e. on
# the second start (see n8n/entrypoint.sh).
dc restart n8n >/dev/null 2>&1 || true
dc up -d >/dev/null 2>&1 || true
curl -skf "$URL_LOCAL/api/v1/health" >/dev/null && ok "$(L "Backend and login service are up" "Backend und Login-Dienst laufen")" \
    || warn "$(L "Backend not answering yet — see: docker compose ps / docker compose logs api" "Backend antwortet noch nicht — siehe: docker compose ps / docker compose logs api")"

# =====================================================================
step "$(L "Let's Encrypt certificate" "Let's-Encrypt-Zertifikat")"
# =====================================================================
if [[ "$TLS_MODE" == "letsencrypt" ]]; then
    if certbot certonly --webroot -w "$PROJECT_DIR/acme-webroot" -d "$PUBLIC_HOST" ${ADMIN_EMAIL:+--email "$ADMIN_EMAIL"} \
            --agree-tos --non-interactive --keep-until-expiring >/var/log/oof-certbot.log 2>&1; then
        HOOK=/etc/letsencrypt/renewal-hooks/deploy/oof.sh
        mkdir -p "$(dirname "$HOOK")"
        cat > "$HOOK" <<HOOK
#!/bin/bash
# Generated by OOF setup.sh — copies a renewed certificate into the stack.
set -e
LE="/etc/letsencrypt/live/$PUBLIC_HOST"
install -m 644 "\$LE/fullchain.pem" "$PROJECT_DIR/certs/server.crt"
install -m 600 "\$LE/privkey.pem"   "$PROJECT_DIR/certs/server.key"
cd "$PROJECT_DIR" && docker compose exec -T nginx nginx -s reload || true
HOOK
        chmod +x "$HOOK"; bash "$HOOK"
        ok "$(L "Certificate issued; renewal hook installed (certbot.timer renews)" "Zertifikat ausgestellt; Erneuerung eingerichtet (certbot.timer erneuert)")"
    else
        tail -8 /var/log/oof-certbot.log | sed 's/^/     /'
        warn "$(L "Let's Encrypt failed — the interim certificate stays. Fix DNS/port 80 and re-run setup.sh." "Let's Encrypt fehlgeschlagen — das Übergangszertifikat bleibt. DNS/Port 80 prüfen und setup.sh erneut starten.")"
        GUIDE_FAILED=$((GUIDE_FAILED+1))
    fi
else
    note "$(L "Not used (self-signed)." "Nicht verwendet (selbstsigniert).")"
fi

# =====================================================================
step "$(L "Setting up login (Keycloak)" "Login einrichten (Keycloak)")"
# =====================================================================
KC_ENV=(PLATFORM_USER="$PLATFORM_USER" PLATFORM_EMAIL="$PLATFORM_EMAIL" PLATFORM_PASSWORD="$PLATFORM_PASSWORD"
        ALLOW_PASSWORD_GRANT="${ALLOW_PASSWORD_GRANT:-0}")
if [[ "$MODE" == "allinone" ]]; then
    KC_ENV+=(TENANT="$TENANT" TENANT_ADMIN_USER="$TENANT_ADMIN_USER" TENANT_ADMIN_EMAIL="$TENANT_ADMIN_EMAIL"
             TENANT_ADMIN_PASSWORD="$TENANT_ADMIN_PASSWORD")
fi
if env "${KC_ENV[@]}" bash scripts/configure-keycloak.sh >/var/log/oof-keycloak.log 2>&1; then
    ok "$(L "Realms 'osint' and 'platform' configured" "Realms 'osint' und 'platform' eingerichtet")"
else
    tail -12 /var/log/oof-keycloak.log | sed 's/^/     /'
    fail "$(L "Keycloak setup failed — log:" "Keycloak-Einrichtung fehlgeschlagen — Log:") /var/log/oof-keycloak.log"
fi

# =====================================================================
step "$(L "Organisation and data server" "Organisation und Datenserver")"
# =====================================================================
if [[ "$MODE" == "allinone" ]]; then
    TJSON="$(bash scripts/configure-tenant.sh "$TENANT" "$TENANT_ADMIN_EMAIL" --domains "$EMAIL_DOMAINS" \
             --agent-url "http://data-agent-local:9000")" || fail "$(L "Creating the organisation failed." "Anlegen der Organisation fehlgeschlagen.")"
    AGENT_KEY="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["agent_key"])' "$TJSON")"
    [[ -n "$AGENT_KEY" ]] || fail "$(L "No data-server key received." "Kein Datenserver-Schlüssel erhalten.")"
    ok "$(L "Organisation" "Organisation") '$TENANT' — $(L "email domains" "E-Mail-Domains"): $EMAIL_DOMAINS"

    AENV=data-agent/.env
    if [[ ! -s "$AENV" ]]; then
        APW="$(openssl rand -hex 24)"
        umask 077
        cat > "$AENV" <<EOF
# Generated by setup.sh (all-in-one data server) — do not share.
POSTGRES_PASSWORD=$APW
POSTGRES_KEYCLOAK_PASSWORD=$(openssl rand -hex 24)
DATABASE_URL=postgresql+asyncpg://agent:$APW@postgres:5432/agent
FRAMEWORK_KEY=$AGENT_KEY
KC_ADMIN_PASSWORD=$(openssl rand -hex 16)
EOF
        umask 022
    else
        sed -i "s|^FRAMEWORK_KEY=.*|FRAMEWORK_KEY=$AGENT_KEY|" "$AENV"
    fi
    chmod 600 "$AENV"
    if (cd data-agent && docker compose -f docker-compose.yml -f docker-compose.local.yml build -q agent >>"$BUILD_LOG" 2>&1 \
        && docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres agent >>"$BUILD_LOG" 2>&1); then
        for _ in $(seq 1 30); do
            dc exec -T api python -c "import httpx;httpx.get('http://data-agent-local:9000/health',timeout=3).raise_for_status()" >/dev/null 2>&1 && break
            sleep 3
        done
        ok "$(L "Local data server running (case data stays on this host)" "Lokaler Datenserver läuft (Falldaten bleiben auf diesem Host)")"
    else
        tail -15 "$BUILD_LOG" | sed 's/^/     /'; fail "$(L "Data server failed to start —" "Datenserver startet nicht —") $BUILD_LOG"
    fi
else
    note "$(L "Operator mode: organisations are created in /glbadmin → Authorities." "Betreibermodus: Organisationen werden in /glbadmin → Behörden angelegt.")"
fi

# =====================================================================
step "$(L "Datasets and data-server release" "Datensätze und Datenserver-Release")"
# =====================================================================
if [[ $SKIP_DATASETS -eq 0 ]]; then
    for ep in threat-actors linkbase; do
        dc exec -T module-forums python -c "import httpx;httpx.post('http://localhost:8110/$ep/refresh',timeout=20).raise_for_status()" >/dev/null 2>&1 \
            && ok "$(L "Download started:" "Download gestartet:") $ep $(L "(runs in the background, 2–15 min)" "(läuft im Hintergrund, 2–15 Min.)")" \
            || warn "$(L "Could not start" "Konnte nicht starten:") $ep $(L "— later: operator console → Settings" "— später: Betreiberkonsole → Einstellungen")"
    done
else
    note "$(L "Forum indexes skipped (--skip-datasets)." "Foren-Indizes übersprungen (--skip-datasets).")"
fi
if [[ "$MODE" == "operator" && $SKIP_RELEASE -eq 0 ]]; then
    info "$(L "Publishing the data-server release for customer servers …" "Datenserver-Release für Kundenserver wird veröffentlicht …")"
    if ALLOW_DIRTY=1 SKIP_TESTS=1 ASSUME_YES=1 SW_LANG="$SW_LANG" bash scripts/release.sh >/var/log/oof-release.log 2>&1; then
        ok "$(L "Release published at" "Release veröffentlicht unter") $(public_url)/agent/version.json"
    else
        tail -10 /var/log/oof-release.log | sed 's/^/     /'
        warn "$(L "Release failed — retry: bash scripts/release.sh" "Release fehlgeschlagen — erneut: bash scripts/release.sh")"
        GUIDE_FAILED=$((GUIDE_FAILED+1))
    fi
fi

# =====================================================================
step "$(L "Final verification" "Abschlussprüfung")"
# =====================================================================
sleep 3
UP=$(dc ps --services --filter status=running | wc -l); ALL=$(dc config --services | wc -l)
check "$(L "All services running" "Alle Dienste laufen") ($UP/$ALL)"   test "$UP" -eq "$ALL"
check "$(L "Web interface answers" "Weboberfläche antwortet")"         bash -c "curl -sk -o /dev/null -w '%{http_code}' $URL_LOCAL/ | grep -q 200"
check "$(L "Backend answers" "Backend antwortet")"                     bash -c "curl -skf $URL_LOCAL/api/v1/health | grep -q ok"
check "$(L "Login service answers" "Login-Dienst antwortet")"          bash -c "curl -skf $URL_LOCAL/auth/realms/osint/.well-known/openid-configuration | grep -q '\"issuer\":\"$(public_url)/auth/realms/osint\"'"
check "$(L "Operator login realm answers" "Login-Realm Betreiber antwortet")" curl -skf "$URL_LOCAL/auth/realms/platform/.well-known/openid-configuration"
check "$(L "API refuses requests without login" "API verweigert Anfragen ohne Login")" bash -c "curl -sk -o /dev/null -w '%{http_code}' $URL_LOCAL/api/v1/cases | grep -qE '401|403'"
if [[ "$MODE" == "allinone" ]]; then
    check "$(L "Email domain resolves to the organisation" "E-Mail-Domain führt zur Organisation")" \
        bash -c "curl -skf '$URL_LOCAL/api/v1/resolve-tenant?email=x@${EMAIL_DOMAINS%%,*}' | grep -q '$TENANT'"
    check "$(L "Data server reachable from the framework" "Datenserver vom Framework erreichbar")" \
        dc exec -T api python -c "import httpx;httpx.get('http://data-agent-local:9000/health',timeout=5).raise_for_status()"
fi
[[ "$MODE" == "operator" && $SKIP_RELEASE -eq 0 ]] && check "$(L "Data-server release served at /agent/" "Datenserver-Release unter /agent/ verfügbar")" \
    bash -c "curl -skf $URL_LOCAL/agent/version.json | grep -q '\"files\"'"

URL="$(public_url)"
umask 077
{
    echo "OOF — credentials ($(date -u +%Y-%m-%dT%H:%M:%SZ), $MODE)"
    echo "Address: $URL"
    echo
    echo "Operator console  $URL/glbadmin"
    echo "  user     : $PLATFORM_USER"
    echo "  password : $PLATFORM_PASSWORD"
    if [[ "$MODE" == "allinone" ]]; then
        echo
        echo "Web application   $URL/"
        echo "  sign in with : $TENANT_ADMIN_EMAIL   (user $TENANT_ADMIN_USER)"
        echo "  password     : $TENANT_ADMIN_PASSWORD"
        echo "  first login asks for a new password and an authenticator app (TOTP)"
    fi
    echo
    echo "Keycloak administration  $URL/auth/admin/"
    echo "  user     : $(envget KEYCLOAK_ADMIN_USER)"
    echo "  password : $(envget KEYCLOAK_ADMIN_PASSWORD)"
    echo "Grafana  $URL/grafana/   user admin / $(envget GRAFANA_PASSWORD)"
    echo
    echo "All other secrets: $ENV_FILE (chmod 600). Back up .env — without it"
    echo "the stored API keys and customer secrets cannot be decrypted."
} > "$CRED_FILE"
umask 022

if [[ $GUIDE_FAILED -eq 0 ]]; then summary_ok "$(L "Installation complete" "Installation abgeschlossen")"
else summary_bad "$(L "Installation complete —" "Installation abgeschlossen —") $GUIDE_FAILED $(L "item(s) open" "Punkt(e) offen")"; fi

cat <<EOF
   ${C_BOLD}$(L "Web application" "Webanwendung")${C_RESET}       $URL/
   ${C_BOLD}$(L "Operator console" "Betreiberkonsole")${C_RESET}     $URL/glbadmin
   ${C_BOLD}$(L "Credentials" "Zugangsdaten")${C_RESET}         $CRED_FILE  ($(L "root only" "nur root"))
EOF
[[ "$TLS_MODE" == "selfsigned" ]] && note "$(L "Self-signed certificate: the browser warns once — accept it to continue." "Selbstsigniertes Zertifikat: der Browser warnt einmal — akzeptieren, um fortzufahren.")"
echo
if [[ "$MODE" == "allinone" ]]; then
cat <<EOF
   ${C_BOLD}$(L "Next steps" "Nächste Schritte")${C_RESET}
   1. $(L "Sign in at" "Anmelden unter") $URL/ $(L "with" "mit") $TENANT_ADMIN_EMAIL
   2. $(L "Add API keys (all optional) in" "API-Schlüssel (alle optional) eintragen in") $URL/glbadmin → $(L "Settings" "Einstellungen")
   3. $(L "Add users: Admin → User Management (their email domain must be one of" "Benutzer anlegen: Admin → Benutzerverwaltung (deren E-Mail-Domain muss eine von") $EMAIL_DOMAINS $(L "be)" "sein)")
   4. $(L "Backups:" "Sicherung:") docs/operations.$SW_LANG.md
EOF
else
cat <<EOF
   ${C_BOLD}$(L "Next steps" "Nächste Schritte")${C_RESET}
   1. $(L "Sign in to" "Anmelden in") $URL/glbadmin $(L "and create an organisation (Authorities → New)" "und eine Organisation anlegen (Behörden → Neu)")
   2. $(L "Give the organisation its licence key; it installs its data server with" "Der Organisation ihren Lizenzschlüssel geben; sie installiert ihren Datenserver mit")
        curl -fsSL$([[ "$TLS_MODE" == "selfsigned" ]] && echo "k") $URL/agent/install.sh -o install.sh && sudo bash install.sh
   3. $(L "Register the URLs it reports back (data server + login) in /glbadmin" "Die zurückgemeldeten URLs (Datenserver + Login) in /glbadmin eintragen")
   $(L "Guide:" "Anleitung:") docs/install.$SW_LANG.md, docs/customer-server.$SW_LANG.md
EOF
fi
echo
note "$(L "Health:" "Zustand:") bash scripts/health-check.sh    $(L "Update:" "Aktualisieren:") git pull && sudo ./setup.sh"
echo
