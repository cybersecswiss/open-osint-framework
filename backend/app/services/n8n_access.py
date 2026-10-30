"""Operator toggle: is the n8n editor reachable from OUTSIDE (via nginx)?

Stored as a plain flag in the license-server platform-settings KV bag
(key ``n8n_external_access``). n8n keeps running regardless — this only
gates the public ``/n8n/`` route (nginx ``auth_request`` →
``/api/v1/n8n-gate``), so the backend can still call n8n webhooks
internally while external editor access is off.

Default when unset = DISABLED (fail-closed / secure). The operator flips
it in the Product-Owner console → Settings.
"""
from __future__ import annotations

import time

import httpx

from app.config import settings

_KEY = "n8n_external_access"
_TRUTHY = {"true", "1", "on", "yes"}
_cache: dict[str, tuple[float, bool]] = {}
_TTL = 5.0  # short — the gate is hit on every /n8n/ request


async def _fetch() -> bool:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    headers = {"X-Internal-Key": settings.internal_secret}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers=headers)
        r.raise_for_status()
        val = (r.json() or {}).get(_KEY, "")
    return str(val).strip().lower() in _TRUTHY


async def is_enabled(force: bool = False) -> bool:
    now = time.time()
    if not force and "f" in _cache and now - _cache["f"][0] < _TTL:
        return _cache["f"][1]
    try:
        v = await _fetch()
    except Exception:  # noqa: BLE001 — store unreachable → fail CLOSED (deny)
        v = False
    _cache["f"] = (now, v)
    return v


async def set_enabled(enabled: bool) -> None:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    headers = {"X-Internal-Key": settings.internal_secret}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(url, headers=headers,
                        json={"values": {_KEY: "true" if enabled else "false"}})
        r.raise_for_status()
    _cache.pop("f", None)
