#!/usr/bin/env python3
"""
Re-encrypt the stored OSINT API keys from one KEK to another.

Why this exists: the stored keys are Fernet ciphertext whose key is derived
from a single secret. Before this script there was NO migration path — the
only way to change that secret was to lose every stored key and re-enter it
by hand in /glbadmin → Settings. That made rotation effectively impossible,
which is the same as never rotating.

Run it INSIDE the api container (it needs the license-server on the internal
network and the same Python deps):

    docker compose exec -T api python /app/scripts/rekey-apikeys.py \
        --old "$OLD_KEK" --new "$NEW_KEK"

Then put NEW_KEK into .env as APIKEY_KEK and recreate the api:

    bash scripts/rebuild.sh api

Safe to re-run: values that already decrypt with --new are left alone, and
a --dry-run pass tells you exactly what would change without writing.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import sys

import httpx
from cryptography.fernet import Fernet, InvalidToken

sys.path.insert(0, "/app")

from app.config import settings  # noqa: E402
from app.services.api_keys import REGISTRY_BY_NAME  # noqa: E402

_FERNET_PREFIX = "gAAAAA"


def _fernet(secret: str) -> Fernet:
    digest = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


async def _fetch(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.get(f"{settings.license_server_url}/api/v1/platform-settings",
                         headers={"X-Internal-Key": settings.internal_secret})
    r.raise_for_status()
    return r.json() or {}


async def _store(client: httpx.AsyncClient, values: dict[str, str]) -> None:
    r = await client.put(f"{settings.license_server_url}/api/v1/platform-settings",
                         headers={"X-Internal-Key": settings.internal_secret},
                         json={"values": values})
    r.raise_for_status()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="current KEK (APIKEY_KEK, or API_SECRET_KEY if never split)")
    ap.add_argument("--new", required=True, help="new KEK to re-encrypt to")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if args.old == args.new:
        print("old and new KEK are identical — nothing to do")
        return 0

    old_f, new_f = _fernet(args.old), _fernet(args.new)

    async with httpx.AsyncClient(timeout=30) as client:
        raw = await _fetch(client)

        out: dict[str, str] = {}
        stats = {"rekeyed": 0, "already_new": 0, "plaintext": 0, "undecryptable": 0, "skipped": 0}

        for name, value in raw.items():
            # Only registry keys are secrets; other platform settings (feed
            # intervals, toggles) are plain values and must not be touched.
            if name not in REGISTRY_BY_NAME or not value:
                stats["skipped"] += 1
                continue
            try:
                plain = old_f.decrypt(value.encode()).decode()
                stats["rekeyed"] += 1
            except (InvalidToken, ValueError):
                try:
                    new_f.decrypt(value.encode())
                    stats["already_new"] += 1        # a previous run did this one
                    continue
                except (InvalidToken, ValueError):
                    if value.startswith(_FERNET_PREFIX):
                        # Ciphertext that neither key opens — do NOT overwrite
                        # it; the operator must re-enter that key by hand.
                        print(f"  !! {name}: ciphertext decrypts with neither KEK — left untouched")
                        stats["undecryptable"] += 1
                        continue
                    plain = value                    # legacy plaintext row
                    stats["plaintext"] += 1
            out[name] = new_f.encrypt(plain.encode()).decode()
            print(f"  ok {name}")

        print(f"\n{stats}")
        if not out:
            print("nothing to write")
            return 0
        if args.dry_run:
            print(f"DRY RUN — would rewrite {len(out)} key(s)")
            return 0

        await _store(client, out)
        print(f"wrote {len(out)} re-encrypted key(s)")

        # Prove it: read back and decrypt with the NEW key only.
        check = await _fetch(client)
        bad = []
        for name in out:
            try:
                new_f.decrypt((check.get(name) or "").encode())
            except (InvalidToken, ValueError):
                bad.append(name)
        if bad:
            print(f"VERIFY FAILED for: {bad}")
            return 1
        print("verify ok — every rewritten key decrypts with the new KEK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
