"""
One-shot INTERACTIVE Telethon authentication helper for module-telegram.

The module uses a pre-authorized *file* session. This script (re)creates
that session file. It is NOT part of the running container — run it once
by hand whenever the session is missing or has been revoked server-side
(symptom: /health shows "telegram_authenticated": false and get_me()
returns None).

Usage (writes into the bind-mounted session/ dir the container reads):

    cd /opt/oof/modules/telegram
    TELEGRAM_API_ID=... TELEGRAM_API_HASH=... TELEGRAM_PHONE=+41... \
        python3 authenticate.py
    # enter the login code Telegram sends to that phone (and 2FA if set)

Then:  docker compose up -d --force-recreate module-telegram

The API_ID/API_HASH must match the ones in the framework .env (the same
app the session is bound to). Requires `pip install telethon`.
"""
import asyncio
import os

from telethon import TelegramClient

SESSION = os.getenv("TELEGRAM_SESSION_NAME", "session/osint_scanner")


async def main() -> None:
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")
    if not api_id or not api_hash:
        raise SystemExit("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")
    client = TelegramClient(SESSION, int(api_id), api_hash)
    await client.start(phone=phone)
    me = await client.get_me()
    print(f"Authenticated as id={me.id} username=@{me.username} phone={me.phone}")
    print(f"Session written to {SESSION}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
