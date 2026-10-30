"""Operator-tunable AI-function settings, stored in the license-server
platform-settings KV bag (same store as the API keys + the n8n toggle).

Currently: ``ai_max_entities`` — how many (most-relevant-first) entities of a
case are sent to the AI. Bigger = more context but slower / costlier;
smaller = faster. Changeable in the Product-Owner console → Settings → AI,
no rebuild. Cached briefly so the ai-link hot path doesn't hit the store
every run.
"""
from __future__ import annotations

import time

import httpx

from app.config import settings

_KEY = "ai_max_entities"
_DEFAULT = 150
_MIN, _MAX = 10, 500
_cache: dict[str, tuple[float, int]] = {}
_TTL = 20.0


def _clamp(n: int) -> int:
    return max(_MIN, min(_MAX, n))


async def get_max_entities(force: bool = False) -> int:
    now = time.time()
    if not force and "v" in _cache and now - _cache["v"][0] < _TTL:
        return _cache["v"][1]
    val = _DEFAULT
    try:
        url = f"{settings.license_server_url}/api/v1/platform-settings"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
            r.raise_for_status()
            raw = (r.json() or {}).get(_KEY, "")
        if str(raw).strip():
            val = _clamp(int(str(raw).strip()))
    except Exception:  # noqa: BLE001 — store down / unset → default
        val = _DEFAULT
    _cache["v"] = (now, val)
    return val


async def set_max_entities(n: int) -> int:
    val = _clamp(int(n))
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(url, headers={"X-Internal-Key": settings.internal_secret},
                        json={"values": {_KEY: str(val)}})
        r.raise_for_status()
    _cache.pop("v", None)
    return val
