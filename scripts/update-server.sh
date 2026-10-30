#!/bin/bash
# =============================================================
# OOF — update existing install
#   - git pull
#   - docker compose pull (new images)
#   - rebuild local images that exist
#   - alembic migrate (when the backend exists)
#   - rolling restart
# =============================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/oof}"
cd "$PROJECT_DIR"

log() { printf "\033[1;34m[update]\033[0m %s\n" "$*"; }

# 1. git
if [[ -d .git ]]; then
    BRANCH="$(git rev-parse --abbrev-ref HEAD)"
    log "git pull on branch $BRANCH"
    git pull --ff-only
else
    log "Not a git repo, skipping pull."
fi

# 2. images
log "Pulling images"
docker compose pull -q

# 3. rebuild local images
# Derived from the compose file itself — every service carrying a `build:`
# directive. A hard-coded list silently rots: every service added later
# would keep running a stale image after a `git pull`, with no error
# anywhere.
mapfile -t BUILDABLE < <(docker compose config --format json | python3 -c '
import json, sys
services = json.load(sys.stdin).get("services", {})
for name in sorted(services):
    if services[name].get("build"):
        print(name)
')

if [[ ${#BUILDABLE[@]} -gt 0 ]]; then
    log "Rebuilding ${#BUILDABLE[@]} services: ${BUILDABLE[*]}"
    docker compose build "${BUILDABLE[@]}"
else
    log "No services with a build: directive found — check docker-compose.yml."
    exit 1
fi

# 4. database schema
# No alembic: `backend/alembic/versions/` is empty and the schema is created
# by `app/bootstrap.py` (create_all + idempotent ADD COLUMN IF NOT EXISTS)
# on every api start. A new column needs a model change AND a line in
# ADHOC_MIGRATIONS — see docs/operations.en.md.
log "Schema: handled by app/bootstrap.py at api startup (no alembic step)"

# 5. rolling restart
log "Recreating containers"
docker compose up -d

# Flush nginx's DNS cache so it re-resolves the recreated containers
# immediately instead of serving 502s for up to `resolver valid=5s`.
docker compose exec -T nginx nginx -t >/dev/null 2>&1 \
    && docker compose exec -T nginx nginx -s reload >/dev/null 2>&1 \
    && log "nginx reloaded"

sleep 3
docker compose ps

# Surface anything that did not come back up.
missing=$(comm -23 <(docker compose config --services | sort) \
                   <(docker compose ps --services | sort))
if [[ -n "$missing" ]]; then
    log "WARNING — these services are NOT running:"
    echo "$missing" | sed 's/^/    - /'
    log "If 'up -d' reported 'AlreadyExists: task ... already exists',"
    log "clear it with: docker compose rm -sf <service> && docker compose up -d <service>"
fi

log "Update complete."
