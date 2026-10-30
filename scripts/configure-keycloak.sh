#!/bin/bash
# =============================================================
# Idempotent Keycloak post-import configuration. Called by setup.sh;
# safe to re-run by hand:
#
#   sudo PLATFORM_PASSWORD='…' bash scripts/configure-keycloak.sh
#
# What it does (realm `osint` comes from keycloak/realm-export.json):
#   1. syncs the osint-backend client secret with KEYCLOAK_CLIENT_SECRET
#      and grants its service account the user-management roles
#   2. adds a `groups` mapper to osint-backend + osint-frontend, so tokens
#      carry the tenant group
#   3. creates realm `platform` with the clients of the operator console
#      (/glbadmin) and the product-owner account PLATFORM_USER
#   4. optionally (TENANT set) creates the tenant group, and with
#      TENANT_ADMIN_USER set the tenant's first administrator in realm
#      `osint` — used by the all-in-one setup, where the tenant logs in
#      through the framework's own Keycloak instead of its own IdP
#
# Environment:
#   PLATFORM_USER / PLATFORM_EMAIL / PLATFORM_PASSWORD   (password required)
#   TENANT, TENANT_ADMIN_USER, TENANT_ADMIN_EMAIL, TENANT_ADMIN_PASSWORD
#   ALLOW_PASSWORD_GRANT=1   enable the OAuth password grant on the public
#                            clients (automation/tests only — off by default)
#
# There are deliberately NO default passwords in this file: it is public.
# =============================================================
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source .env; set +a

KC="docker compose exec -T keycloak"
KCBIN="/opt/keycloak/bin/kcadm.sh"
ALLOW_PASSWORD_GRANT="${ALLOW_PASSWORD_GRANT:-0}"
DIRECT_GRANTS=false; [[ "$ALLOW_PASSWORD_GRANT" == "1" ]] && DIRECT_GRANTS=true

log() { printf "\033[1;34m[kc]\033[0m %s\n" "$*"; }
die() { printf "\033[1;31m[kc]\033[0m %s\n" "$*" >&2; exit 1; }

[[ -n "${PLATFORM_PASSWORD:-}" ]] || die "PLATFORM_PASSWORD must be set (no default on purpose)."
[[ -n "${KEYCLOAK_CLIENT_SECRET:-}" ]] || die "KEYCLOAK_CLIENT_SECRET missing in .env — run setup.sh first."
[[ -n "${PLATFORM_KC_CLIENT_SECRET:-}" ]] || die "PLATFORM_KC_CLIENT_SECRET missing in .env — run setup.sh first."

log "Waiting for Keycloak"
for _ in $(seq 1 60); do
    $KC bash -c "exec 3<>/dev/tcp/127.0.0.1/8080" >/dev/null 2>&1 \
        && $KC $KCBIN config credentials --server http://localhost:8080/auth --realm master \
               --user "$KEYCLOAK_ADMIN_USER" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null 2>&1 \
        && break
    sleep 3
done
$KC $KCBIN config credentials --server http://localhost:8080/auth --realm master \
    --user "$KEYCLOAK_ADMIN_USER" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null \
    || die "Cannot log in to Keycloak as $KEYCLOAK_ADMIN_USER."

cid() {  # cid REALM CLIENT_ID → internal id
    $KC $KCBIN get clients -r "$1" -q "clientId=$2" --fields id --format csv --noquotes 2>/dev/null | head -1 | tr -d '[:space:]'
}

# ── 1. realm osint: backend client ─────────────────────────────────
log "Realm osint: backend client"
BACKEND_ID="$(cid osint osint-backend)"
[[ -n "$BACKEND_ID" ]] || die "client 'osint-backend' not found — was keycloak/realm-export.json imported?"
$KC $KCBIN update "clients/$BACKEND_ID" -r osint -s "secret=$KEYCLOAK_CLIENT_SECRET" \
    -s serviceAccountsEnabled=true -s standardFlowEnabled=true >/dev/null
SVC_USER_ID="$($KC $KCBIN get "clients/$BACKEND_ID/service-account-user" -r osint --fields id --format csv --noquotes 2>/dev/null | head -1 | tr -d '[:space:]')"
if [[ -n "$SVC_USER_ID" ]]; then
    for role in view-users manage-users query-users query-groups view-realm; do
        $KC $KCBIN add-roles -r osint --uid "$SVC_USER_ID" --cclientid realm-management --rolename "$role" 2>/dev/null || true
    done
fi
log "  secret synced, service-account roles granted"

FRONTEND_ID="$(cid osint osint-frontend)"
$KC $KCBIN update "clients/$FRONTEND_ID" -r osint -s publicClient=true \
    -s "directAccessGrantsEnabled=$DIRECT_GRANTS" >/dev/null
log "  osint-frontend: public client, password grant $DIRECT_GRANTS"

add_groups_mapper() {
    local id="$1" name="$2"
    local names
    # Captured first: `kcadm … | grep -q` under pipefail fails on SIGPIPE
    # and would report an existing mapper as missing.
    names="$($KC $KCBIN get "clients/$id/protocol-mappers/models" -r osint --fields name --format csv --noquotes 2>/dev/null || true)"
    if grep -qx 'groups' <<<"$(tr -d '\r' <<<"$names")"; then
        return
    fi
    $KC $KCBIN create "clients/$id/protocol-mappers/models" -r osint \
        -s 'name=groups' -s 'protocol=openid-connect' \
        -s 'protocolMapper=oidc-group-membership-mapper' \
        -s 'config."claim.name"=groups' -s 'config."full.path"=false' \
        -s 'config."id.token.claim"=true' -s 'config."access.token.claim"=true' \
        -s 'config."userinfo.token.claim"=true' >/dev/null
    log "  groups mapper added to $name"
}
add_groups_mapper "$BACKEND_ID" osint-backend
add_groups_mapper "$FRONTEND_ID" osint-frontend

# ── 2. optional tenant group + first tenant administrator ───────────
if [[ -n "${TENANT:-}" ]]; then
    log "Tenant group '$TENANT'"
    GROUP_ID="$($KC $KCBIN get groups -r osint -q "search=$TENANT" --fields id,name --format csv --noquotes 2>/dev/null \
        | awk -F, -v g="$TENANT" '$2==g {print $1}' | head -1)"
    if [[ -z "$GROUP_ID" ]]; then
        GROUP_ID="$($KC $KCBIN create groups -r osint -s "name=$TENANT" -i 2>/dev/null | tr -d '[:space:]')"
        log "  created"
    fi
    $KC $KCBIN add-roles -r osint --gid "$GROUP_ID" --rolename investigator 2>/dev/null || true

    if [[ -n "${TENANT_ADMIN_USER:-}" ]]; then
        [[ -n "${TENANT_ADMIN_PASSWORD:-}" ]] || die "TENANT_ADMIN_PASSWORD must be set with TENANT_ADMIN_USER."
        log "Tenant administrator '$TENANT_ADMIN_USER'"
        UID_="$($KC $KCBIN get users -r osint -q "username=$TENANT_ADMIN_USER" -q exact=true --fields id --format csv --noquotes 2>/dev/null | head -1 | tr -d '[:space:]')"
        if [[ -z "$UID_" ]]; then
            UID_="$($KC $KCBIN create users -r osint -s "username=$TENANT_ADMIN_USER" \
                -s "email=${TENANT_ADMIN_EMAIL:-}" -s emailVerified=true -s enabled=true \
                -i 2>/dev/null | tr -d '[:space:]')"
            $KC $KCBIN set-password -r osint --userid "$UID_" --new-password "$TENANT_ADMIN_PASSWORD" 2>&1 \
                | grep -v invalidPasswordHistoryMessage || true
            # First login: choose an own password and enrol a second factor.
            echo '{"requiredActions":["UPDATE_PASSWORD","CONFIGURE_TOTP"]}' | \
                $KC $KCBIN update "users/$UID_" -r osint -f - >/dev/null 2>&1 || true
            log "  created (password change + TOTP enrolment at first login)"
        else
            log "  exists — password left unchanged"
        fi
        $KC $KCBIN update "users/$UID_/groups/$GROUP_ID" -r osint -n 2>/dev/null || true
        $KC $KCBIN add-roles -r osint --uid "$UID_" --rolename admin 2>/dev/null || true
        $KC $KCBIN add-roles -r osint --uid "$UID_" --rolename investigator 2>/dev/null || true
    fi
fi

# ── 3. realm platform (operator console /glbadmin) ──────────────────
PLATFORM_REALM="${PLATFORM_REALM:-platform}"
PLATFORM_USER="${PLATFORM_USER:-owner}"
PLATFORM_EMAIL="${PLATFORM_EMAIL:-${PLATFORM_USER}@platform.invalid}"

log "Realm '$PLATFORM_REALM'"
if [[ -z "$($KC $KCBIN get "realms/$PLATFORM_REALM" --fields realm --format csv --noquotes 2>/dev/null | head -1)" ]]; then
    $KC $KCBIN create realms -s "realm=$PLATFORM_REALM" -s enabled=true \
        -s sslRequired=external -s registrationAllowed=false >/dev/null
    log "  created"
fi
$KC $KCBIN update "realms/$PLATFORM_REALM" \
    -s bruteForceProtected=true -s failureFactor=5 -s waitIncrementSeconds=900 \
    -s accessTokenLifespan=900 -s ssoSessionIdleTimeout=1800 -s ssoSessionMaxLifespan=36000 >/dev/null
$KC $KCBIN update authentication/required-actions/VERIFY_PROFILE -r "$PLATFORM_REALM" \
    -s enabled=false -s defaultAction=false 2>/dev/null || true

PC_ID="$(cid "$PLATFORM_REALM" platform-console)"
if [[ -z "$PC_ID" ]]; then
    PC_ID="$($KC $KCBIN create clients -r "$PLATFORM_REALM" \
        -s clientId=platform-console -s enabled=true -s publicClient=true \
        -s standardFlowEnabled=true \
        -s 'redirectUris=["*"]' -s 'webOrigins=["+"]' \
        -s 'attributes."pkce.code.challenge.method"=S256' -i 2>/dev/null | tr -d '[:space:]')"
    log "  client platform-console created"
fi
$KC $KCBIN update "clients/$PC_ID" -r "$PLATFORM_REALM" -s "directAccessGrantsEnabled=$DIRECT_GRANTS" >/dev/null

PB_ID="$(cid "$PLATFORM_REALM" platform-backend)"
if [[ -z "$PB_ID" ]]; then
    PB_ID="$($KC $KCBIN create clients -r "$PLATFORM_REALM" \
        -s clientId=platform-backend -s enabled=true -s publicClient=false \
        -s serviceAccountsEnabled=true -s standardFlowEnabled=false \
        -s directAccessGrantsEnabled=false -i 2>/dev/null | tr -d '[:space:]')"
    log "  client platform-backend created"
fi
$KC $KCBIN update "clients/$PB_ID" -r "$PLATFORM_REALM" -s "secret=$PLATFORM_KC_CLIENT_SECRET" >/dev/null
PB_SVC="$($KC $KCBIN get "clients/$PB_ID/service-account-user" -r "$PLATFORM_REALM" --fields id --format csv --noquotes 2>/dev/null | head -1 | tr -d '[:space:]')"
if [[ -n "$PB_SVC" ]]; then
    for role in manage-users view-users query-users view-realm manage-realm view-clients; do
        $KC $KCBIN add-roles -r "$PLATFORM_REALM" --uid "$PB_SVC" --cclientid realm-management --rolename "$role" 2>/dev/null || true
    done
fi
$KC $KCBIN create roles -r "$PLATFORM_REALM" -s name=platform_admin >/dev/null 2>&1 || true

log "Product owner '$PLATFORM_USER'"
OWNER_ID="$($KC $KCBIN get users -r "$PLATFORM_REALM" -q "username=$PLATFORM_USER" -q exact=true --fields id --format csv --noquotes 2>/dev/null | head -1 | tr -d '[:space:]')"
if [[ -z "$OWNER_ID" ]]; then
    OWNER_ID="$($KC $KCBIN create users -r "$PLATFORM_REALM" \
        -s "username=$PLATFORM_USER" -s "email=$PLATFORM_EMAIL" \
        -s firstName=Product -s lastName=Owner \
        -s emailVerified=true -s enabled=true -i 2>/dev/null | tr -d '[:space:]')"
    log "  created"
fi
echo '{"requiredActions":[],"enabled":true}' | $KC $KCBIN update "users/$OWNER_ID" -r "$PLATFORM_REALM" -f - >/dev/null 2>&1 || true
$KC $KCBIN set-password -r "$PLATFORM_REALM" --userid "$OWNER_ID" --new-password "$PLATFORM_PASSWORD" 2>&1 \
    | grep -v invalidPasswordHistoryMessage || true
$KC $KCBIN add-roles -r "$PLATFORM_REALM" --uid "$OWNER_ID" --rolename platform_admin 2>/dev/null || true

log "Done."
