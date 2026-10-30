#!/bin/bash
# =============================================================
# OOF — roll back code AND the containers that run it
#
# What was wrong before
# ---------------------
# The old version did `git reset --hard HEAD~1` and then
# `docker compose up -d --force-recreate`. Compose does NOT rebuild in that
# call, so it recreated the containers from the images that were already
# there — i.e. from the code being rolled back. Application code is baked
# into the images (only wiki/, threat-catalog/, messenger config/ and the
# telegram session/ are bind-mounted), so the running system kept the new
# code while the tree on disk showed the old one. The two silently drifted
# apart, which is worse than not rolling back at all.
#
# How it works now
# ----------------
# Builds tag their image with the commit they came from (rebuild.sh +
# image-versions.sh). This script therefore knows whether a *named*
# generation for the target commit exists:
#
#   all images present  -> retag them onto :latest and recreate. Seconds,
#                          no build, byte-identical to what ran before.
#   some/none present   -> rebuild those services from the rolled-back
#                          source. Minutes, but correct.
#
# It never recreates containers from images whose provenance does not match
# the tree. That decision is stated out loud before anything is touched.
#
# Volumes are NOT touched — DB state stays put. A rollback is a code
# operation; a schema downgrade is not automatic and never silent (Alembic
# does not auto-downgrade, and the agent only ever adds columns).
#
# Usage
#   bash scripts/rollback.sh                  # to HEAD~1
#   bash scripts/rollback.sh <commit|tag>     # to a specific commit
#   bash scripts/rollback.sh --list           # what can be rolled back to
#
# Undo a rollback: the outgoing images are kept as `:pre-rollback`, and git
# still has the newer commit (`git reflog`).
# =============================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/oof}"

# --- run from a copy -------------------------------------------------
# `git reset --hard` rewrites files in scripts/ — including this script and
# its helper — while bash is still reading this one incrementally. Execute
# from a temp copy so the reset cannot mutate the code that is running it.
if [[ "${ROLLBACK_DETACHED:-0}" != "1" ]]; then
    _tmp="$(mktemp -d)"
    cp "$0" "$_tmp/rollback.sh"
    cp "$PROJECT_DIR/scripts/image-versions.sh" "$_tmp/" 2>/dev/null || true
    export ROLLBACK_DETACHED=1 ROLLBACK_HELPER_DIR="$_tmp" PROJECT_DIR
    exec bash "$_tmp/rollback.sh" "$@"
fi
trap '[[ -n "${ROLLBACK_HELPER_DIR:-}" ]] && rm -rf "$ROLLBACK_HELPER_DIR"' EXIT

cd "$PROJECT_DIR"
IMAGES="${ROLLBACK_HELPER_DIR}/image-versions.sh"

log()  { printf "\033[1;34m[rollback]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[rollback]\033[0m %s\n" "$*" >&2; }
err()  { printf "\033[1;31m[rollback]\033[0m %s\n" "$*" >&2; }

[[ -d .git ]] || { err "not a git repo"; exit 1; }

if [[ "${1:-}" == "--list" ]]; then
    log "image generations available per service:"
    bash "$IMAGES" list
    echo
    log "recent commits:"
    git log --oneline -10
    exit 0
fi

CURRENT="$(git rev-parse --short HEAD)"
TARGET_REF="${1:-HEAD~1}"
TARGET="$(git rev-parse --short "$TARGET_REF" 2>/dev/null)" || {
    err "unknown commit: $TARGET_REF"; exit 1; }

[[ "$CURRENT" != "$TARGET" ]] || { err "already at $TARGET — nothing to do"; exit 1; }

if [[ -n "$(git status --porcelain)" ]]; then
    warn "working tree is DIRTY — 'git reset --hard' will discard these changes:"
    git status --short | sed 's/^/    /'
fi

log "current : $CURRENT  $(git log -1 --format=%s "$CURRENT" | cut -c1-60)"
log "target  : $TARGET  $(git log -1 --format=%s "$TARGET" | cut -c1-60)"
echo

# --- can we restore images, or must we rebuild? ----------------------
if bash "$IMAGES" check "$TARGET" 2>/dev/null; then
    MODE="restore"
    log "PLAN: images for $TARGET exist -> retag onto :latest + recreate (no build)"
else
    MODE="rebuild"
    warn "PLAN: no complete image set for $TARGET -> the affected services are"
    warn "      REBUILT from the rolled-back source. Slower, and the result is"
    warn "      only as reproducible as the sources that commit pins."
fi
echo

read -rp "Continue? [y/N] " yn
[[ "$yn" == "y" || "$yn" == "Y" ]] || { echo "Aborted."; exit 0; }

log "resetting tree to $TARGET"
git reset --hard "$TARGET"

# Deliberately NOT `docker compose pull`: a rollback must not drag in newer
# upstream images. Pinned tags (postgres:16-alpine, keycloak:24.0, …) are
# already local; pulling here would move `:latest` images forward while the
# code moves backward.

if [[ "$MODE" == "restore" ]]; then
    log "restoring images built from $TARGET"
    bash "$IMAGES" restore "$TARGET"
    log "recreating containers"
    docker compose up -d --force-recreate
else
    log "rebuilding from source at $TARGET (this takes a while)"
    docker compose build
    bash "$IMAGES" tag || warn "tagging failed — next rollback will rebuild again"
    log "recreating containers"
    docker compose up -d --force-recreate
fi

# Flush nginx's resolver cache — recreated containers get new IPs and nginx
# would hold the old ones for up to valid=5s (same reason as rebuild.sh).
if docker compose ps --status running --services 2>/dev/null | grep -qx nginx; then
    docker compose exec -T nginx nginx -t >/dev/null 2>&1 && \
        docker compose exec -T nginx nginx -s reload && log "nginx reloaded"
fi

echo
log "rolled back to $TARGET."
log "verify:  bash scripts/health-check.sh"
log "undo:    git reflog  (code)  ·  images kept as :pre-rollback"
