#!/bin/bash
# =============================================================
# Create (or update) a tenant in the license server — idempotent.
#
#   bash scripts/configure-tenant.sh <tenant> <contact-email> \
#        [--domains a.example,b.example] [--agent-url URL] [--days N]
#
# Prints the tenant's licence key and agent key as JSON on stdout when
# the tenant is created; on a re-run it prints the stored agent key only
# (licence keys are shown once — see /glbadmin to rotate).
#
# Normally tenants are created in the operator console (/glbadmin →
# Authorities). setup.sh uses this script for the all-in-one install.
# =============================================================
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

TENANT="${1:?tenant name}"; CONTACT="${2:?contact email}"; shift 2
DOMAINS=""; AGENT_URL=""; DAYS=3650
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domains)   DOMAINS="$2"; shift 2 ;;
        --agent-url) AGENT_URL="$2"; shift 2 ;;
        --days)      DAYS="$2"; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done
[[ "$TENANT" =~ ^[a-z0-9][a-z0-9-]{1,30}$ ]] || { echo "tenant must be lowercase letters, digits, '-' (2–31 chars)" >&2; exit 2; }

KEY="${INTERNAL_KEY:-$API_SECRET_KEY}"
# Talk to the license server from inside the api container: it is not
# published, and the api image has python + httpx.
lic() {  # lic METHOD PATH [JSON]
    docker compose exec -T -e K="$KEY" -e M="$1" -e P="$2" -e B="${3:-}" api python - <<'PY'
import json, os, sys, httpx
r = httpx.request(os.environ["M"], "http://license:9000" + os.environ["P"],
                  headers={"X-Internal-Key": os.environ["K"]},
                  json=json.loads(os.environ["B"]) if os.environ["B"] else None, timeout=20)
print(json.dumps({"status": r.status_code, "body": r.json() if r.content else None}))
PY
}
status() { python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])'; }

for _ in $(seq 1 40); do
    docker compose exec -T api python -c "import httpx;httpx.get('http://license:9000/health',timeout=3).raise_for_status()" >/dev/null 2>&1 && break
    sleep 3
done

OUT="$(lic POST /api/v1/license/create "{\"tenant\":\"$TENANT\",\"contact_email\":\"$CONTACT\",\"valid_days\":$DAYS}")"
case "$(status <<<"$OUT")" in
    200|201) CREATED=1 ;;
    409)     CREATED=0 ;;
    *) echo "license create failed: $OUT" >&2; exit 1 ;;
esac

if [[ -n "$DOMAINS" ]]; then
    JSON="$(python3 -c 'import json,sys;print(json.dumps({"email_domains":[d.strip() for d in sys.argv[1].split(",") if d.strip()]}))' "$DOMAINS")"
    [[ "$(lic PUT "/api/v1/tenants/$TENANT/email-domains" "$JSON" | status)" == 200 ]] || { echo "setting email domains failed" >&2; exit 1; }
fi
if [[ -n "$AGENT_URL" ]]; then
    R="$(lic PUT "/api/v1/tenants/$TENANT/agent-url" "{\"agent_url\":\"$AGENT_URL\"}")"
    [[ "$(status <<<"$R")" == 200 ]] || { echo "setting agent url failed: $R" >&2; exit 1; }
fi

AGENT_KEY="$(lic GET "/api/v1/tenants/$TENANT/agent-key" | python3 -c 'import json,sys;print((json.load(sys.stdin)["body"] or {}).get("agent_key",""))')"
if [[ "$CREATED" == 1 ]]; then
    python3 -c 'import json,sys;b=json.loads(sys.argv[1])["body"];print(json.dumps({"tenant":b["tenant"],"license_key":b["license_key"],"agent_key":b["agent_api_key"],"created":True}))' "$OUT"
else
    python3 -c 'import json,sys;print(json.dumps({"tenant":sys.argv[1],"agent_key":sys.argv[2],"created":False}))' "$TENANT" "$AGENT_KEY"
fi
