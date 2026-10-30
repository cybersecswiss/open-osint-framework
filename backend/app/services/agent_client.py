"""
HTTP client for the customer's data agent.

Two things here are load-bearing for data sovereignty:

1. **The key is per tenant.** Every request carries the tenant's own
   `agent_api_key` (issued with its licence, baked into the agent by
   `install.sh`), fetched via `tenant_registry.get_agent_key`. The
   framework's own secrets never leave this network.

2. **Auth failures are NOT "agent unavailable".** Callers fall back to the
   framework-local DB when an agent is unreachable, which is correct for a
   network outage but very wrong for a rejected key: the investigation data
   would silently land in the operator's database instead of the customer's.
   So 401/403 raises `AgentAuthError`, which no caller treats as a fallback
   condition — it surfaces as an error the operator has to fix.

3. **A rejected payload is NOT "agent unavailable" either.** Same reasoning
   as (2), one step further. HTTP 500 means the agent ran our request and
   its code raised — bad data, a constraint violation, a bug. Reading that
   as "unreachable" sent the caller down the local-fallback path, where the
   write either lands in the operator's DB or (for a caller that sends only
   edges, whose endpoints live solely on the agent) is dropped as dangling
   and reported as success. Both were observed: an AI link the analyst
   accepted returned `{"applied": 1}` and existed nowhere.

   So 500 raises `AgentRejected`. 502/503/504 stay `AgentUnavailable` —
   those come from something in front of the app, and mean we never reached
   it, which is exactly what a fallback is for.

Mapping used throughout:
    network error / timeout        → AgentUnavailable  (local fallback OK)
    502 / 503 / 504                → AgentUnavailable  (never reached the app)
    500                            → AgentRejected     (fail loudly)
    401 / 403                      → AgentAuthError    (fail loudly)
    missing URL or key             → TenantNotConfigured / AgentKeyUnavailable
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services.tenant_registry import get_agent_key, get_agent_url

log = logging.getLogger("osint.agent_client")


class AgentUnavailable(Exception):
    """Agent is configured but not reachable right now (network, 5xx)."""


class AgentAuthError(Exception):
    """Agent rejected our key. Never fall back to local storage on this."""


class AgentRejected(AgentUnavailable):
    """Agent was reached and refused the request (HTTP 500).

    Distinct from a plain `AgentUnavailable` on purpose: the store is up, so
    a fallback is not a stand-in for it — it is a different destination for
    data the customer's store just declined.

    **Why it SUBCLASSES `AgentUnavailable` instead of standing alone.** Some
    twenty call sites catch `AgentUnavailable`, and all but three are reads
    (graph, alerts, entity fetch) whose local fallback is long-established
    behaviour. Making this a sibling class would have changed all of them at
    once, in a commit about the AI path. As a subclass, every existing
    handler keeps behaving exactly as before, and the three WRITE paths that
    must not fall back opt in by catching `AgentRejected` first.

    The read paths are not thereby correct — a 500 on a graph read still
    serves possibly-stale local data as though it were the case. That is a
    real question, and it is recorded rather than settled here.
    """


async def _headers(tenant: str) -> dict[str, str]:
    return {"X-Framework-Key": await get_agent_key(tenant)}


def _raise_for_status(r: httpx.Response, tenant: str) -> None:
    """Translate HTTP status into this module's exception vocabulary."""
    if r.status_code in (401, 403):
        raise AgentAuthError(
            f"Agent for tenant '{tenant}' rejected the framework key "
            f"(HTTP {r.status_code}). The tenant's agent_api_key and the "
            f"agent's FRAMEWORK_KEY are out of sync — re-run the licence "
            f"handover; do NOT expect data to be stored while this persists."
        )
    if r.status_code == 500:
        # Reached the app and it raised. Include the body: for an ingest
        # this is usually the constraint that failed, and it is the only
        # place the operator will ever see it.
        detail = (r.text or "")[:300].replace("\n", " ")
        raise AgentRejected(
            f"The customer's store refused the write (HTTP 500). "
            f"Nothing was saved. Agent said: {detail or '(no body)'}"
        )
    if r.status_code >= 500:
        raise AgentUnavailable(f"Agent returned HTTP {r.status_code}")
    r.raise_for_status()


async def push_to_agent(tenant: str, endpoint: str, payload: dict) -> dict:
    agent_url = await get_agent_url(tenant)  # raises TenantNotConfigured upstream
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=30, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.post(f"{agent_url}{endpoint}", json=payload, headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent push failed: {e}") from e
        _raise_for_status(r, tenant)
        return r.json()


async def get_from_agent(tenant: str, endpoint: str) -> dict:
    agent_url = await get_agent_url(tenant)
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=30, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.get(f"{agent_url}{endpoint}", headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent unreachable: {e}") from e
        _raise_for_status(r, tenant)
        return r.json()


async def get_bytes_from_agent(tenant: str, endpoint: str) -> tuple[bytes, dict[str, str]]:
    """Raw GET for binary content (evidence files). Returns body + headers."""
    agent_url = await get_agent_url(tenant)
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=60, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.get(f"{agent_url}{endpoint}", headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent unreachable: {e}") from e
        _raise_for_status(r, tenant)
        return r.content, dict(r.headers)


async def post_large_to_agent(tenant: str, endpoint: str, payload: dict) -> dict:
    """POST with a longer timeout — an evidence record carries tens of MB."""
    agent_url = await get_agent_url(tenant)
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=120, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.post(f"{agent_url}{endpoint}", json=payload, headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent push failed: {e}") from e
        _raise_for_status(r, tenant)
        return r.json()


async def patch_on_agent(tenant: str, endpoint: str, payload: dict) -> dict:
    """PATCH on the customer agent. Used for in-place updates like the
    'mark as relevant' toggle on entities."""
    agent_url = await get_agent_url(tenant)
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=30, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.patch(f"{agent_url}{endpoint}", json=payload, headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent unreachable: {e}") from e
        _raise_for_status(r, tenant)
        return r.json()


async def put_on_agent(tenant: str, endpoint: str, payload: dict) -> dict:
    """PUT on the customer agent. Used to mirror case metadata (number,
    title, status) so the customer's store is self-describing rather than
    a pile of `job <uuid>` buckets."""
    agent_url = await get_agent_url(tenant)
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=30, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.put(f"{agent_url}{endpoint}", json=payload, headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent unreachable: {e}") from e
        _raise_for_status(r, tenant)
        return r.json()


async def delete_on_agent(tenant: str, endpoint: str) -> None:
    """DELETE on the customer agent. Used when a case is wiped from the
    framework — the agent owns the actual investigation data, so the
    framework asks it to wipe its rows too. Returns silently on 204
    (success) or 404 (case never existed on this agent). Raises
    AgentUnavailable on network errors so the caller can decide
    whether to abort the cascade."""
    agent_url = await get_agent_url(tenant)
    headers = await _headers(tenant)
    async with httpx.AsyncClient(timeout=30, verify=settings.tls_verify_agent) as client:
        try:
            r = await client.delete(f"{agent_url}{endpoint}", headers=headers)
        except httpx.RequestError as e:
            raise AgentUnavailable(f"Agent unreachable: {e}") from e
        if r.status_code == 404:
            return
        _raise_for_status(r, tenant)
