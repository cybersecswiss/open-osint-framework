#!/bin/bash
# =============================================================
# Rebuild/recreate one or more compose services WITHOUT leaving nginx
# pointed at a dead container IP.
#
# Why this exists
# ---------------
# nginx proxies to service names via variable proxy_pass + the Docker
# resolver (nginx/conf.d/main.conf). When a proxied container is
# `--force-recreate`d it gets a NEW IP; nginx keeps the old one until the
# resolver TTL (valid=5s) lapses, so clients can see a few seconds of 502
# during/after the swap. Reloading nginx drops the resolver cache
# immediately, so the very next request re-resolves to the new container.
#
# Usage
#   bash scripts/rebuild.sh api                 # recreate api, reload nginx
#   bash scripts/rebuild.sh api frontend        # several at once
#   BUILD=1 bash scripts/rebuild.sh api         # rebuild image first
#   bash scripts/rebuild.sh                      # just reload nginx (flush DNS)
#
# Only nginx-proxied services need the reload, but reloading is cheap and
# harmless for any service, so we always do it.
#
# BUILD=1 also tags the new image with the current commit (see
# scripts/image-versions.sh) so rollback.sh has a generation to return to.
# A plain `docker compose build` does NOT do that — use this script, or run
# `bash scripts/image-versions.sh tag <service>` right after.
# =============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

SERVICES=("$@")
BUILD="${BUILD:-0}"

if [[ ${#SERVICES[@]} -gt 0 ]]; then
    if [[ "$BUILD" == "1" ]]; then
        echo ">>> building ${SERVICES[*]}"
        docker compose build "${SERVICES[@]}"
        # Name the fresh image after the commit it was built from, and keep
        # the newest IMAGE_KEEP generations. Without this the previous image
        # loses its only tag on every rebuild, which is why a rollback had
        # nothing to go back to. Never fatal: a failed tag must not make a
        # successful build look broken.
        bash scripts/image-versions.sh tag "${SERVICES[@]}" || \
            echo "    WARN: could not tag images — rollback for this build is source-only." >&2
        bash scripts/image-versions.sh prune "${IMAGE_KEEP:-2}" >/dev/null || true
    fi

# --- don't recreate the api out from under a running search -----------
#
# ⚠️ This check sits AFTER the build on purpose. It used to run first and
# `exit 1` before building, so `BUILD=1 rebuild.sh api` during a search built
# NOTHING while looking like it had been stopped at the recreate step. A later
# plain `rebuild.sh api` then recreated the container from the stale image and
# printed "Done." — a deploy that silently shipped the previous code. Building
# does not touch the running container, so it is safe during a search; only
# recreating is not.
#
# `_run_search` is a FastAPI BackgroundTask: it lives inside the api process.
# Recreating that container kills the fan-out mid-flight, and NOTHING says so
# — the job row simply stays `running` with a stale heartbeat until the reaper
# marks it failed 20 minutes later. A long-running username search can easily
# be several minutes in when a rebuild lands.
#
# Findings already flushed survive (the flush is per tool), but everything
# still in flight is lost, and edges whose endpoints were held back for the
# final flush never arrive.
if [[ " ${SERVICES[*]} " == *" api "* ]] && [[ "${FORCE:-0}" != "1" ]]; then
    # NOTE: the python below is a string, so its lines must stay at
    # column 0 — indenting them for looks yields an IndentationError that
    # `2>/dev/null || true` swallows, leaving the guard permanently silent.
    running="$(docker compose exec -T api python -c "
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal
async def m():
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            \"SELECT query, query_type, started_at FROM search_jobs WHERE status='running'\"
        ))).all()
    for q, qt, at in rows:
        print(f'  {q!r} ({qt}) since {at}')
asyncio.run(m())" 2>/dev/null || true)"
    if [[ -n "$running" ]]; then
        echo "" >&2
        echo "WARNING: search job(s) are RUNNING right now:" >&2
        echo "$running" >&2
        echo "Recreating 'api' kills them mid-flight; the job stays 'running'" >&2
        echo "until the reaper fails it ~20 min later." >&2
        if [[ "$BUILD" == "1" ]]; then
            echo "The image IS built and tagged; only the recreate is pending." >&2
        fi
        echo "Re-run WITHOUT BUILD=1 once the search finishes to deploy it:" >&2
        echo "    bash scripts/rebuild.sh ${SERVICES[*]}" >&2
        if [[ -t 0 ]]; then
            read -rp "Recreate anyway? [y/N] " _yn
            [[ "$_yn" == "y" || "$_yn" == "Y" ]] || { echo "Aborted."; exit 1; }
        else
            echo "Refusing in a non-interactive shell. Re-run with FORCE=1 to override." >&2
            exit 1
        fi
    fi
fi

    echo ">>> recreating ${SERVICES[*]}"
    docker compose up -d --force-recreate --no-deps "${SERVICES[@]}"
fi

# Flush nginx's resolver cache so it re-resolves the recreated container(s)
# on the next request instead of holding a stale IP for up to valid=5s.
if docker compose ps --status running --services 2>/dev/null | grep -qx nginx; then
    echo ">>> reloading nginx (flush DNS cache)"
    # Validate first so a bad config can't take the proxy down.
    if docker compose exec -T nginx nginx -t 2>/dev/null; then
        docker compose exec -T nginx nginx -s reload
        echo "    nginx reloaded."
    else
        echo "    WARN: nginx -t failed; skipped reload (config unchanged, DNS will self-heal in ~5s)." >&2
    fi
else
    echo ">>> nginx not running; nothing to reload."
fi

echo "Done."
