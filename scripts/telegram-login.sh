#!/bin/bash
# =============================================================
# Guided Telegram login — writes TELEGRAM_SESSION into the encrypted
# key store WITHOUT ever printing it.
#
# Why this exists next to scripts/telegram-session.py
# ---------------------------------------------------
# That script predates the Owner-console key panel: it asks the operator to
# supply api_id/api_hash by hand and then prints the StringSession so it can
# be pasted into `.env`. Both halves are wrong once the key store is used —
# the credentials already live encrypted in the store, and a session string
# on the terminal is a password-equivalent sitting in scrollback and shell
# history.
#
# This one reads the credentials from the store, runs the one interactive
# step Telegram requires (phone number + the code Telegram sends you), and
# writes the resulting session straight back into the store.
#
# WHAT IT DOES NOT DO: module-telegram (the deep scanner on :8090) uses a
# session FILE, not a string, and the panel cannot supply it — see
# `--file` below and docs/operations.en.md → "Telegram deep scanner".
#
# Usage
#   bash scripts/telegram-login.sh          # StringSession -> key store
#   bash scripts/telegram-login.sh --file   # ALSO re-auth module-telegram's
#                                           # session file (second login)
#
# The account you log in with is the account every authenticated Telegram
# collection will act as. Use a dedicated one.
# =============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

WANT_FILE=0
[[ "${1:-}" == "--file" ]] && WANT_FILE=1

log()  { printf "\033[1;34m[tg]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[tg]\033[0m %s\n" "$*" >&2; }

# Telegram asks for a phone number and a login code. There is no way around
# that and no way to script it — fail loudly rather than hang on a prompt
# nobody can answer.
if [[ ! -t 0 ]]; then
    err "This needs a real terminal: Telegram asks for your phone number and"
    err "the code it sends you. Run it from an interactive shell."
    exit 1
fi

# --- 1. credentials, from the store, never echoed --------------------
log "reading TELEGRAM_API_ID / TELEGRAM_API_HASH from the key store…"
CREDS="$(docker compose exec -T api python -c "
import asyncio, json
from app.services.api_keys import load_keys
k = asyncio.run(load_keys())
print(json.dumps({'id': k.get('TELEGRAM_API_ID',''), 'hash': k.get('TELEGRAM_API_HASH','')}))
" 2>/dev/null | tr -d '\r')"
API_ID="$(printf '%s' "$CREDS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
API_HASH="$(printf '%s' "$CREDS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["hash"])')"

if [[ -z "$API_ID" || -z "$API_HASH" ]]; then
    err "TELEGRAM_API_ID / TELEGRAM_API_HASH are not set."
    err "Set them first: /glbadmin → Settings → API keys → Telegram."
    err "You get both from https://my.telegram.org/apps (API development tools)."
    exit 1
fi
log "credentials found (id ends …${API_ID: -3})."

# --- 2. the one interactive step -------------------------------------
log "starting the Telegram login. You will be asked for:"
log "   • your phone number in international format, e.g. +41790000000"
log "   • the login code Telegram sends to that account"
log "   • your 2FA password, if the account has one"
echo

docker compose exec \
    -e TG_ID="$API_ID" -e TG_HASH="$API_HASH" \
    module-messenger python - <<'PY'
import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

with TelegramClient(StringSession(), int(os.environ["TG_ID"]),
                    os.environ["TG_HASH"]) as client:
    me = client.get_me()
    # Written to a file inside the container instead of printed: the string
    # is password-equivalent and has no business in terminal scrollback.
    with open("/tmp/tg_session.txt", "w") as fh:
        fh.write(client.session.save())
    print(f"\nlogged in as: {me.first_name or ''} (@{me.username or '—'}, id={me.id})")
PY

SESSION="$(docker compose exec -T module-messenger sh -lc 'cat /tmp/tg_session.txt 2>/dev/null' | tr -d '\r\n')"
docker compose exec -T module-messenger sh -lc 'rm -f /tmp/tg_session.txt' >/dev/null 2>&1 || true

if [[ -z "$SESSION" ]]; then
    err "no session produced — login aborted or failed. Nothing was stored."
    exit 1
fi

# --- 3. store it, encrypted ------------------------------------------
log "storing TELEGRAM_SESSION in the key store (Fernet-encrypted)…"
docker compose exec -T -e TG_SESSION="$SESSION" api python -c "
import asyncio, os
from app.services.api_keys import save_keys
asyncio.run(save_keys({'TELEGRAM_SESSION': os.environ['TG_SESSION']}))
print('stored')
"
log "done. The panel will now show TELEGRAM_SESSION as set."
log "No restart needed — modules read the store per request."

# --- 4. optional: the deep scanner's session FILE --------------------
if [[ "$WANT_FILE" == "1" ]]; then
    echo
    log "second login for module-telegram (:8090). It uses a session FILE,"
    log "which the panel cannot hold — this is a separate Telegram login."
    docker compose exec \
        -e TG_ID="$API_ID" -e TG_HASH="$API_HASH" \
        module-telegram python - <<'PY'
import os
from telethon.sync import TelegramClient
name = os.getenv("TELEGRAM_SESSION_NAME", "osint_scanner")
with TelegramClient(f"/app/session/{name}", int(os.environ["TG_ID"]),
                    os.environ["TG_HASH"]) as client:
    me = client.get_me()
    print(f"\nsession file written for: {me.first_name or ''} (@{me.username or '—'})")
PY
    log "recreating module-telegram so it picks the new session up…"
    docker compose up -d --force-recreate module-telegram
fi

echo
log "verify in the Owner console: /glbadmin → Settings → API keys → Telegram"
log "→ the 'Test' button. It opens the stored session in Telethon and reports"
log "  the account it belongs to."
log ""
log "NOTE: module-messenger's /health keeps reporting"
log '  "telegram_deep_collection": false'
log "and that is CORRECT — the gate reflects the container's own .env, while"
log "panel keys are resolved per run request. Do not use it to check this."
