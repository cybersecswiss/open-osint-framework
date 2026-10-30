#!/bin/bash
# Quick health probe for the running stack.
# Works without DNS — uses 127.0.0.1 by default.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
set -a; source .env; set +a

HOST="${1:-127.0.0.1}"
HTTP_PORT="${PUBLIC_HTTP_PORT:-80}"
HTTPS_PORT="${PUBLIC_HTTPS_PORT:-443}"

echo "=== Container status ==="
docker compose ps

# A stopped service is invisible to the HTTP probes below — nothing here
# talks to a module directly, so dead OSINT modules or a dead n8n would
# still produce a fully green report. Compare defined vs. running instead.
echo
echo "=== Service completeness ==="
defined=$(docker compose config --services 2>/dev/null | sort)
running=$(docker compose ps --services 2>/dev/null | sort)
missing=$(comm -23 <(echo "$defined") <(echo "$running"))
if [[ -z "$missing" ]]; then
    printf "  [OK]   all %s services running\n" "$(echo "$defined" | wc -l)"
else
    printf "  [FAIL] %s of %s services NOT running:\n" \
        "$(echo "$missing" | wc -l)" "$(echo "$defined" | wc -l)"
    echo "$missing" | sed 's/^/           - /'
    echo "           start with: docker compose up -d <service>"
    echo "           if that reports 'AlreadyExists: task ... already exists',"
    echo "           the containerd task is orphaned — 'docker compose rm -sf <service>' first."
fi

echo
echo "=== HTTP/S probes (host: $HOST  http:$HTTP_PORT  https:$HTTPS_PORT) ==="

probe() {
    local name=$1 url=$2 expected=$3
    local code
    code=$(curl -sk --max-time 5 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "ERR")
    if [[ "$code" == "$expected" ]]; then
        printf "  [OK]   %-30s -> %s\n" "$name" "$code"
    else
        printf "  [FAIL] %-30s -> %s (expected %s)\n" "$name" "$code" "$expected"
    fi
}

probe "HTTP redirect"        "http://$HOST:$HTTP_PORT/"                                              301
probe "HTTPS root"           "https://$HOST:$HTTPS_PORT/"                                            200
probe "Keycloak realm OIDC"  "https://$HOST:$HTTPS_PORT/auth/realms/osint/.well-known/openid-configuration" 200
probe "Keycloak account"     "https://$HOST:$HTTPS_PORT/auth/realms/osint/account"                   302
probe "Grafana"              "https://$HOST:$HTTPS_PORT/grafana/api/health"                          200
probe "Backend API health"   "https://$HOST:$HTTPS_PORT/api/v1/health"                               200
probe "Backend API deep"     "https://$HOST:$HTTPS_PORT/api/v1/health/deep"                          200
probe "Backend auth (no token = 403)" "https://$HOST:$HTTPS_PORT/api/v1/cases"                       403

echo
echo "=== Direct service probes (inside docker net) ==="
docker compose exec -T postgres pg_isready -U osint && echo "  [OK]   postgres ready" || echo "  [FAIL] postgres"
docker compose exec -T redis sh -c 'redis-cli -a "$REDIS_PASSWORD" ping' 2>/dev/null | grep -q PONG \
    && echo "  [OK]   redis pong" || echo "  [FAIL] redis"

echo
echo "=== Customer data agents (authenticated round-trip) ==="
# Why authenticated and not just /health: the framework used to send its own
# global secret as X-Framework-Key while every real customer agent expects
# the per-tenant licence key. An unauthenticated liveness probe was green
# throughout — the mismatch would only have surfaced as failed searches at
# the customer. This probe exercises the real credential path.
docker compose exec -T api python - <<'PY' 2>/dev/null || echo "  [WARN] agent probe could not run"
import asyncio, os, httpx
from app.config import settings
from app.services.agent_client import AgentAuthError, AgentUnavailable, get_from_agent
from app.services.tenant_registry import (
    AgentKeyUnavailable, TenantNotConfigured, get_agent_url,
)

async def tenants():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{settings.license_server_url}/api/v1/tenants",
                        headers={"X-Internal-Key": settings.internal_secret})
        r.raise_for_status()
        return [row["tenant"] for row in r.json()]

# Mandanten, deren Agent bewusst nicht erreichbar ist (Demo-/Musterlizenzen
# mit erfundener URL). Ohne diese Liste meldete der Health-Check bei jedem
# Lauf dieselbe Warnung — und eine Warnung, die immer da steht, wird nicht
# mehr gelesen. Genau dann verpasst man die echte.
# Über die Umgebung setzbar:  DEMO_TENANTS="demo-a,demo-b"
DEMO = {x.strip() for x in os.environ.get("DEMO_TENANTS", "").split(",") if x.strip()}

async def main():
    try:
        names = await tenants()
    except Exception as e:
        print(f"  [WARN] tenant list unavailable: {type(e).__name__}")
        return
    for t in names:
        if t in DEMO:
            print(f"  [DEMO] {t:<20} Musterlizenz — Agent absichtlich nicht erreichbar")
            continue
        try:
            await get_agent_url(t)
        except TenantNotConfigured:
            print(f"  [--]   {t:<20} no agent registered (local fallback)")
            continue
        try:
            # 404 is a fine answer here: it proves the key was accepted.
            await get_from_agent(t, "/api/cases/00000000-0000-0000-0000-000000000000/graph")
            print(f"  [OK]   {t:<20} agent reachable + key accepted")
        except AgentAuthError:
            print(f"  [FAIL] {t:<20} agent REJECTED the framework key (401/403)")
        except AgentKeyUnavailable as e:
            print(f"  [FAIL] {t:<20} no usable agent key: {e}")
        except AgentUnavailable:
            print(f"  [WARN] {t:<20} agent unreachable (network)")
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            verdict = "OK" if code in (404, 422) else "WARN"
            print(f"  [{verdict}]   {t:<20} agent answered HTTP {code} (key accepted)")

asyncio.run(main())
PY

# =====================================================================
# Sicherungskette — laeuft sie ueberhaupt noch?
# =====================================================================
# Ohne diese Pruefung beantwortet nichts diese Frage. Die Dateien von gestern
# liegen nach einem ausgefallenen Cron genauso da wie nach einem
# erfolgreichen Lauf, und der Unterschied faellt erst an dem Tag auf, an
# dem man eine Sicherung braucht. Der Waechter liest die Zustandsdateien,
# die scripts/run-scheduled.sh je Auftrag schreibt.
echo
if [[ -x "$(dirname "$0")/backup-watchdog.sh" ]]; then
    bash "$(dirname "$0")/backup-watchdog.sh" || true
else
    echo "=== Sicherungskette ==="
    echo "  [WARN] scripts/backup-watchdog.sh fehlt"
fi
