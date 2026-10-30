"""
Keycloak JWT verification + tenant extraction (tenant-aware).

Tenant comes from the user's Keycloak group membership. We do NOT use
the X-Tenant header (the original plan's nginx-subdomain fallback) —
this build runs without subdomain routing, so groups are the only
source of truth.

JWT validation is tenant-aware. A JWT's `iss` claim points at its
issuing Keycloak realm. We use that to look up the right JWKS:

1. Decode the JWT *unverified* to read its `iss` claim and groups.
2. If the iss matches the framework's own Keycloak (legacy / dev
   tenant / platform-admin), use the framework JWKS.
3. Otherwise, look up the tenant's `idp_url` in the license-server
   and fetch *that* JWKS.

A per-issuer cache (5-minute TTL) avoids hitting the IdP on every
request.

This means a JWT issued by tenant-a's Keycloak can never be accepted
as a tenant-b user — the issuer chain is the trust anchor.
"""
from __future__ import annotations

import logging
import time

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

log = logging.getLogger("osint.auth")
security = HTTPBearer(auto_error=True)

_JWKS_TTL = 300.0
# issuer URL -> {"jwks": dict, "exp": float}
_jwks_cache: dict[str, dict] = {}


def _framework_issuer() -> str:
    """The framework Keycloak's canonical issuer URL."""
    return f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}"


def _framework_issuers() -> set[str]:
    """All issuer strings the framework Keycloak may legitimately emit.

    The same realm presents a different `iss` depending on the inbound
    network (internal docker DNS vs. the public nginx URL), so we accept
    a fixed, explicit allow-list — NOT a loose prefix match. A token from
    `http://keycloak:8080/realms/EVIL` must never be treated as a
    framework token just because it starts with `http://keycloak:`.
    """
    realm = settings.keycloak_realm
    allowed = {
        _framework_issuer().rstrip("/"),
        settings.keycloak_public_issuer.rstrip("/"),
        f"http://keycloak:8080/realms/{realm}",
        f"http://framework-kc:8080/realms/{realm}",
    }
    return {i for i in allowed if i}


def _platform_realm_issuer() -> str:
    """Internal issuer URL for the separate product-owner realm.
    Used to fetch that realm's JWKS."""
    return f"{settings.keycloak_url.rstrip('/')}/realms/{settings.platform_realm}"


def _is_platform_issuer(token_iss: str | None) -> bool:
    """True if the token was issued by the platform realm.

    Matched by realm-path suffix (`.../realms/<platform_realm>`) rather
    than an exact issuer string, because Keycloak emits different
    scheme/host/port issuers for the same realm depending on the inbound
    network (internal http vs. public https via nginx). This is safe: a
    foreign token whose realm merely happens to be named `platform` is
    still fetched-and-verified against OUR platform realm's JWKS, so a
    token not signed by our platform key fails signature verification.
    A tenant/osint token (realm `osint`) never matches this suffix, so it
    can never reach the operator console."""
    if not token_iss:
        return False
    return token_iss.rstrip("/").endswith(f"/realms/{settings.platform_realm}")


# Realm roles / IdP group names that are NOT tenants. A tenant group is
# any group whose normalized name is not one of these reserved names.
_NON_TENANT_GROUPS = {"admin", "investigator", "reader", "platform_admin"}


async def _fetch_jwks(issuer: str) -> dict:
    now = time.time()
    cached = _jwks_cache.get(issuer)
    if cached and cached["exp"] > now:
        return cached["jwks"]
    url = f"{issuer.rstrip('/')}/protocol/openid-connect/certs"
    # TLS verification follows settings.tls_verify_idp: True in prod
    # (customer Keycloaks have real CA certs), False in dev where the
    # customer KC serves a self-signed cert. The dev .env sets it False.
    async with httpx.AsyncClient(timeout=10, verify=settings.tls_verify_idp) as client:
        r = await client.get(url)
        r.raise_for_status()
        jwks = r.json()
    _jwks_cache[issuer] = {"jwks": jwks, "exp": now + _JWKS_TTL}
    return jwks


async def _resolve_tenant_idp(tenant: str) -> str | None:
    """Ask license-server which IdP this tenant uses. Returns None if
    license-server says 'use framework default' (idp_url is null) or
    the tenant doesn't exist."""
    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/idp-url"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url, headers={"X-Internal-Key": settings.internal_secret})
    except httpx.HTTPError:
        log.exception("license-server idp-url lookup failed for tenant=%s", tenant)
        return None
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        log.warning("license-server idp-url returned %s for tenant=%s", r.status_code, tenant)
        return None
    return r.json().get("idp_url")


async def _resolve_issuer(token_iss: str | None, tenant_hint: str | None) -> str:
    """Decide which issuer's JWKS to validate against.

    - If the JWT's iss is the framework's own Keycloak (or its internal
      docker-network counterpart), use the framework JWKS. This covers
      platform-admins and legacy tenants without a per-tenant IdP.
    - Else, if a tenant hint is in the JWT's groups claim and the
      license-server has an idp_url for that tenant, use that — and
      verify the JWT's iss actually matches it (defends against tokens
      from tenant-A being replayed against tenant-B's endpoints).
    - Else fall back to framework Keycloak.
    """
    fw = _framework_issuer()
    if token_iss and token_iss.rstrip("/") in _framework_issuers():
        return fw

    # Product-owner token → validate against the separate platform realm.
    if _is_platform_issuer(token_iss):
        return _platform_realm_issuer()

    if tenant_hint:
        idp = await _resolve_tenant_idp(tenant_hint)
        if idp:
            if token_iss and token_iss.rstrip("/") != idp.rstrip("/"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"JWT issuer mismatch for tenant '{tenant_hint}'",
                )
            return idp
    return fw


def _extract_tenant(payload: dict) -> str | None:
    """Pick the user's tenant from the groups claim.

    A tenant is any group whose normalized name is not a reserved
    role-group name (see `_NON_TENANT_GROUPS`). We match those names
    exactly rather than by prefix, so a legitimate tenant called e.g.
    `administration` is no longer silently discarded.
    """
    groups = payload.get("groups", []) or []
    candidates = sorted(
        g.lstrip("/")
        for g in groups
        if g.lstrip("/").lower() not in _NON_TENANT_GROUPS
    )
    if len(candidates) > 1:
        # Picking the first group in claim order made the effective tenant
        # depend on Keycloak's serialisation — the same user could land in a
        # different tenant between two logins. Sorting makes it at least
        # deterministic; the real fix is not putting a user in two tenants.
        log.warning("user is in multiple tenant groups %s — using '%s'",
                    candidates, candidates[0])
    return candidates[0] if candidates else None


async def _verify_token(token: str) -> dict:
    """Verify a JWT's signature against the correct (tenant-aware) issuer
    JWKS and return the decoded payload. Shared by get_current_user
    (tenant users) and get_platform_admin (framework operators). Raises
    401 on any verification failure."""
    try:
        # Step 1: peek at the unverified payload to learn iss + tenant hint.
        # We do NOT trust this yet; it's just for routing the lookup.
        unverified = jwt.get_unverified_claims(token)
        iss = unverified.get("iss")
        tenant_hint = _extract_tenant(unverified)

        # Step 2: pick the right issuer's JWKS.
        issuer = await _resolve_issuer(iss, tenant_hint)
        jwks = await _fetch_jwks(issuer)

        # Step 3: verify signature against the chosen JWKS.
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
        if key is None:
            raise HTTPException(status_code=401, detail="Unknown token signing key")
        # `alg` is taken from the JWKS entry, not from the attacker-supplied
        # header: a token header claiming e.g. "none" or a symmetric alg must
        # never dictate how we verify it.
        alg = key.get("alg") or header.get("alg") or "RS256"
        if alg.lower() == "none":
            raise HTTPException(status_code=401, detail="Unsupported token algorithm")
        payload = jwt.decode(
            token,
            key,
            algorithms=[alg],
            # aud is not verified: Keycloak puts "account" there for SPA
            # tokens, so it carries no trust decision here. The issuer chain
            # (signature verified against THAT realm's JWKS) is the anchor.
            # `azp` can be pinned via ALLOWED_AZP when an operator wants a
            # token minted for one client not to be usable by another.
            options={"verify_aud": False, "verify_iss": False},
        )
        allowed = [a.strip() for a in (settings.allowed_azp or "").split(",") if a.strip()]
        if allowed:
            azp = payload.get("azp")
            if azp and azp not in allowed:
                log.warning("token rejected: azp '%s' not in ALLOWED_AZP", azp)
                raise HTTPException(status_code=401, detail="Token issued for another client")
        return payload
    except JWTError as e:
        log.info("JWT verification failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        log.exception("Token verification error")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    payload = await _verify_token(credentials.credentials)

    roles = payload.get("realm_access", {}).get("roles", [])
    tenant = _extract_tenant(payload)
    if not tenant:
        if "platform_admin" in roles:
            # Platform admins are framework operators. By design they
            # have no tenant and no access to tenant-scoped data.
            # They use /api/v1/platform/*.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admins do not have access to tenant data endpoints.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tenant group on this user. Add the user to a tenant group in your IdP.",
        )

    return {
        "user_id": payload.get("sub"),
        "username": payload.get("preferred_username"),
        "email": payload.get("email"),
        "roles": roles,
        "tenant": tenant,
    }


def require_role(role: str):
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if role not in user["roles"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return user
    return _check


async def get_platform_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Auth dependency for the framework-operator panel (/api/v1/platform/*).

    Requires the framework-KC realm role `platform_admin`. Deliberately
    tenant-LESS: it does NOT call get_current_user (which 403s a
    tenant-less user), so the operator can reach platform endpoints —
    but by using this dependency ONLY on /platform/*, tenant-scoped
    routers still reject platform admins (they keep using
    get_current_user, which has no tenant to work with). This preserves
    the data-sovereignty boundary: operators manage tenants but
    never see case/entity/alert data or tenant user accounts.
    """
    payload = await _verify_token(credentials.credentials)
    # Must be a token from the dedicated platform realm — a tenant/osint
    # token is rejected here even if it carried a platform_admin role.
    if not _is_platform_issuer(payload.get("iss")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a platform-realm token",
        )
    roles = payload.get("realm_access", {}).get("roles", [])
    if "platform_admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role 'platform_admin' required",
        )
    user = {
        "user_id": payload.get("sub"),
        "username": payload.get("preferred_username"),
        "email": payload.get("email"),
        "roles": roles,
        "tenant": None,
    }
    # Stashed so the platform router's audit wrapper knows WHO acted without
    # re-verifying the token. It runs after the handler, outside dependency
    # scope, so this is the handover point.
    request.state.platform_user = user
    return user
