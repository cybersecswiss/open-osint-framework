#!/usr/bin/env python3
"""
Generate the value for the Global-Admin → Settings → Google → "GHunt Google
Session" field, so email → Google-account OSINT (the `ghunt` tool) works.

Run this on ANY machine (or `docker run -it python:3.12-slim bash`) whose
browser is logged into a DEDICATED BURNER Google account:

    pip install ghunt          # or: pipx install ghunt
    python3 ghunt-session.py

It launches `ghunt login` — complete the cookie step there (easiest: install
the "GHunt Companion" browser extension, click it, paste the base64 it gives).
Then this script prints the value to paste into the framework:

  • MASTER TOKEN  (recommended)  — one line starting "aas_et/…", long-lived
    (does NOT expire in weeks like cookies; only when the account revokes it).
  • BASE64 CREDS  (fallback)     — the whole creds.m encoded, also accepted.

Paste EITHER into the "GHunt Google Session" field and save. The runner
auto-detects which one you gave.

⚠️ Use a throwaway Google account — GHunt operates AS that account and Google
may lock it. Never a personal/work account.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

CREDS_PATH = Path.home() / ".malfrats" / "ghunt" / "creds.m"


def main() -> int:
    # 1) Make sure ghunt is available.
    try:
        subprocess.run(["ghunt", "--help"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("GHunt is not installed. Install it first:\n"
              "    pip install ghunt      (or: pipx install ghunt)\n"
              "then re-run this script.", file=sys.stderr)
        return 1

    # 2) Interactive login (operator completes the browser-cookie step).
    print("Launching `ghunt login` — complete the cookie step there "
          "(GHunt Companion extension → paste base64).\n", file=sys.stderr)
    subprocess.run(["ghunt", "login"])

    # 3) Read the produced creds.m and extract the master token.
    if not CREDS_PATH.is_file():
        print(f"\n[-] No creds file at {CREDS_PATH} — login did not complete.",
              file=sys.stderr)
        return 1
    raw = CREDS_PATH.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(base64.b64decode(raw).decode())
        master = data.get("android", {}).get("master_token", "")
    except Exception as e:  # noqa: BLE001
        print(f"\n[-] Could not parse creds.m: {e}", file=sys.stderr)
        return 1

    print("\n" + "=" * 72)
    if master:
        print("MASTER TOKEN (recommended — paste this one line into the field):\n")
        print(master)
    print("\n" + "-" * 72)
    print("BASE64 CREDS (fallback — the whole session, also accepted):\n")
    print(raw)
    print("=" * 72)
    print("\nPaste EITHER value into Global-Admin → Settings → Google → "
          "'GHunt Google Session' and save.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
