#!/bin/bash
# =====================================================================
# OOF — publish a data-server release for customer servers
#
#     bash scripts/release.sh                       # tarball mode (default)
#     bash scripts/release.sh registry.example.org/oof [version]
#
# A release is a FROZEN set of files in data-agent/dist/ (gitignored),
# served by nginx at https://<framework>/agent/ :
#
#   version.json                  manifest: version, commit, image, SHA-256 of every file
#   install.sh update.sh backup.sh
#   docker-compose.yml            the customer compose, image reference pinned
#   postgres-init.sh Caddyfile.template keycloak/realm-template.json
#   agent-image-<version>.tar.gz  the data-server image (tarball mode only)
#
# data-agent/install.sh and update.sh on a customer server refuse every
# file whose checksum differs from the manifest. Because dist/ is a copy,
# editing a script in the repository never changes what customers fetch
# until the next release.
#
# Tarball mode needs no registry: the customer downloads the image from
# /agent/ and `docker load`s it. Registry mode pushes instead.
#
# Version: the VERSION file (scheme YYYY.MM.N) unless passed explicitly.
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=lib/guide.sh
source "$SCRIPT_DIR/lib/guide.sh"
GUIDE_TOTAL=5

REGISTRY="${1:-}"
VERSION="${2:-$(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo "")}"
AGENT_DIR="$PROJECT_DIR/data-agent"
DIST="$AGENT_DIR/dist"
MODE=tarball; [[ -n "$REGISTRY" ]] && MODE=registry

cd "$PROJECT_DIR"
[[ -f .env ]] || fail "No .env — run setup.sh first."
# shellcheck disable=SC1091
set -a; source .env; set +a

banner "OOF — $(L "Publish a data-server release" "Datenserver-Release veröffentlichen")" "Version ${VERSION:-?} · $MODE"
[[ -n "$VERSION" ]] || fail "No version — VERSION file missing."
[[ "$VERSION" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]+$ ]] || fail "Version '$VERSION' does not match YYYY.MM.N."

# =====================================================================
step "$(L "Release gate" "Freigabeprüfung")"
# =====================================================================
if git rev-parse --git-dir >/dev/null 2>&1; then
    COMMIT="$(git rev-parse --short HEAD)"
    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        DIRTY="-dirty"
        warn "$(L "Working tree has uncommitted changes — the manifest records the commit as" "Arbeitsverzeichnis hat nicht eingecheckte Änderungen — das Manifest vermerkt den Commit als") $COMMIT-dirty"
        [[ "${ALLOW_DIRTY:-0}" == "1" ]] || confirm "$(L "Publish anyway?" "Trotzdem veröffentlichen?")" N || fail "$(L "Aborted." "Abgebrochen.")"
    else
        DIRTY=""
    fi
    COMMIT="$COMMIT$DIRTY"
else
    COMMIT="source"
    note "$(L "Not a git checkout — commit recorded as 'source'." "Kein Git-Checkout — Commit wird als 'source' vermerkt.")"
fi
ok "Commit $COMMIT"


# =====================================================================
step "$(L "Building the data-server image" "Datenserver-Image bauen")"
# =====================================================================
STAGE="$(mktemp -d "$AGENT_DIR/.dist-stage.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
TARBALL_NAME=""
if [[ "$MODE" == "registry" ]]; then
    IMAGE="${REGISTRY%/}/oof-data-agent:${VERSION}"
    docker build -q --build-arg AGENT_VERSION="$VERSION" -t "$IMAGE" -t "${REGISTRY%/}/oof-data-agent:latest" "$AGENT_DIR" | sed 's/^/     /'
    docker push -q "$IMAGE"; docker push -q "${REGISTRY%/}/oof-data-agent:latest"
    DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || echo "")"
    ok "$(L "pushed" "gepusht") $IMAGE"
else
    # No registry host in the tag: a customer compose must never try to
    # pull from somewhere.
    IMAGE="oof-data-agent:${VERSION}"
    TARBALL_NAME="agent-image-${VERSION}.tar.gz"
    docker build -q --build-arg AGENT_VERSION="$VERSION" -t "$IMAGE" -t oof-data-agent:latest "$AGENT_DIR" | sed 's/^/     /'
    info "$(L "Packing the image (a few minutes) …" "Image wird gepackt (einige Minuten) …")"
    docker save "$IMAGE" | gzip -6 > "$STAGE/$TARBALL_NAME"
    gzip -t "$STAGE/$TARBALL_NAME" || fail "The image tarball is not a readable gzip archive."
    [[ $(stat -c%s "$STAGE/$TARBALL_NAME") -gt 10000000 ]] || fail "The image tarball is implausibly small — save incomplete."
    DIGEST="$(docker inspect --format='{{.Id}}' "$IMAGE")"
    ok "$(du -h "$STAGE/$TARBALL_NAME" | cut -f1) — $TARBALL_NAME"
fi

# =====================================================================
step "$(L "Assembling the release files" "Release-Dateien zusammenstellen")"
# =====================================================================
mkdir -p "$STAGE/keycloak"
cp "$AGENT_DIR/install.sh" "$AGENT_DIR/update.sh" "$AGENT_DIR/backup.sh" \
   "$AGENT_DIR/postgres-init.sh" "$AGENT_DIR/Caddyfile.template" "$STAGE/"
cp "$AGENT_DIR/keycloak/realm-template.json" "$STAGE/keycloak/"
python3 - "$AGENT_DIR/docker-compose.customer.yml" "$STAGE/docker-compose.yml" "$IMAGE" <<'PY'
import re, sys
src, dst, image = sys.argv[1:4]
text = open(src, encoding="utf-8").read()
new, n = re.subn(r"^([ \t]*image:).*\{\{AGENT_IMAGE\}\}.*$",
                 lambda m: f"{m.group(1)} {image}   # {{{{AGENT_IMAGE}}}} set by scripts/release.sh",
                 text, count=1, flags=re.M)
if n != 1:
    sys.exit("marker {{AGENT_IMAGE}} not found in docker-compose.customer.yml")
open(dst, "w", encoding="utf-8").write(new)
PY
ok "$(L "files staged, image pinned to" "Dateien bereitgestellt, Image festgelegt auf") $IMAGE"

# =====================================================================
step "$(L "Writing the manifest" "Manifest schreiben")"
# =====================================================================
CHANGES_JSON="$(python3 - "$PROJECT_DIR/frontend/public/wiki/changelog.json" "$VERSION" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except (FileNotFoundError, ValueError):
    print("{}"); sys.exit(0)
rel = next((r for r in data.get("releases") or [] if r.get("version") == sys.argv[2]), None)
out = {}
for it in (rel or {}).get("items") or []:
    for lang, text in (it.get("text") or {}).items():
        out.setdefault(lang, []).append(text)
print(json.dumps(out, ensure_ascii=False))
PY
)"
STAGE="$STAGE" VERSION="$VERSION" COMMIT="$COMMIT" MODE="$MODE" IMAGE="$IMAGE" \
DIGEST="${DIGEST:-}" TARBALL="$TARBALL_NAME" CHANGES="${CHANGES_JSON:-{\}}" python3 - <<'PY'
import datetime, hashlib, json, os, pathlib
stage = pathlib.Path(os.environ["STAGE"])
files = {}
for p in sorted(stage.rglob("*")):
    if p.is_file():
        files[str(p.relative_to(stage))] = hashlib.sha256(p.read_bytes()).hexdigest()
manifest = {
    "version": os.environ["VERSION"],
    "released_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "commit": os.environ["COMMIT"],
    "delivery": os.environ["MODE"],
    "agent_image": os.environ["IMAGE"],
    "agent_digest": os.environ["DIGEST"],
    "agent_tarball": os.environ["TARBALL"],
    "files": files,
    "changes": json.loads(os.environ["CHANGES"] or "{}"),
}
(stage / "version.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
PY
ok "version.json ($(python3 -c "import json;print(len(json.load(open('$STAGE/version.json'))['files']))" ) $(L "files" "Dateien"))"

# Swap in atomically-ish: the old release stays served until the new one
# is complete. dist/ is a directory bind mount, so nginx sees the new
# files without a restart.
mkdir -p "$DIST"
find "$DIST" -mindepth 1 -delete
cp -a "$STAGE/." "$DIST/"
chmod -R a+rX "$DIST"
ok "$(L "published to" "veröffentlicht nach") data-agent/dist/"

# =====================================================================
step "$(L "Verifying as a customer would" "Prüfen wie ein Kundenserver")"
# =====================================================================
BASE="${FRAMEWORK_URL:-https://127.0.0.1:${PUBLIC_HTTPS_PORT:-443}}"
MISMATCH=0
while IFS='=' read -r name want; do
    got="$(curl -skf "$BASE/agent/$name" | sha256sum | cut -d' ' -f1)"
    if [[ "$got" == "$want" ]]; then
        printf '   %s✓%s /agent/%s\n' "$C_GREEN" "$C_RESET" "$name"
    else
        printf '   %s✗%s /agent/%s\n' "$C_RED" "$C_RESET" "$name"; MISMATCH=1
    fi
done < <(python3 -c "
import json
for k, v in json.load(open('$DIST/version.json'))['files'].items(): print(f'{k}={v}')")
curl -skf "$BASE/agent/version.json" >/dev/null || MISMATCH=1
[[ $MISMATCH -eq 0 ]] || fail "$(L "What nginx serves differs from the manifest. Is the stack running? (docker compose ps nginx)" "Was nginx ausliefert, weicht vom Manifest ab. Läuft der Stack? (docker compose ps nginx)")"

PUB="${PUBLIC_ORIGIN:-${PUBLIC_SCHEME:-https}://${PUBLIC_HOST}}"
CK=""   # self-signed framework certificate → customers need curl -k once
openssl verify certs/server.crt >/dev/null 2>&1 || CK="k"
summary_ok "Release $VERSION $(L "published" "veröffentlicht")"
cat <<EOF
   Manifest:   $PUB/agent/version.json
   $(L "New customer server:" "Neuer Kundenserver:")
       curl -fsSL$CK $PUB/agent/install.sh -o install.sh && sudo bash install.sh
   $(L "Existing customer servers:" "Bestehende Kundenserver:")
       cd /opt/oof-agent && sudo ./update.sh

EOF
