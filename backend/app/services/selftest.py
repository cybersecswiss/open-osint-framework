"""Self-test for the customer admin.

One screen that answers "is our installation working?" in the terms the
customer can act on — each check has a status and a sentence, never a stack
trace. It reads only health and configuration: no case data crosses into it.

Statuses: ok · warn (works, but act soon) · fail (broken now) · info (a fact,
e.g. "you sign in through the operator's Keycloak").
"""
from __future__ import annotations

import asyncio
import ssl
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.services.agent_client import AgentAuthError, push_to_agent, get_from_agent
from app.services.tenant_registry import get_agent_url

# What the framework of this build expects the customer's agent to offer.
EXPECTED_CAPABILITIES = {"activity-log", "evidence", "entity-merge", "cross-case", "case-scoped-writes"}


def _r(key: str, status: str, **params: Any) -> dict[str, Any]:
    return {"key": key, "status": status, "params": {k: v for k, v in params.items() if v is not None}}


async def _lic(path: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=8) as c:
        return await c.get(f"{settings.license_server_url}{path}",
                           headers={"X-Internal-Key": settings.internal_secret})


async def check_license(tenant: str) -> dict:
    try:
        r = await _lic(f"/api/v1/tenants/{tenant}/license-info")
        if r.status_code == 404:
            return _r("license", "fail", reason="not_registered")
        d = r.json()
    except Exception as e:  # noqa: BLE001
        return _r("license", "fail", reason="unreachable", error=type(e).__name__)
    days = d.get("days_remaining")
    until = (d.get("valid_until") or "")[:10]
    if not d.get("is_active") or d.get("is_expired"):
        return _r("license", "fail", reason="expired", until=until)
    return _r("license", "warn" if days is not None and days < 30 else "ok", until=until, days=days)


async def check_agent(tenant: str) -> list[dict]:
    try:
        url = await get_agent_url(tenant)
    except Exception:  # noqa: BLE001
        return [_r("agent", "fail", reason="not_configured")]
    out: list[dict] = []
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8, verify=settings.tls_verify_idp) as c:
            h = await c.get(f"{url.rstrip('/')}/health")
        ms = int((time.monotonic() - t0) * 1000)
        health = h.json() if h.status_code == 200 else {}
        out.append(_r("agent", "ok" if h.status_code == 200 else "fail", ms=ms,
                      status_code=None if h.status_code == 200 else h.status_code))
    except Exception as e:  # noqa: BLE001
        return [_r("agent", "fail", reason="unreachable", error=str(e)[:160])]

    # The key: an authenticated no-op. 401 is its own, actionable failure.
    try:
        await push_to_agent(tenant, "/api/entities/lookup", {"ids": []})
        out.append(_r("agent_key", "ok"))
    except AgentAuthError:
        out.append(_r("agent_key", "fail"))
    except Exception as e:  # noqa: BLE001
        out.append(_r("agent_key", "warn", error=str(e)[:160]))

    caps = set(health.get("capabilities") or [])
    missing = sorted(EXPECTED_CAPABILITIES - caps)
    out.append(_r("agent_version", "warn" if missing else "ok",
                  level=health.get("api_level") or "?", missing=", ".join(missing) or None))

    out.append(await check_tls(url))

    try:
        v = await get_from_agent(tenant, "/api/activity/verify")
        broken = len(v.get("broken") or [])
        out.append(_r("audit_chain", "fail" if broken else "ok",
                      verified=v.get("verified", 0), broken=broken or None))
    except Exception:  # noqa: BLE001 — older agent without the log
        out.append(_r("audit_chain", "warn", reason="unavailable"))
    return out


async def check_tls(agent_url: str) -> dict:
    p = urlparse(agent_url)
    host = p.hostname or ""
    if p.scheme != "https":
        # A Docker service name has no dot: the dev overlay. Anything else in
        # clear text is a customer store reachable without transport security.
        if "." not in host:
            return _r("tls", "info", reason="internal", host=host)
        return _r("tls", "fail", reason="plain_http", host=host)
    port = p.port or 443

    def _probe() -> dict:
        import socket
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=6) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ss:
                return ss.getpeercert()
    try:
        cert = await asyncio.to_thread(_probe)
    except ssl.SSLCertVerificationError as e:
        return _r("tls", "fail", reason="invalid", error=str(e.verify_message or e)[:160])
    except Exception as e:  # noqa: BLE001
        return _r("tls", "fail", reason="unreachable", error=str(e)[:160])
    not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    days = (not_after - datetime.now(timezone.utc)).days
    return _r("tls", "warn" if days < 21 else "ok", until=not_after.date().isoformat(), days=days)


async def check_idp(tenant: str) -> dict:
    try:
        r = await _lic(f"/api/v1/tenants/{tenant}/idp-credentials")
        idp = r.json().get("idp_url") if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        idp = None
    if not idp:
        return _r("idp", "info", reason="framework")
    try:
        async with httpx.AsyncClient(timeout=8, verify=settings.tls_verify_idp) as c:
            d = await c.get(f"{idp.rstrip('/')}/.well-known/openid-configuration")
        if d.status_code != 200:
            return _r("idp", "fail", reason="status", status_code=d.status_code, url=idp)
        return _r("idp", "ok", issuer=d.json().get("issuer"))
    except Exception as e:  # noqa: BLE001
        return _r("idp", "fail", reason="unreachable", url=idp, error=str(e)[:160])


async def check_alerting(tenant: str) -> dict:
    try:
        r = await _lic(f"/api/v1/tenants/{tenant}/notification-settings")
        n = r.json() if r.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        n = {}
    channels = [c for c, on in (("email", n.get("notify_email_enabled")),
                                ("webhook", n.get("notify_webhook_enabled"))) if on]
    if not channels:
        return _r("alerting", "warn", reason="none")
    last_ok, last_err = n.get("notify_last_ok_at"), n.get("notify_last_error")
    last_try = n.get("notify_last_attempt_at")
    if last_err and (not last_ok or (last_try and last_try > last_ok)):
        return _r("alerting", "fail", channels=", ".join(channels), error=str(last_err)[:160])
    return _r("alerting", "ok", channels=", ".join(channels), last_ok=(last_ok or "")[:16] or None)


async def check_capture() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.capture_url}/health")
        return _r("capture", "ok" if r.status_code == 200 else "warn")
    except Exception:  # noqa: BLE001
        return _r("capture", "warn")


async def run(tenant: str) -> list[dict]:
    lic, agent, idp, alerting, capture = await asyncio.gather(
        check_license(tenant), check_agent(tenant), check_idp(tenant),
        check_alerting(tenant), check_capture())
    return [lic, *agent, idp, alerting, capture]
