#!/usr/bin/env bash
# Each module builds from its own narrow Docker context, so shared files
# (SSRF guard, module contract, …) exist as copies. This check fails if any
# copy drifts from its source. Run from anywhere; CI runs it on every push.
#
# Documented exception: modules/telegram/schemas.py appends its own option
# models below the shared contract (see modules/base/schemas.py).
set -euo pipefail
cd "$(dirname "$0")/.."

rc=0
check() {
  local src=$1 pattern=$2 f
  while IFS= read -r f; do
    [[ "$f" == "$src" ]] && continue
    [[ "$pattern" == "*/schemas.py" && "$f" == modules/telegram/schemas.py ]] && continue
    if ! cmp -s "$src" "$f"; then
      echo "DRIFT: $f differs from $src" >&2
      rc=1
    fi
  done < <(git ls-files -- "$pattern")
}

check modules/base/safe_fetch.py      "*/safe_fetch.py"
check modules/base/schemas.py         "*/schemas.py"
check modules/base/handle_variants.py "*/handle_variants.py"
check backend/app/database.py         "*/app/database.py"

if (( rc == 0 )); then echo "shared copies: all identical"; fi
exit "$rc"
