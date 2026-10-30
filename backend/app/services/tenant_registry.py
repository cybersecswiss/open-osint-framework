"""
Resolves tenant -> data agent URL.

Lookup order:
  1. Per-tenant env var `AGENT_URL_<TENANT-UPPER>` (no slashes; e.g.
     `AGENT_URL_DEFAULT=http://data-agent-default:9000`). This lets a
     dev/staging deployment wire an agent without running the
     license server.
  2. License server at `${LICENSE_SERVER_URL}/api/v1/tenants/<t>/agent-url`.

Either path may raise `TenantNotConfigured`; callers map to a clean
local-DB fallback in agent_proxy / search routers.
"""
from __future__ import annotations

import logging
import os
import time

import httpx

from app.config import settings

log = logging.getLogger("osint.tenant_registry")

# Short in-memory cache for the per-tenant module allow-list. /search/modules
# is hit on every search-form render, so we don't want a license-server
# round-trip each time. Operator changes to a tenant's pack take effect
# within _MODULES_TTL seconds.
_MODULES_TTL = 60.0
_modules_cache: dict[str, tuple[float, list[str] | None]] = {}


class TenantNotConfigured(Exception):
    """No agent URL known for this tenant (env unset, license server down or 404)."""


def _env_override(tenant: str) -> str | None:
    # Tenant names are lowercase ascii; uppercase + replace - for env-var-safe key.
    key = f"AGENT_URL_{tenant.upper().replace('-', '_')}"
    return os.environ.get(key)


async def get_agent_url(tenant: str) -> str:
    override = _env_override(tenant)
    if override:
        log.debug("agent url for %s from env override: %s", tenant, override)
        return override

    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/agent-url"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"X-Internal-Key": settings.internal_secret})
    except httpx.RequestError as e:
        log.info("license server unreachable for %s: %s", tenant, e)
        raise TenantNotConfigured(f"License server unreachable: {e}") from e
    if r.status_code == 404:
        raise TenantNotConfigured(f"Unknown tenant: {tenant}")
    r.raise_for_status()
    return r.json()["agent_url"]


class AgentKeyUnavailable(Exception):
    """No agent key known for this tenant (license server down, tenant not
    registered, or the licence is inactive/expired)."""


# Per-tenant agent keys. Cached because every graph read and every
# incremental search flush needs one; the TTL is short enough that a
# re-issued licence takes effect on its own.
_AGENT_KEY_TTL = 300.0
_agent_key_cache: dict[str, tuple[float, str]] = {}


async def get_agent_key(tenant: str) -> str:
    """The `X-Framework-Key` this tenant's data agent expects.

    This is the per-tenant `agent_api_key` from the licence — the same value
    `data-agent/install.sh` writes into the customer's agent as
    `FRAMEWORK_KEY`. It is deliberately NOT the framework's own secret: the
    key travels to customer premises, so a shared one would let any customer
    authenticate against any other customer's agent (and against anything
    else that secret protects).

    Lookup order mirrors `get_agent_url`:
      1. `AGENT_KEY_<TENANT-UPPER>` env override (dev/staging without a
         licence server),
      2. the licence server.

    Raises `AgentKeyUnavailable` rather than silently falling back to a
    global secret — a wrong key must surface as an auth error, not as a
    quiet local-DB write that would take investigation data out of the
    customer's sovereign store.
    """
    override = os.environ.get(f"AGENT_KEY_{tenant.upper().replace('-', '_')}")
    if override:
        return override

    now = time.monotonic()
    cached = _agent_key_cache.get(tenant)
    if cached and cached[0] > now:
        return cached[1]

    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/agent-key"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"X-Internal-Key": settings.internal_secret})
    except httpx.RequestError as e:
        raise AgentKeyUnavailable(f"License server unreachable: {e}") from e
    if r.status_code in (403, 404):
        raise AgentKeyUnavailable(
            f"No usable agent key for tenant '{tenant}' (HTTP {r.status_code})")
    r.raise_for_status()
    key = (r.json() or {}).get("agent_key") or ""
    if not key:
        raise AgentKeyUnavailable(f"License server returned an empty agent key for '{tenant}'")
    _agent_key_cache[tenant] = (now + _AGENT_KEY_TTL, key)
    return key


def invalidate_agent_key(tenant: str | None = None) -> None:
    """Drop cached agent keys (all, or one tenant). Call after re-issuing a
    licence so the new key is picked up without waiting out the TTL."""
    if tenant is None:
        _agent_key_cache.clear()
    else:
        _agent_key_cache.pop(tenant, None)


async def get_enabled_modules(tenant: str) -> list[str] | None:
    """Return the tenant's licensed module allow-list, or ``None`` = all
    modules enabled.

    Degrades OPEN: any failure (license server down/unreachable, tenant
    not registered, column NULL/empty) returns ``None`` so a licensing
    lookup blip can never lock a tenant out of search. A non-empty list
    restricts the tenant to exactly those module names.
    """
    now = time.monotonic()
    cached = _modules_cache.get(tenant)
    if cached and cached[0] > now:
        return cached[1]

    value: list[str] | None = None
    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/enabled-modules"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"X-Internal-Key": settings.internal_secret})
        if r.status_code == 200:
            mods = r.json().get("enabled_modules")
            if mods:  # non-empty list restricts; None/[] means "all"
                cleaned = [str(m).strip().lower() for m in mods if str(m).strip()]
                value = cleaned or None
        elif r.status_code != 404:
            r.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        log.info("enabled-modules lookup failed for %s: %s (defaulting to ALL)", tenant, e)
        value = None

    _modules_cache[tenant] = (now + _MODULES_TTL, value)
    return value


# ── Tenant settings the customer admin sets ─────────────────
# Read on hot paths (every search start), so cached like the module list.
# Invalidated by PUT /admin/settings, so an admin's change applies at once
# in the worker that served it and within the TTL everywhere else.
_SETTINGS_TTL = 60.0
_settings_cache: dict[str, tuple[float, dict]] = {}


async def get_tenant_settings(tenant: str) -> dict:
    """The tenant's settings from the license server, or {} if unknown.

    On a lookup failure the LAST KNOWN value is kept rather than dropped to
    {}: a setting like "a search needs a stated purpose" must not silently
    switch itself off because the license server blinked.
    """
    now = time.monotonic()
    cached = _settings_cache.get(tenant)
    if cached and cached[0] > now:
        return cached[1]
    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/settings"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"X-Internal-Key": settings.internal_secret})
        if r.status_code == 404:
            value: dict = {}
        else:
            r.raise_for_status()
            value = r.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        log.warning("tenant settings lookup failed for %s: %s (keeping last known)", tenant, e)
        return cached[1] if cached else {}
    _settings_cache[tenant] = (now + _SETTINGS_TTL, value)
    return value


def invalidate_tenant_settings(tenant: str | None = None) -> None:
    if tenant is None:
        _settings_cache.clear()
    else:
        _settings_cache.pop(tenant, None)



async def get_usable_modules(tenant: str) -> list[str] | None:
    """What this tenant may actually run: the licence, narrowed by what the
    customer admin switched off (`disabled_modules`).

    ``None`` keeps its meaning of "everything" — only when the licence is
    unrestricted AND nothing is switched off. A customer can narrow, never
    widen: a disabled name outside the licence changes nothing.
    """
    licensed = await get_enabled_modules(tenant)
    disabled = set((await get_tenant_settings(tenant)).get("disabled_modules") or [])
    if not disabled:
        return licensed
    if licensed is None:
        from app.services.osint_orchestrator import supported_modules
        licensed = list(supported_modules())
    return [m for m in licensed if m not in disabled]
