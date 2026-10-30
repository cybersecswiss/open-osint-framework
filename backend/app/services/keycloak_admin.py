"""
Wrapper around Keycloak Admin REST API — tenant-aware.

For each call, the caller passes a `user` dict (the request's
authenticated user). We use the user's tenant to look up:
- which Keycloak base URL to talk to (idp_url from license-server)
- which client secret to use for the service-account token

A tenant whose `idp_url` is NULL falls back to the framework Keycloak
+ the framework's `osint-backend` client secret (legacy/dev path).

Tokens cached for 50 s per (issuer, client_id).
Credentials (idp_url + secret) cached for 5 min per tenant.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("osint.keycloak_admin")

_TOKEN_TTL = 50.0
_CREDS_TTL = 300.0
class IdPNotManaged(Exception):
    """This tenant runs its own IdP and has given the framework no client
    credential for it — so user administration genuinely does not belong here.

    Raised instead of letting `_token()` post `client_secret=None`, get a 401
    and surface as an unhandled HTTP 500. The code already knew the situation
    (it logged "admin proxy will fail") and then failed in a way that told the
    administrator nothing.

    Whether a tenant SHOULD be manageable from here is a product question, not
    a bug: architecture rule 2 says the operator does not manage customer
    users, and a customer running its own Keycloak has its own console for
    that. The honest answer is a clear sentence, not an error page.
    """

    def __init__(self, tenant: str):
        super().__init__(
            f"Tenant '{tenant}' authenticates against its own identity "
            f"provider, which this framework has no administrative access "
            f"to. Manage these accounts in your own identity provider."
        )
        self.tenant = tenant


# (idp_url, client_id) -> {"value": str, "exp": float}
_token_cache: dict[tuple[str, str], dict[str, Any]] = {}
# tenant -> {"idp_url": str|None, "client_id": str, "secret": str, "exp": float}
_creds_cache: dict[str, dict[str, Any]] = {}


def _framework_creds() -> dict[str, str | None]:
    return {
        "idp_url": f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}",
        "client_id": settings.keycloak_client_id,
        "secret": settings.keycloak_client_secret,
    }


async def _resolve_tenant_creds(tenant: str) -> dict[str, str | None]:
    """For a given tenant, resolve which Keycloak to call (with which
    client secret). Returns dict with idp_url, client_id, secret."""
    now = time.time()
    cached = _creds_cache.get(tenant)
    if cached and cached["exp"] > now:
        return cached

    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/idp-credentials"
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
    except httpx.HTTPError:
        log.exception("license-server idp-credentials lookup failed for tenant=%s", tenant)
        r = None

    if r is None or r.status_code != 200 or not r.json().get("idp_url"):
        # No customer-side IdP (or lookup failed) → fall back to framework KC.
        creds = {**_framework_creds(), "exp": now + _CREDS_TTL}
    else:
        body = r.json()
        creds = {
            "idp_url": body["idp_url"],
            "client_id": "osint-backend",  # convention, baked into realm-template
            "secret": body.get("backend_secret"),
            "exp": now + _CREDS_TTL,
        }
        if not creds["secret"]:
            # Do not cache a credential set that cannot work — otherwise the
            # tenant stays broken for the whole TTL after the operator fixes
            # it.
            log.warning(
                "tenant=%s has idp_url but no backend_secret — user "
                "administration is not available for this tenant", tenant,
            )
            raise IdPNotManaged(tenant)

    _creds_cache[tenant] = creds
    return creds


async def ensure_manageable(tenant: str) -> None:
    """Raise IdPNotManaged if this tenant's IdP cannot be administered here.

    Cheap: `_resolve_tenant_creds` is cached for five minutes, so this costs
    nothing on the hot path and gives the router a single place to ask.
    """
    await _resolve_tenant_creds(tenant)


async def _token(tenant: str) -> str:
    creds = await _resolve_tenant_creds(tenant)
    cache_key = (creds["idp_url"], creds["client_id"])
    now = time.time()
    cached = _token_cache.get(cache_key)
    if cached and cached["exp"] > now + 5:
        return cached["value"]

    url = f"{creds['idp_url'].rstrip('/')}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=10, verify=settings.tls_verify_idp) as c:
        r = await c.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": creds["client_id"],
                "client_secret": creds["secret"],
            },
        )
        r.raise_for_status()
        data = r.json()
    _token_cache[cache_key] = {
        "value": data["access_token"],
        "exp": now + min(_TOKEN_TTL, int(data.get("expires_in", 60))),
    }
    return data["access_token"]


def _admin_url(tenant_creds: dict, path: str) -> str:
    """Build admin-API URL. The idp_url ends in /realms/<realm> — strip
    that to get the base, then re-add /admin/realms/<realm>."""
    idp_url = tenant_creds["idp_url"].rstrip("/")
    if "/realms/" not in idp_url:
        raise RuntimeError(f"unexpected idp_url shape: {idp_url}")
    base, realm = idp_url.rsplit("/realms/", 1)
    return f"{base}/admin/realms/{realm}{path}"


async def _request(tenant: str, method: str, path: str, **kw) -> httpx.Response:
    creds = await _resolve_tenant_creds(tenant)
    headers = kw.pop("headers", {})
    headers["Authorization"] = f"Bearer {await _token(tenant)}"
    async with httpx.AsyncClient(timeout=15, verify=settings.tls_verify_idp) as c:
        r = await c.request(method, _admin_url(creds, path), headers=headers, **kw)
    if r.status_code >= 400:
        # Log status + method + path only. Response bodies from the
        # Keycloak admin API can echo tokens / realm internals, so keep
        # them out of INFO/WARNING logs (DEBUG only).
        log.warning("keycloak admin %s %s [tenant=%s] -> %s",
                    method, path, tenant, r.status_code)
        log.debug("keycloak admin error body [tenant=%s]: %s", tenant, r.text[:300])
    return r


# ── Groups ──────────────────────────────────────────────────────

async def list_groups(tenant: str) -> list[dict[str, Any]]:
    r = await _request(tenant, "GET", "/groups")
    r.raise_for_status()
    return r.json()


async def find_group_by_name(tenant: str, name: str) -> dict[str, Any] | None:
    for g in await list_groups(tenant):
        if g["name"] == name:
            return g
    return None


async def group_members(tenant: str, group_id: str) -> list[dict[str, Any]]:
    """Return every member of a group, paginating so tenants with more
    than one page of users don't silently lose members (which would make
    an existing user look 'not found' during auth checks)."""
    members: list[dict[str, Any]] = []
    first = 0
    page = 100
    while True:
        r = await _request(
            tenant, "GET",
            f"/groups/{group_id}/members?first={first}&max={page}",
        )
        r.raise_for_status()
        batch = r.json()
        members.extend(batch)
        if len(batch) < page:
            break
        first += page
    return members


# ── Roles ───────────────────────────────────────────────────────

async def list_realm_roles(tenant: str) -> list[dict[str, Any]]:
    r = await _request(tenant, "GET", "/roles")
    r.raise_for_status()
    return [
        x for x in r.json()
        if x["name"] not in {"offline_access", "uma_authorization"}
        and not x["name"].startswith("default-roles-")
    ]


async def user_roles(tenant: str, user_id: str) -> list[dict[str, Any]]:
    r = await _request(tenant, "GET", f"/users/{user_id}/role-mappings/realm")
    r.raise_for_status()
    return r.json()


async def add_user_roles(tenant: str, user_id: str, roles: list[dict[str, Any]]) -> None:
    if not roles:
        return
    r = await _request(tenant, "POST", f"/users/{user_id}/role-mappings/realm", json=roles)
    if r.status_code not in (204, 200):
        r.raise_for_status()


async def remove_user_roles(tenant: str, user_id: str, roles: list[dict[str, Any]]) -> None:
    if not roles:
        return
    r = await _request(tenant, "DELETE", f"/users/{user_id}/role-mappings/realm", json=roles)
    if r.status_code not in (204, 200):
        r.raise_for_status()


# ── Users ───────────────────────────────────────────────────────

async def get_user(tenant: str, user_id: str) -> dict[str, Any] | None:
    r = await _request(tenant, "GET", f"/users/{user_id}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


async def create_user(tenant: str, payload: dict[str, Any]) -> str:
    """Returns the new user's ID (parsed from Location header)."""
    r = await _request(tenant, "POST", "/users", json=payload)
    if r.status_code == 409:
        raise ValueError("User already exists")
    r.raise_for_status()
    location = r.headers.get("Location", "")
    return location.rsplit("/", 1)[-1]


async def update_user(tenant: str, user_id: str, payload: dict[str, Any]) -> None:
    r = await _request(tenant, "PUT", f"/users/{user_id}", json=payload)
    if r.status_code not in (204, 200):
        r.raise_for_status()


async def delete_user(tenant: str, user_id: str) -> None:
    r = await _request(tenant, "DELETE", f"/users/{user_id}")
    if r.status_code not in (204, 404):
        r.raise_for_status()


async def set_password(tenant: str, user_id: str, password: str, temporary: bool = True) -> None:
    r = await _request(
        tenant,
        "PUT",
        f"/users/{user_id}/reset-password",
        json={"type": "password", "value": password, "temporary": temporary},
    )
    if r.status_code not in (204, 200):
        r.raise_for_status()


async def add_user_to_group(tenant: str, user_id: str, group_id: str) -> None:
    r = await _request(tenant, "PUT", f"/users/{user_id}/groups/{group_id}")
    if r.status_code not in (204, 200):
        r.raise_for_status()


async def get_required_actions(tenant: str, user_id: str) -> list[str]:
    """Return the user's pending required actions (e.g. CONFIGURE_TOTP,
    UPDATE_PASSWORD). Empty list = nothing pending."""
    u = await get_user(tenant, user_id) or {}
    return list(u.get("requiredActions") or [])


async def set_required_actions(tenant: str, user_id: str, actions: list[str]) -> None:
    """Replace the user's required-actions list. Pass [] to clear all
    pending actions — how an operator releases a service / test account
    from a pending TOTP enrolment."""
    await update_user(tenant, user_id, {"requiredActions": actions})


async def update_realm_session_timeout(tenant: str, minutes: int) -> None:
    """Push the tenant's chosen session timeout to the Customer-KC
    realm. Sets both the SSO idle and max-lifespan timeouts to the same
    value (in seconds). 60s is the practical floor — anything shorter
    makes the UI unusable. Tenant setting `session_timeout_minutes`."""
    seconds = max(60, int(minutes) * 60)
    # PUT on /admin/realms/{realm} updates the realm representation.
    # _request → _admin_url with empty path returns exactly that URL.
    r = await _request(tenant, "PUT", "", json={
        "ssoSessionIdleTimeout": seconds,
        "ssoSessionMaxLifespan": seconds,
    })
    if r.status_code not in (204, 200):
        r.raise_for_status()


async def reset_totp(tenant: str, user_id: str) -> int:
    """Wipe the user's existing TOTP credentials and force a fresh
    enrollment on next login. Returns the number of OTP credentials that
    were removed (so the caller can surface "no 2FA was configured" vs.
    "old authenticator invalidated"). Any non-OTP credential (password,
    webauthn, …) is left untouched."""
    creds_resp = await _request(tenant, "GET", f"/users/{user_id}/credentials")
    creds_resp.raise_for_status()
    removed = 0
    for c in creds_resp.json():
        if c.get("type") == "otp":
            r = await _request(tenant, "DELETE", f"/users/{user_id}/credentials/{c['id']}")
            if r.status_code in (204, 200):
                removed += 1
    cur = await get_user(tenant, user_id) or {}
    actions = list({*(cur.get("requiredActions") or []), "CONFIGURE_TOTP"})
    await update_user(tenant, user_id, {"requiredActions": actions})
    return removed
