#!/bin/bash
# =============================================================
# OOF — commit-tagged images (the actual rollback net)
#
# Why this exists
# ---------------
# Every locally built image carried ONLY `:latest`. A rebuild overwrote
# that tag, the previous image lost its name and survived — unnamed and
# unfindable — until the next prune. So there was no "last working state"
# to go back to: `rollback.sh` reset the git tree but then recreated the
# containers from the SAME images, i.e. from the code it had just rolled
# back. Application code is baked into the images (only wiki/, config/ and
# session/ are bind-mounted), so the rollback did not roll back anything
# that runs.
#
# This script gives each build a second tag naming the commit it was built
# from, keeps the newest N of them per service, and lets rollback.sh put a
# named generation back on `:latest`.
#
# Disk cost is bounded on purpose: KEEP=2 means one generation back per
# service, nothing more. Image layers are shared, so the real cost is the
# unique part of each image (a few hundred MB for the big ones). A large
# build cache does not make a rollback possible — an extra generation of
# images buys the thing people think the cache is.
#
# A build from a dirty working tree is tagged `<sha>-dirty`, because such an
# image cannot be reproduced from that commit and must not claim it can.
#
# Usage
#   image-versions.sh tag [service...]        tag :latest with the current commit
#   image-versions.sh list [service...]       which generations exist per service
#   image-versions.sh prune [N]               keep newest N commit tags (default 2)
#   image-versions.sh check <commit> [svc...] exit 0 only if ALL have that commit
#   image-versions.sh restore <commit> [svc...] put that generation back on :latest
#
# `restore` never destroys the state it replaces: the outgoing :latest is
# tagged `:pre-rollback` first, so a rollback is itself reversible.
# =============================================================
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJECT_DIR"

KEEP_DEFAULT="${IMAGE_KEEP:-2}"

log()  { printf "\033[1;34m[images]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[images]\033[0m %s\n" "$*" >&2; }
err()  { printf "\033[1;31m[images]\033[0m %s\n" "$*" >&2; }

# --- service -> image repository ------------------------------------
# Only services with a `build:` section are ours to version; pulled images
# (postgres, redis, keycloak, …) already carry upstream version tags.
_build_map() {
    docker compose config --format json 2>/dev/null | python3 -c '
import json, sys
c = json.load(sys.stdin)
project = c.get("name", "oof")
for svc, v in sorted(c["services"].items()):
    if "build" not in v:
        continue
    # An explicit image: wins; otherwise compose derives <project>-<service>.
    repo = v.get("image", f"{project}-{svc}").rsplit(":", 1)[0]
    print(f"{svc}\t{repo}")
'
}

# Resolve the requested services (or all buildable ones) to "svc<TAB>repo".
_selected() {
    local map; map="$(_build_map)"
    if [[ $# -eq 0 ]]; then
        printf '%s\n' "$map"
        return
    fi
    local svc line
    for svc in "$@"; do
        line="$(grep -P "^${svc}\t" <<<"$map" || true)"
        if [[ -z "$line" ]]; then
            warn "service '$svc' has no build section — skipped (pulled image?)"
            continue
        fi
        printf '%s\n' "$line"
    done
}

# Current commit, marked when the tree it was built from was dirty.
_version() {
    local sha dirty=""
    sha="$(git rev-parse --short HEAD 2>/dev/null)" || { err "not a git repo"; exit 1; }
    if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        dirty="-dirty"
    fi
    printf '%s%s' "$sha" "$dirty"
}

# Tags of $1 that look like a commit generation (7+ hex, optional -dirty).
# ONLY these are auto-pruned. Manually pinned tags (`baseline-*`) and the
# safety copy `pre-rollback` are deliberately not matched: a human pinned
# them, so a retention rule must not silently drop them.
_commit_tags() {
    docker images "$1" --format '{{.Tag}}' 2>/dev/null |
        grep -Ex '[0-9a-f]{7,40}(-dirty)?' || true
}

# Everything that can be rolled back to — commit generations plus the
# manually pinned ones. Display only; never fed to prune.
_restorable_tags() {
    docker images "$1" --format '{{.Tag}}' 2>/dev/null |
        grep -Ev '^(latest|<none>)$' || true
}

# --- commands --------------------------------------------------------

cmd_tag() {
    local ver; ver="$(_version)"
    local svc repo count=0
    while IFS=$'\t' read -r svc repo; do
        [[ -n "$repo" ]] || continue
        if ! docker image inspect "$repo:latest" >/dev/null 2>&1; then
            warn "$svc: no $repo:latest yet — build it first, nothing tagged"
            continue
        fi
        docker tag "$repo:latest" "$repo:$ver"
        log "$svc -> $repo:$ver"
        count=$((count + 1))
    done < <(_selected "$@")
    [[ $count -gt 0 ]] && log "tagged $count image(s) as $ver"
    return 0
}

cmd_list() {
    local svc repo tags cur
    printf '%-26s %-12s %s\n' "SERVICE" "RUNNING" "AVAILABLE GENERATIONS"
    while IFS=$'\t' read -r svc repo; do
        [[ -n "$repo" ]] || continue
        cur="$(docker image inspect "$repo:latest" --format '{{.Id}}' 2>/dev/null | cut -c8-19)"
        tags="$(_restorable_tags "$repo" | tr '\n' ' ')"
        printf '%-26s %-12s %s\n' "$svc" "${cur:--}" "${tags:-(none)}"
    done < <(_selected "$@")
}

cmd_prune() {
    # First arg is the retention count only if it IS a count; otherwise every
    # arg is a service. Without the shift the count was passed on as a service
    # name, `_selected` matched nothing, and prune silently kept everything —
    # exactly the failure mode a retention rule must not have.
    local keep="$KEEP_DEFAULT"
    if [[ "${1:-}" =~ ^[0-9]+$ ]]; then keep="$1"; shift; fi
    local svc repo tag n removed=0
    while IFS=$'\t' read -r svc repo; do
        [[ -n "$repo" ]] || continue
        n=0
        # Newest first: docker images sorts by creation, which for a build
        # tag IS the build time.
        while read -r tag; do
            [[ -n "$tag" ]] || continue
            n=$((n + 1))
            if [[ $n -gt $keep ]]; then
                docker rmi "$repo:$tag" >/dev/null 2>&1 && {
                    log "dropped $repo:$tag"
                    removed=$((removed + 1))
                }
            fi
        done < <(_commit_tags "$repo")
    done < <(_selected "$@")
    log "kept newest $keep generation(s) per service; removed $removed tag(s)"
}

cmd_check() {
    local want="${1:-}"; shift || true
    [[ -n "$want" ]] || { err "check needs a commit"; exit 2; }
    want="$(git rev-parse --short "$want" 2>/dev/null || printf '%s' "$want")"
    local svc repo missing=0 have=0
    while IFS=$'\t' read -r svc repo; do
        [[ -n "$repo" ]] || continue
        if docker image inspect "$repo:$want" >/dev/null 2>&1; then
            have=$((have + 1))
        else
            missing=$((missing + 1))
            printf '  missing: %s (%s:%s)\n' "$svc" "$repo" "$want" >&2
        fi
    done < <(_selected "$@")
    log "commit $want: $have image(s) present, $missing missing"
    [[ $missing -eq 0 ]]
}

cmd_restore() {
    local want="${1:-}"; shift || true
    [[ -n "$want" ]] || { err "restore needs a commit"; exit 2; }
    want="$(git rev-parse --short "$want" 2>/dev/null || printf '%s' "$want")"
    local svc repo count=0
    while IFS=$'\t' read -r svc repo; do
        [[ -n "$repo" ]] || continue
        if ! docker image inspect "$repo:$want" >/dev/null 2>&1; then
            warn "$svc: no image for $want — left untouched"
            continue
        fi
        # Keep the outgoing state reachable even if it was never tagged.
        if docker image inspect "$repo:latest" >/dev/null 2>&1; then
            docker tag "$repo:latest" "$repo:pre-rollback"
        fi
        docker tag "$repo:$want" "$repo:latest"
        log "$svc <- $want"
        count=$((count + 1))
    done < <(_selected "$@")
    log "restored $count image(s) to :latest (previous state kept as :pre-rollback)"
}

case "${1:-}" in
    tag)     shift; cmd_tag "$@" ;;
    list)    shift; cmd_list "$@" ;;
    prune)   shift; cmd_prune "$@" ;;
    check)   shift; cmd_check "$@" ;;
    restore) shift; cmd_restore "$@" ;;
    *)
        sed -n '/^# Usage/,/^# =\{10,\}/p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
