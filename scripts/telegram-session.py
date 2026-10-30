#!/usr/bin/env python3
"""
Generate a Telethon StringSession for the optional Telegram deep-collection
path of module-messenger.

Run this ONCE, interactively, on any machine with Python + telethon and a
Telegram account. It performs the one-time phone/SMS login and prints a
StringSession you paste into .env as TELEGRAM_SESSION (plus set
TELEGRAM_API_ID / TELEGRAM_API_HASH from https://my.telegram.org/apps).

    pip install telethon
    TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=abc... python3 telegram-session.py

The session string is a credential — treat it like a password. Anyone with
it can act as your Telegram account. Prefer a dedicated OSINT collection
account, not a personal one.
"""
import os
import sys

try:
    from telethon.sync import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    sys.exit("telethon not installed — run: pip install telethon")

api_id = os.environ.get("TELEGRAM_API_ID")
api_hash = os.environ.get("TELEGRAM_API_HASH")
if not api_id or not api_hash:
    sys.exit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH env vars first "
             "(get them from https://my.telegram.org/apps).")

with TelegramClient(StringSession(), int(api_id), api_hash) as client:
    print("\n=== Your TELEGRAM_SESSION (paste into .env) ===\n")
    print(client.session.save())
    print("\n===============================================\n")
    print("Now set in /opt/oof/.env:")
    print(f"  TELEGRAM_API_ID={api_id}")
    print("  TELEGRAM_API_HASH=<your hash>")
    print("  TELEGRAM_SESSION=<the string above>")
    print("Optionally: TELEGRAM_TRANSLATE=true, TELEGRAM_DOWNLOAD_MEDIA=true")
    print("Then: docker compose up -d --force-recreate module-messenger")
