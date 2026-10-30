"""
Public OIDC-config bootstrap endpoint.

Frontend hits this BEFORE auth init to learn which Keycloak realm to
talk to for a given tenant. Tenant comes from subdomain (production)
or query param (dev). Returns only non-sensitive values.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.config import settings

log = logging.getLogger("osint.oidc")
router = APIRouter(tags=["oidc"])


# Public — resolves an email address to a tenant by matching the email
# domain against the per-tenant email_domains list in the license server.
# Frontend pre-auth screen calls this before initializing keycloak-js.
@router.get("/resolve-tenant")
async def resolve_tenant(email: str, request: Request):
    """Map an e-mail domain to its tenant. Unauthenticated by necessity.

    ⚠️ **This endpoint answers "is this organisation a customer?"** — 200
    against 404 — and for a law-enforcement product the customer list is
    itself sensitive. nginx caps it at 60 requests/minute per IP (zone
    `resolve`), which bounds but does not prevent enumeration: ~3 600 domains
    per hour from one address.

    A miss is therefore logged at WARNING with the client IP and the DOMAIN,
    so a sweep shows up in the ordinary logs instead of leaving no trace.
    The local part of the address is deliberately NOT logged: it is personal
    data belonging to someone who is not a user of this system, and it adds
    nothing — enumeration is visible from the domain and the rate alone.

    Bounding the oracle further (slower rate, invitation-only registration,
    uniform responses) is a deployment policy decision, not something to
    settle in code.
    """
    url = f"{settings.license_server_url}/api/v1/tenants/resolve-by-email"
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url, params={"email": email})
    except httpx.HTTPError:
        log.exception("license-server resolve-by-email lookup failed")
        raise HTTPException(status_code=503, detail="License server unreachable")
    if r.status_code == 400:
        raise HTTPException(status_code=400, detail=r.json().get("detail", "Invalid email"))
    if r.status_code == 404:
        domain = email.rsplit("@", 1)[-1].lower() if "@" in email else "(none)"
        client = request.headers.get("x-real-ip") or (
            request.client.host if request.client else "unknown")
        log.warning("resolve-tenant miss: domain=%s from %s", domain, client)
        raise HTTPException(
            status_code=404,
            detail="Ihre Organisation ist auf dieser Plattform nicht registriert.",
        )
    r.raise_for_status()
    return r.json()


@router.get("/oidc-config/{tenant}")
async def oidc_config(tenant: str):
    """Return {idp_url, realm} for a tenant. Public endpoint, no auth.

    Two cases:
    - tenant has its own IdP (customer-side):
        idp_url = customer Keycloak base URL incl. realm path
        realm   = tenant name
    - tenant uses framework Keycloak (legacy / dev):
        idp_url = framework Keycloak base URL incl. realm path
        realm   = framework realm name (currently 'osint')
    """
    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/oidc-config"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
    except httpx.HTTPError:
        log.exception("license-server oidc-config lookup failed")
        raise HTTPException(status_code=503, detail="License server unreachable")

    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Unknown tenant '{tenant}'")
    r.raise_for_status()
    body = r.json()

    if body.get("idp_url"):
        # Customer-side IdP. The idp_url already includes the /realms/<x>
        # suffix; split it back into base + realm so keycloak-js can
        # reconstruct it.
        idp_url = body["idp_url"].rstrip("/")
        # Expected shape: https://host[:port]/auth/realms/<realm>
        if "/realms/" in idp_url:
            base, realm = idp_url.rsplit("/realms/", 1)
        else:
            base, realm = idp_url, tenant
        return {"url": base, "realm": realm, "tenant": tenant}

    # Legacy fallback: use framework Keycloak. Frontend already has the
    # build-time VITE_KEYCLOAK_URL so we just signal "use defaults".
    return {"url": None, "realm": None, "tenant": tenant}
