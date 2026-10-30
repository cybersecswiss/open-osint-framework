"""
Platform / Global Admin router — the framework OPERATOR panel.

Every route is gated by `get_platform_admin` (framework-KC realm role
`platform_admin`, tenant-less). Operators manage tenants, licenses, the
customer-docker wiring (agent URL / IdP URL / e-mail domains), module
packs and branding — and can probe a tenant's agent for reachability
(`GET /health` only, which returns NO investigation data).

Hard data-sovereignty boundary: this router NEVER exposes
case/entity/alert data or tenant user accounts. It only ever talks to
the license-server (operator metadata) and to a tenant agent's
unauthenticated `/health`. Tenant-scoped routers keep using
`get_current_user`, which rejects tenant-less platform admins.

All operator metadata lives in the license-server; this router is a
thin, audited proxy so the browser never holds the internal key.
"""
from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_platform_admin
from app.config import settings
from app.database import get_db
from app.models.case import Case
from app.services import (ai_settings, ai_usage, api_keys, audit, crime_forums,
                          forum_indexes, n8n_access, news_feeds, news_store,
                          telegram_channels)
from app.services.agent_client import (AgentAuthError, AgentUnavailable,
                                       delete_on_agent, get_from_agent)
from app.services.tenant_registry import TenantNotConfigured

log = logging.getLogger("osint.platform")

# The operator's own audit trail.
#
# This module calls itself "a thin, audited proxy". Without a router-wide
# audit wrapper, deleting a customer, extending a licence, resetting another
# operator's password or replacing an API key would all happen without a
# trace. The product keeps an HMAC-chained, append-only audit log with
# external anchors for investigators; the most privileged actor in the
# system must be in it too.
#
# Doing this per endpoint would mean ~40 hand-written calls and a standing
# invitation for number 41 to forget. A route class cannot be forgotten: it
# wraps every mutating request registered on this router, now and later.
#
# What is recorded: who, when, method, route template, path parameters,
# resulting status, client IP. What is deliberately NOT recorded: the
# request body. Half these endpoints carry secrets (API keys, passwords,
# client secrets), and an audit log that quietly becomes a credential store
# is a worse problem than the one it solves.
#
# Entries go under the `platform` pseudo-tenant, which gives operator
# actions their OWN hash chain. Interleaving them into a customer's chain
# would mix the operator's record into evidence the customer relies on.

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_ACTION_MAX = 60          # audit_log.action is varchar(60)


def _action_for(method: str, path: str) -> str:
    """`platform.put:/tenants/{tenant}/ai-enabled` — stable and greppable.

    The mount prefix is stripped rather than carried. By the time a route is
    registered its `path` is the full `/api/v1/platform/...`, which pushed
    five actions past the 60-character column — including
    `operators/{uid}/reset-password`, the one an investigation into a
    compromised operator account would grep for first. The `platform.`
    namespace already says where these came from; repeating it in the path
    cost 17 characters and bought nothing.
    """
    for prefix in ("/api/v1/platform", "/platform"):
        if path.startswith(prefix):
            path = path[len(prefix):] or "/"
            break
    return f"platform.{method.lower()}:{path}"[:_ACTION_MAX]


class _AuditedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        path = self.path

        async def handler(request: Request) -> Response:
            if request.method not in _MUTATING:
                return await original(request)
            status_code = 500
            try:
                response = await original(request)
                status_code = response.status_code
                return response
            except HTTPException as e:
                status_code = e.status_code
                raise
            finally:
                # A rejected attempt is worth recording too — on an operator
                # console, "someone tried" is exactly the interesting line.
                user = getattr(request.state, "platform_user", None)
                params = dict(request.path_params or {})
                tenant_target = params.get("tenant")
                try:
                    await audit.log_action(
                        PLATFORM_TENANT,
                        _action_for(request.method, path),
                        user=user or {"username": "anonymous", "user_id": "anonymous"},
                        target_type="tenant" if tenant_target else None,
                        target_id=str(tenant_target)[:80] if tenant_target else None,
                        details={"params": params, "status": status_code},
                        ip=audit.client_ip(request),
                    )
                except Exception:  # noqa: BLE001
                    # Never let bookkeeping break the operation it describes.
                    log.exception("platform audit write failed for %s %s",
                                  request.method, path)

        return handler


router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    dependencies=[Depends(get_platform_admin)],
    route_class=_AuditedRoute,
)

# The operator's own login pseudo-tenant (framework-KC, idp_url NULL).
# It's infrastructure, not a customer — hidden from the tenant list and
# protected from lifecycle operations so an operator can't delete their
# own way in.
PLATFORM_TENANT = os.getenv("PLATFORM_TENANT", "platform")


# ── payloads ────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    tenant: str = Field(min_length=1, max_length=100)
    contact_email: str
    valid_days: int = 365
    # optional onboarding in one shot
    agent_url: str | None = None
    idp_url: str | None = None
    idp_backend_secret: str | None = None
    email_domains: list[str] | None = None
    enabled_modules: list[str] | None = None
    display_name: str | None = None


class AgentUrlBody(BaseModel):
    agent_url: str


class IdpUrlBody(BaseModel):
    idp_url: str
    backend_secret: str | None = None


class EmailDomainsBody(BaseModel):
    email_domains: list[str]


class AiEnabledBody(BaseModel):
    ai_enabled: bool


class EnabledModulesBody(BaseModel):
    enabled_modules: list[str] | None = None


class RenewBody(BaseModel):
    valid_days: int = 365


class ActiveBody(BaseModel):
    is_active: bool


class SettingsBody(BaseModel):
    display_name: str | None = None
    logo_b64: str | None = None
    default_alert_email: str | None = None
    session_timeout_minutes: int | None = None
    auto_delete_months: int | None = None


class Contact(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    role: str | None = None


class ContactsBody(BaseModel):
    contacts: list[Contact]


class OperatorCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    email: str | None = None
    password: str = Field(min_length=8)


class PasswordReset(BaseModel):
    password: str = Field(min_length=8)


# ── license-server proxy helpers ────────────────────────────────

async def _lic(method: str, path: str, **kw) -> httpx.Response:
    url = f"{settings.license_server_url}{path}"
    headers = kw.pop("headers", {})
    headers["X-Internal-Key"] = settings.internal_secret
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.request(method, url, headers=headers, **kw)


def _json(r: httpx.Response, ok: tuple[int, ...] = (200,)):
    if r.status_code in ok:
        return r.json()
    try:
        detail = r.json().get("detail", r.text)
    except Exception:  # noqa: BLE001
        detail = r.text or "license-server error"
    raise HTTPException(status_code=r.status_code, detail=detail)


def _guard(tenant: str) -> None:
    """Hide the operator's own login pseudo-tenant from management."""
    if tenant == PLATFORM_TENANT:
        raise HTTPException(status_code=404, detail="Tenant not found")


# ── tenants ─────────────────────────────────────────────────────

@router.get("/tenants")
async def list_tenants():
    rows = _json(await _lic("GET", "/api/v1/tenants"))
    return [t for t in rows if t.get("tenant") != PLATFORM_TENANT]


@router.post("/tenants", status_code=201)
async def create_tenant(payload: TenantCreate):
    if payload.tenant == PLATFORM_TENANT:
        raise HTTPException(status_code=400, detail="Reserved tenant name")
    # 1) create the license (returns the keys the operator hands to the customer)
    created = _json(
        await _lic("POST", "/api/v1/license/create", json={
            "tenant": payload.tenant,
            "contact_email": payload.contact_email,
            "valid_days": payload.valid_days,
        }),
        ok=(200,),
    )
    # 2) optional one-shot onboarding fields
    t = payload.tenant
    if payload.agent_url:
        _json(await _lic("PUT", f"/api/v1/tenants/{t}/agent-url", json={"agent_url": payload.agent_url}))
    if payload.idp_url:
        _json(await _lic("PUT", f"/api/v1/tenants/{t}/idp-url",
                         json={"idp_url": payload.idp_url, "backend_secret": payload.idp_backend_secret}))
    if payload.email_domains is not None:
        _json(await _lic("PUT", f"/api/v1/tenants/{t}/email-domains", json={"email_domains": payload.email_domains}))
    if payload.enabled_modules is not None:
        _json(await _lic("PUT", f"/api/v1/tenants/{t}/enabled-modules", json={"enabled_modules": payload.enabled_modules}))
    if payload.display_name:
        _json(await _lic("PUT", f"/api/v1/tenants/{t}/settings", json={"display_name": payload.display_name}))
    return created


@router.get("/tenants/{tenant}")
async def get_tenant(tenant: str):
    _guard(tenant)
    info = _json(await _lic("GET", f"/api/v1/tenants/{tenant}/license-info"))
    settings_r = await _lic("GET", f"/api/v1/tenants/{tenant}/settings")
    if settings_r.status_code == 200:
        s = settings_r.json()
        info["display_name"] = s.get("display_name")
        info["logo_b64"] = s.get("logo_b64")
        info["default_alert_email"] = s.get("default_alert_email")
        info["session_timeout_minutes"] = s.get("session_timeout_minutes")
        info["auto_delete_months"] = s.get("auto_delete_months")
    mods_r = await _lic("GET", f"/api/v1/tenants/{tenant}/enabled-modules")
    info["enabled_modules"] = mods_r.json().get("enabled_modules") if mods_r.status_code == 200 else None
    return info


@router.put("/tenants/{tenant}/agent-url")
async def set_agent_url(tenant: str, body: AgentUrlBody):
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/agent-url", json=body.model_dump()))


@router.put("/tenants/{tenant}/idp-url")
async def set_idp_url(tenant: str, body: IdpUrlBody):
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/idp-url", json=body.model_dump()))


@router.put("/tenants/{tenant}/email-domains")
async def set_email_domains(tenant: str, body: EmailDomainsBody):
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/email-domains", json=body.model_dump()))


@router.put("/tenants/{tenant}/enabled-modules")
async def set_enabled_modules(tenant: str, body: EnabledModulesBody):
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/enabled-modules", json=body.model_dump()))


@router.put("/tenants/{tenant}/ai-enabled")
async def set_ai_enabled(tenant: str, body: AiEnabledBody):
    """License the AI function (KI-Verknüpfung) for a tenant — opt-in."""
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/ai-enabled", json=body.model_dump()))


@router.put("/tenants/{tenant}/settings")
async def set_settings(tenant: str, body: SettingsBody):
    _guard(tenant)
    data = body.model_dump(exclude_unset=True)
    r = await _lic("PUT", f"/api/v1/tenants/{tenant}/settings", json=data)
    return _json(r)


@router.put("/tenants/{tenant}/contacts")
async def set_contacts(tenant: str, body: ContactsBody):
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/contacts",
                            json={"contacts": [c.model_dump() for c in body.contacts]}))


@router.post("/tenants/{tenant}/renew")
async def renew(tenant: str, body: RenewBody):
    _guard(tenant)
    return _json(await _lic("POST", f"/api/v1/tenants/{tenant}/renew", json=body.model_dump()))


@router.put("/tenants/{tenant}/active")
async def set_active(tenant: str, body: ActiveBody):
    _guard(tenant)
    return _json(await _lic("PUT", f"/api/v1/tenants/{tenant}/active", json=body.model_dump()))


@router.delete("/tenants/{tenant}")
async def delete_tenant(tenant: str):
    _guard(tenant)
    return _json(await _lic("DELETE", f"/api/v1/tenants/{tenant}"))


# ── Product-owner management (platform-realm KC users) ──────────
# Uses the platform-backend confidential client (service account with
# manage/view/query-users on the platform realm). NEVER touches tenant
# users — a different realm entirely.

async def _kc_token() -> str:
    if not settings.platform_kc_client_secret:
        raise HTTPException(status_code=503, detail="platform-backend client secret not configured")
    url = f"{settings.keycloak_url.rstrip('/')}/realms/{settings.platform_realm}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=10, verify=settings.tls_verify_idp) as c:
        r = await c.post(url, data={
            "grant_type": "client_credentials",
            "client_id": settings.platform_kc_client_id,
            "client_secret": settings.platform_kc_client_secret,
        })
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"platform KC token failed ({r.status_code})")
    return r.json()["access_token"]


async def _kc(method: str, path: str, token: str, **kw) -> httpx.Response:
    base = f"{settings.keycloak_url.rstrip('/')}/admin/realms/{settings.platform_realm}"
    async with httpx.AsyncClient(timeout=15, verify=settings.tls_verify_idp) as c:
        return await c.request(method, f"{base}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)


@router.get("/operators")
async def list_operators():
    token = await _kc_token()
    r = await _kc("GET", "/users?max=500", token)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"KC user list failed ({r.status_code})")
    return [
        {"id": u.get("id"), "username": u.get("username"), "email": u.get("email"),
         "enabled": u.get("enabled", True)}
        for u in r.json()
    ]


@router.post("/operators", status_code=201)
async def create_operator(payload: OperatorCreate):
    token = await _kc_token()
    # 1) create user
    r = await _kc("POST", "/users", token, json={
        "username": payload.username, "email": payload.email,
        "firstName": payload.username, "lastName": "Operator",
        "enabled": True, "emailVerified": True, "requiredActions": [],
    })
    if r.status_code == 409:
        raise HTTPException(status_code=409, detail="Operator already exists")
    if r.status_code not in (201, 204):
        raise HTTPException(status_code=502, detail=f"KC create failed ({r.status_code})")
    loc = r.headers.get("location", "")
    uid = loc.rstrip("/").rsplit("/", 1)[-1]
    if not uid:
        found = await _kc("GET", f"/users?username={payload.username}&exact=true", token)
        uid = (found.json() or [{}])[0].get("id", "")
    # 2) password (non-temporary)
    await _kc("PUT", f"/users/{uid}/reset-password", token,
              json={"type": "password", "value": payload.password, "temporary": False})
    # 3) assign platform_admin realm role — REQUIRED. Without it the new
    # operator is locked out of every /platform/* endpoint (get_platform_admin
    # 403s → the console shows nothing). Fail loudly instead of silently
    # creating a powerless account. (Needs the platform-backend service
    # account to hold realm-management view-realm + manage-realm.)
    role_r = await _kc("GET", "/roles/platform_admin", token)
    if role_r.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"platform_admin role unreadable ({role_r.status_code}); "
                                   "operator created but NOT authorized — check the "
                                   "platform-backend service-account roles")
    role = role_r.json()
    map_r = await _kc("POST", f"/users/{uid}/role-mappings/realm", token,
                      json=[{"id": role["id"], "name": role["name"]}])
    if map_r.status_code not in (201, 204):
        raise HTTPException(status_code=502,
                            detail=f"platform_admin assignment failed ({map_r.status_code})")
    return {"ok": True, "id": uid, "username": payload.username}


@router.post("/operators/{uid}/reset-password")
async def reset_operator_password(uid: str, payload: PasswordReset):
    # `temporary: True` — the target must set their own password at next
    # login. It was False, which meant whoever performed the reset walked
    # away knowing a working, permanent password for another operator's
    # account: the highest-privileged accounts in the product, and the ones
    # whose actions the new audit chain attributes by name. An attribution
    # is only worth something if the account cannot be quietly borrowed.
    token = await _kc_token()
    r = await _kc("PUT", f"/users/{uid}/reset-password", token,
                  json={"type": "password", "value": payload.password, "temporary": True})
    if r.status_code not in (204, 200):
        raise HTTPException(status_code=502, detail=f"KC password reset failed ({r.status_code})")
    return {"ok": True}


@router.delete("/operators/{uid}")
async def delete_operator(uid: str, me: dict = Depends(get_platform_admin)):
    if uid == me.get("user_id"):
        raise HTTPException(status_code=400, detail="You cannot delete your own operator account")
    token = await _kc_token()
    r = await _kc("DELETE", f"/users/{uid}", token)
    if r.status_code not in (204, 200):
        raise HTTPException(status_code=502, detail=f"KC delete failed ({r.status_code})")
    return {"ok": True, "deleted": uid}


# ── agent reachability (health only — NO investigation data) ────

@router.get("/tenants/{tenant}/agent-health")
async def agent_health(tenant: str):
    _guard(tenant)
    r = await _lic("GET", f"/api/v1/tenants/{tenant}/agent-url")
    if r.status_code == 404:
        return {"reachable": False, "detail": "no agent URL configured", "agent_url": None}
    agent_url = _json(r).get("agent_url")
    health_url = f"{agent_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=8, verify=settings.tls_verify_idp) as client:
            hr = await client.get(health_url)
        return {
            "reachable": hr.status_code == 200,
            "status_code": hr.status_code,
            "agent_url": agent_url,
            # /health returns only {"status":"ok","service":"data-agent"} —
            # no tenant data crosses this boundary.
            "health": hr.json() if hr.headers.get("content-type", "").startswith("application/json") else None,
        }
    except httpx.HTTPError as e:
        return {"reachable": False, "detail": str(e), "agent_url": agent_url}


# ── framework metrics summary (operator-side only) ──────────────

@router.get("/metrics-summary")
async def metrics_summary():
    rows = [t for t in _json(await _lic("GET", "/api/v1/tenants")) if t.get("tenant") != PLATFORM_TENANT]
    active = sum(1 for t in rows if t.get("is_active") and not t.get("is_expired"))
    expired = sum(1 for t in rows if t.get("is_expired"))
    expiring = sum(1 for t in rows if not t.get("is_expired") and 0 <= (t.get("days_remaining") or 0) <= 30)
    # module manifests currently loaded in this worker (framework-side health)
    from app.services.osint_orchestrator import get_manifests
    manifests = get_manifests()
    return {
        "tenants_total": len(rows),
        "tenants_active": active,
        "tenants_expired": expired,
        "tenants_expiring_30d": expiring,
        "modules_loaded": sorted(manifests.keys()),
        "modules_count": len(manifests),
    }


@router.get("/audit")
async def platform_audit(
    limit: int = 200,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The operator's own action log — and ONLY the operator's own.

    Every route on this router is already audited by the `APIRoute` wrapper
    above, including rejected attempts. The tenant admin panel's audit view
    filters on `user["tenant"]`, and a platform admin is deliberately
    tenant-less — without this endpoint the console that creates tenants,
    sets agent URLs and renews licences would keep a record its own operator
    could not open.

    The platform boundary lists "audit log of own platform actions" as
    explicitly allowed and "tenant audit logs" as explicitly forbidden. The `WHERE` clause is
    that boundary: it is pinned to `PLATFORM_TENANT` and takes no tenant
    parameter, so there is no argument a caller could pass to widen it.
    """
    from sqlalchemy import func
    from app.models.audit import AuditLog

    limit = max(1, min(int(limit), 500))
    q = select(AuditLog).where(AuditLog.tenant == PLATFORM_TENANT)
    if action:
        q = q.where(AuditLog.action == action)
    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(
        q.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit)
    )).scalars().all()
    return {
        "total": total or 0,
        "entries": [
            {"id": str(r.id), "timestamp": r.timestamp.isoformat(),
             "user_name": r.user_name, "action": r.action,
             "target_type": r.target_type, "target_id": r.target_id,
             "details": r.details, "ip_address": r.ip_address,
             "entry_hash": r.entry_hash}
            for r in rows
        ],
    }


@router.get("/system-health")
async def system_health() -> dict:
    """Is the framework ITSELF healthy — the operator's own question.

    Without it the console could answer everything about the customers and
    nothing about the machine running under it. `GET /api/v1/health/deep`
    checks only Postgres and Redis; the module containers, the Tor egress and
    the licence server would be visible only over SSH. An operator console
    whose own stack is invisible sends its operator to a terminal, which is exactly where the console was
    supposed to stop being necessary.

    Deliberately NOT folded into `/api/v1/health/deep`: that route is an
    unauthenticated liveness probe used by Docker's healthcheck, it must stay
    cheap, and it must not fan out to sixteen services on every tick. This
    one is behind `get_platform_admin`, is called when a human looks, and can
    afford to ask.

    **Still inside the platform boundary.** Every probe here is a `/health` or
    `/manifest` call against the OPERATOR's own containers. Nothing reaches a
    tenant agent, and nothing returns case data — tenant reachability keeps
    living in `/platform/tenants/{tenant}/agent-health`.
    """
    from app.services.osint_orchestrator import MODULE_REGISTRY

    async def probe(name: str, url: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{url}/health")
            if r.status_code != 200:
                return {"name": name, "status": "degraded",
                        "detail": f"HTTP {r.status_code}"}
            return {"name": name, "status": "ok"}
        except Exception as e:  # noqa: BLE001
            return {"name": name, "status": "down", "detail": type(e).__name__}

    # Infrastructure the backend cannot work without.
    infra: dict[str, str] = {}
    try:
        from sqlalchemy import text
        from app.database import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        infra["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        infra["postgres"] = f"down: {type(e).__name__}"
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            await client.ping()
            infra["redis"] = "ok"
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001
        infra["redis"] = f"down: {type(e).__name__}"
    try:
        # `_lic` does not raise on a non-200, so the status is checked here.
        # A licence server answering 500 is not "ok", and treating it as such
        # would hide the one dependency that decides whether a tenant can log
        # in at all.
        r = await _lic("GET", "/health")
        infra["license"] = ("ok" if r.status_code == 200
                            else f"degraded: HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        infra["license"] = f"down: {type(e).__name__}"

    # The 14 OSINT modules, asked in parallel.
    import asyncio
    targets = [(n, getattr(settings, attr, "")) for n, attr in MODULE_REGISTRY]
    modules = list(await asyncio.gather(
        *[probe(n, u) for n, u in targets if u]))

    # The manifests this worker actually holds. A module that answers /health
    # but never delivered a manifest contributes NO tools to a search — a
    # failure mode that looks perfectly healthy from the outside.
    from app.services.osint_orchestrator import get_manifests
    loaded = get_manifests()
    for m in modules:
        man = loaded.get(m["name"])
        m["tools"] = len(man.get("tools", []) or []) if man else 0
        if m["status"] == "ok" and not man:
            m["status"] = "degraded"
            m["detail"] = "no manifest loaded — contributes no tools to a search"

    down = [m["name"] for m in modules if m["status"] == "down"]
    degraded = [m["name"] for m in modules if m["status"] == "degraded"]
    infra_bad = [k for k, v in infra.items() if v != "ok"]
    status = ("down" if (infra_bad or down) else
              "degraded" if degraded else "ok")
    return {
        "status": status,
        "infra": infra,
        "modules": sorted(modules, key=lambda m: m["name"]),
        "modules_total": len(modules),
        "modules_ok": sum(1 for m in modules if m["status"] == "ok"),
        "tools_total": sum(m["tools"] for m in modules),
        "problems": {"infra": infra_bad, "down": down, "degraded": degraded},
        # The operator's own dashboards. Rendered as a link rather than
        # embedded: Grafana carries its own auth and its own session.
        "grafana_url": "/grafana/",
    }


# ── Support tickets (operator side — sees ALL authorities' tickets) ──

class SupportMessageBody(BaseModel):
    body: str = Field(min_length=1)


class SupportStatusBody(BaseModel):
    status: str


@router.get("/support/tickets")
async def support_list(status: str | None = None, tenant: str | None = None):
    params = {}
    if status:
        params["status"] = status
    if tenant:
        params["tenant"] = tenant
    return _json(await _lic("GET", "/api/v1/support/tickets", params=params))


@router.get("/support/tickets/{ticket_id}")
async def support_get(ticket_id: str):
    return _json(await _lic("GET", f"/api/v1/support/tickets/{ticket_id}"))


@router.post("/support/tickets/{ticket_id}/messages")
async def support_reply(ticket_id: str, body: SupportMessageBody, me: dict = Depends(get_platform_admin)):
    return _json(await _lic("POST", f"/api/v1/support/tickets/{ticket_id}/messages", json={
        "author_role": "operator", "author_name": me.get("username") or "operator", "body": body.body,
    }))


@router.put("/support/tickets/{ticket_id}/status")
async def support_status(ticket_id: str, body: SupportStatusBody):
    return _json(await _lic("PUT", f"/api/v1/support/tickets/{ticket_id}/status", json={"status": body.status}))


@router.delete("/support/tickets/{ticket_id}")
async def support_delete(ticket_id: str):
    return _json(await _lic("DELETE", f"/api/v1/support/tickets/{ticket_id}"))


# ---- API keys (operator-global, Settings tab) -----------------------
# The framework operator's own service-provider keys (VirusTotal, HIBP,
# …) shared across all tenants. Stored in the license-server; the modules
# receive them per /run request (see osint_orchestrator). NOT tenant data.

class ApiKeysUpdate(BaseModel):
    values: dict[str, str]


class KeyTest(BaseModel):
    name: str
    value: str = ""


class NewsFeed(BaseModel):
    """One RSS/Atom source. `kind` reaches the graph so an analyst can tell
    an authority release from a newspaper article."""
    id: str = ""
    name: str = ""
    url: str
    kind: str = "other"
    lang: str = "de"
    enabled: bool = True


class NewsFeedsUpdate(BaseModel):
    feeds: list[NewsFeed]


class NewsFeedTest(BaseModel):
    url: str


class NewsSettingsUpdate(BaseModel):
    max_entries_per_feed: int | None = None
    max_results: int | None = None
    max_age_days: int | None = None


class NewsHarvestUpdate(BaseModel):
    enabled: bool | None = None
    authority_interval_min: int | None = None
    other_interval_min: int | None = None


class TelegramTest(BaseModel):
    api_id: str = ""
    api_hash: str = ""
    session: str = ""


class GhuntDeriveBody(BaseModel):
    companion: str = ""


class N8nAccessBody(BaseModel):
    enabled: bool


class AiSettingsBody(BaseModel):
    max_entities: int


@router.get("/ai-settings")
async def get_ai_settings():
    """Operator-tunable AI-function settings (currently the entity cap sent
    to the model per case)."""
    return {"max_entities": await ai_settings.get_max_entities(force=True)}


@router.put("/ai-settings")
async def set_ai_settings(body: AiSettingsBody):
    return {"max_entities": await ai_settings.set_max_entities(body.max_entities)}


class AiRatesBody(BaseModel):
    rate_in_per_m: float | None = None
    rate_out_per_m: float | None = None


@router.get("/ai-usage")
async def get_ai_usage():
    """Cumulative AI token usage + estimated cost. NB: Google does not expose
    the account's remaining credit via the API key (`balance_available:false`);
    only token usage is available, which we accumulate per run."""
    return await ai_usage.get_usage()


@router.post("/ai-usage/reset")
async def reset_ai_usage():
    await ai_usage.reset()
    return await ai_usage.get_usage()


@router.put("/ai-usage/rates")
async def set_ai_rates(body: AiRatesBody):
    await ai_usage.set_rates(body.rate_in_per_m, body.rate_out_per_m)
    return await ai_usage.get_usage()


@router.get("/n8n-version")
async def n8n_version():
    """Running n8n version vs the latest on npm. current is parsed from the
    editor's sentry meta (unauth); latest from the npm registry."""
    import base64
    import json as _json
    import re

    current = None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{settings.n8n_url}/")
        m = re.search(r'n8n:config:sentry"\s+content="([^"]+)"', r.text)
        if m:
            rel = _json.loads(base64.b64decode(m.group(1))).get("release", "")
            current = rel.split("@")[-1] or None
    except Exception:  # noqa: BLE001
        pass

    latest = None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://registry.npmjs.org/n8n/latest")
        latest = (r.json() or {}).get("version")
    except Exception:  # noqa: BLE001
        pass

    def _lt(a: str | None, b: str | None) -> bool:
        # semver-ish "a < b" on the first 3 numeric parts (avoids a false
        # "update available" when the running version is AHEAD of npm's latest,
        # e.g. the docker :latest tag leads the npm release).
        def parts(v):
            nums = [int(x) for x in re.findall(r"\d+", v or "")[:3]]
            return (nums + [0, 0, 0])[:3]
        return bool(a and b and parts(a) < parts(b))

    return {
        "current": current,
        "latest": latest,
        "update_available": _lt(current, latest),
    }


@router.post("/n8n-update")
async def n8n_update():
    """Pull the latest n8n image + recreate the container via the isolated
    updater sidecar. n8n is briefly unavailable while it restarts."""
    try:
        async with httpx.AsyncClient(timeout=600) as c:
            r = await c.post(f"{settings.updater_url}/update",
                             headers={"X-Internal-Key": settings.updater_secret})
        data = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Updater unreachable: {type(e).__name__}")
    if not data.get("ok"):
        raise HTTPException(status_code=500,
                            detail="n8n update failed. " + (data.get("log", "")[-300:]))
    return {"ok": True, "log": (data.get("log", "") or "")[-1500:]}


@router.get("/n8n-access")
async def get_n8n_access():
    """Whether the n8n editor is reachable from outside (via nginx). n8n
    keeps running either way — this only gates the public /n8n/ route."""
    return {"enabled": await n8n_access.is_enabled(force=True)}


@router.put("/n8n-access")
async def set_n8n_access(body: N8nAccessBody):
    await n8n_access.set_enabled(body.enabled)
    return {"enabled": body.enabled}


@router.get("/tenants/{tenant}/data-exposure")
async def tenant_data_exposure(tenant: str,
                               db: AsyncSession = Depends(get_db),
                               admin: dict = Depends(get_platform_admin)):
    """What this installation holds about one tenant, measured.

    The answer an Auftragsverarbeitungsvertrag needs, generated from the
    live schema rather than from prose that drifts. Reads only the
    OPERATOR's database — the customer's own store is deliberately not
    inspected, because enumerating a customer's case files to prove the
    operator does not hold them would refute itself.

    Platform-admin only, and it exposes counts and column meanings, never
    values. A column added without a classification is reported as
    `unclassified`, which is the useful failure.
    """
    from app.services import data_exposure

    return await data_exposure.report(db, tenant)


# ── Operator mail (licence-expiry warnings) ─────────────────────
#
# The operator's OWN mail server, as opposed to the per-tenant one the
# customer configures in /admin. Two senders, two mailboxes, one transport
# implementation (services/notify.send_email takes a plain config dict).


class OperatorMailPayload(BaseModel):
    enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None   # omit to keep, "" to clear
    smtp_from: str | None = None
    smtp_verify_tls: bool | None = None
    warn_days: list[int] | None = None
    reply_to: str | None = None


class OperatorMailTest(BaseModel):
    recipient: str | None = None


@router.get("/operator-mail")
async def get_operator_mail(admin: dict = Depends(get_platform_admin)):
    from app.services import operator_notify
    return await operator_notify.describe()


@router.put("/operator-mail")
async def put_operator_mail(payload: OperatorMailPayload,
                            admin: dict = Depends(get_platform_admin)):
    from app.services import operator_notify
    try:
        # Every route on this router is audited by the middleware above, so
        # there is no explicit log_action here — a second one would double
        # the entry and the two could disagree about the outcome.
        return await operator_notify.save_config(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/operator-mail/test")
async def test_operator_mail(payload: OperatorMailTest,
                             admin: dict = Depends(get_platform_admin)):
    """Always 200, including on failure — the failure detail is the point."""
    from app.services import operator_notify
    result = await operator_notify.send_test(payload.recipient)
    return result.as_dict()


class ExpiryCheckPayload(BaseModel):
    # Re-send warnings already recorded. Off by default: clicking the
    # button twice must not mail the customer twice.
    force: bool = False


@router.post("/operator-mail/run-expiry-check")
async def run_expiry_check(payload: ExpiryCheckPayload | None = None,
                           admin: dict = Depends(get_platform_admin)):
    """Run the licence-expiry job now instead of waiting for the daily tick.
    Reports what it did, including tenants it could not warn and those
    already warned about this threshold."""
    from app.services import operator_notify
    return await operator_notify.run_license_expiry_check(
        force=bool(payload and payload.force))


@router.get("/api-keys")
async def get_api_keys():
    """Registry + set/effective flags. Secret values are masked — never
    returned in clear."""
    return await api_keys.describe()


@router.put("/api-keys")
async def put_api_keys(payload: ApiKeysUpdate):
    """Persist keys. Empty string clears a key (module falls back to .env).
    A field left out is untouched — the UI omits unchanged secret fields."""
    await api_keys.save_keys(payload.values)
    return {"status": "saved"}


@router.get("/news-feeds")
async def get_news_feeds():
    """Operator-maintained RSS/news feed list used by module-news.

    An empty list is not an error: module-news then falls back to its own
    verified defaults, so a fresh install still searches something.
    """
    feeds = await news_feeds.get_feeds(force=True)
    return {"feeds": feeds, "kinds": list(news_feeds.VALID_KINDS),
            "settings": await news_feeds.get_settings(force=True),
            "max_placeholder": news_feeds.MAX_PLACEHOLDER,
            # Per-feed fetch health so a source that stopped answering is
            # visible here, not buried in a search note.
            "health": await news_feeds.get_health()}


@router.put("/news-feeds")
async def put_news_feeds(payload: NewsFeedsUpdate):
    """Replace the whole list. Feeds are public URLs, stored in clear."""
    saved = await news_feeds.save_feeds([f.model_dump() for f in payload.feeds])
    return {"status": "saved", "feeds": saved}


@router.put("/news-settings")
async def put_news_settings(payload: NewsSettingsUpdate):
    """Search limits: entries fetched per feed, hits returned, max age."""
    vals = {k: v for k, v in payload.model_dump().items() if v is not None}
    return {"settings": await news_feeds.save_settings(vals)}


# ── Telegram channels (username sweep) ───────────────────────────────

class TgChannelIn(BaseModel):
    id: str | None = None
    handle: str
    category: str = "other"
    note: str = ""
    source: str = "manual"
    enabled: bool = False


class TgChannelsUpdate(BaseModel):
    channels: list[TgChannelIn] = Field(default_factory=list)


class TgChannelsBulk(BaseModel):
    text: str
    category: str = "other"
    enabled: bool = False


class TgChannelsImport(BaseModel):
    files: list[str] = Field(default_factory=list)


@router.get("/telegram-channels")
async def get_telegram_channels():
    """Operator-maintained Telegram channel pool for the username sweep.

    `enabled` marks the subset that is actually swept. The pool may hold a
    thousand handles; only the enabled ones cost search time, and the module
    still caps them at TELEGRAM_HUNT_MAX_CHANNELS.
    """
    items = await telegram_channels.get_channels(force=True)
    cats: dict[str, int] = {}
    for c in items:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    return {
        "channels": items,
        "total": len(items),
        "enabled": sum(1 for c in items if c["enabled"]),
        "categories": cats,
        "sources": sorted(telegram_channels.DDCTI_FILES.keys()),
        "sweep_cap": int(os.environ.get("TELEGRAM_HUNT_MAX_CHANNELS") or "40"),
    }


@router.put("/telegram-channels")
async def put_telegram_channels(payload: TgChannelsUpdate):
    """Replace the whole list. Handles are public, stored in clear."""
    saved = await telegram_channels.save_channels(
        [c.model_dump() for c in payload.channels])
    return {"status": "saved", "total": len(saved),
            "enabled": sum(1 for c in saved if c["enabled"])}


@router.post("/telegram-channels/bulk")
async def bulk_telegram_channels(payload: TgChannelsBulk):
    """Add pasted handles. Accepts one per line, comma separated, `@handle`
    or full t.me URLs, with `#` comments — whatever is actually in the
    clipboard. Existing entries keep their settings."""
    parsed = telegram_channels.parse_bulk(
        payload.text, category=payload.category, source="manual",
        enabled=payload.enabled)
    existing = await telegram_channels.get_channels(force=True)
    merged, added, _ = telegram_channels.merge(existing, parsed)
    saved = await telegram_channels.save_channels(merged)
    return {"status": "saved", "parsed": len(parsed), "added": added,
            "total": len(saved),
            "enabled": sum(1 for c in saved if c["enabled"])}


@router.post("/telegram-channels/import")
async def import_telegram_channels(payload: TgChannelsImport):
    """Refresh the pool from deepdarkCTI.

    Imported channels arrive DISABLED. Every username search sweeps the
    enabled set, so importing ~961 handles as active would make each search
    hopeless and then silently truncate to the first 40. The operator picks
    what to sweep.

    Already-stored handles are left exactly as they are — a refresh must
    never un-sweep a channel somebody turned on.
    """
    incoming = await telegram_channels.fetch_deepdarkcti(payload.files or None)
    existing = await telegram_channels.get_channels(force=True)
    merged, added, _ = telegram_channels.merge(existing, incoming)
    saved = await telegram_channels.save_channels(merged)
    return {"status": "imported", "fetched": len(incoming), "added": added,
            "total": len(saved),
            "enabled": sum(1 for c in saved if c["enabled"])}


class TgSourceIn(BaseModel):
    id: str | None = None
    url: str
    category: str = "threat_actor"
    enabled: bool = True


class TgSourcesUpdate(BaseModel):
    sources: list[TgSourceIn] = Field(default_factory=list)


class TgScanBody(BaseModel):
    source_id: str | None = None


class TgCheckBody(BaseModel):
    """Which channels to probe. `only_enabled` keeps a routine check cheap;
    `limit` bounds a full-pool sweep so one click cannot fire 960 requests
    unless the operator asks for it."""
    only_enabled: bool = True
    limit: int = 200


class TgCleanupBody(BaseModel):
    """`remove=False` only disables — the safe default, because an
    invite-only channel probes exactly like a deleted one."""
    remove: bool = False
    only_enabled: bool = False


@router.get("/telegram-sources")
async def get_telegram_sources():
    """Operator-defined harvest sources (GitHub repos or raw list URLs)."""
    return {"sources": await telegram_channels.get_sources(force=True)}


@router.put("/telegram-sources")
async def put_telegram_sources(payload: TgSourcesUpdate):
    saved = await telegram_channels.save_sources(
        [s.model_dump() for s in payload.sources])
    return {"status": "saved", "sources": saved}


@router.post("/telegram-sources/scan")
async def scan_telegram_sources(payload: TgScanBody):
    """Pull every enabled source now. New handles arrive disabled."""
    return await telegram_channels.harvest_sources(only_id=payload.source_id)


@router.post("/telegram-channels/check")
async def check_telegram_channels(payload: TgCheckBody):
    """Probe channels against t.me and record what came back.

    Keyless on purpose: resolving a thousand handles through the collection
    account is how that account earns a flood-wait, and it is a real account
    whose loss would disable every authenticated Telegram tool.
    """
    items = await telegram_channels.get_channels(force=True)
    pool = [c for c in items if c["enabled"]] if payload.only_enabled else items
    handles = [c["handle"] for c in pool][: max(1, min(payload.limit, 1000))]
    results = await telegram_channels.check_liveness(handles)
    saved = await telegram_channels.apply_liveness(results)
    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"checked": len(handles), "counts": counts,
            "total": len(saved),
            "enabled": sum(1 for c in saved if c["enabled"])}


@router.post("/telegram-channels/cleanup")
async def cleanup_telegram_channels(payload: TgCleanupBody):
    """Act on channels that showed no public page.

    Default is to DISABLE, not delete. `no_public_page` is the same signature
    a private, invite-only channel produces — and those are precisely the ones
    worth watching, so throwing them away on this signal would be the more
    expensive mistake. Deleting stays available, but has to be asked for.

    Channels whose check errored are never touched: an error is a statement
    about the probe, not about the channel.
    """
    items = await telegram_channels.get_channels(force=True)
    hit = [c for c in items
           if c["status"] == telegram_channels.STATUS_NO_PAGE
           and (not payload.only_enabled or c["enabled"])]
    ids = {c["id"] for c in hit}
    if payload.remove:
        kept = [c for c in items if c["id"] not in ids]
    else:
        kept = [{**c, "enabled": False} if c["id"] in ids else c for c in items]
    saved = await telegram_channels.save_channels(kept)
    return {"status": "cleaned", "affected": len(hit),
            "removed": len(hit) if payload.remove else 0,
            "disabled": 0 if payload.remove else len(hit),
            "total": len(saved),
            "enabled": sum(1 for c in saved if c["enabled"])}


# ── Crime forums (forum hunt) ────────────────────────────────────────

class ForumIn(BaseModel):
    id: str | None = None
    domain: str
    category: str = "other"
    note: str = ""
    source: str = "manual"
    enabled: bool = True


class ForumsUpdate(BaseModel):
    forums: list[ForumIn] = Field(default_factory=list)


class ForumsBulk(BaseModel):
    text: str
    category: str = "other"
    enabled: bool = True


class ForumsDefaults(BaseModel):
    """`enabled` applies to the entries this call ADDS. Domains already in
    the store keep whatever the operator decided about them."""
    enabled: bool = True


@router.get("/crime-forums")
async def get_crime_forums():
    """Operator-maintained crime-forum list for `forums/crime_forum_hunt`.

    `enabled` marks the subset that is actually dorked. Every hunt spends one
    search-engine query per enabled forum, so the enabled count — not the
    pool size — is what a search costs.
    """
    items = await crime_forums.get_forums(force=True)
    cats: dict[str, int] = {}
    for f in items:
        cats[f["category"]] = cats.get(f["category"], 0) + 1
        # Derived here rather than stored: the summary is a function of the
        # log, and a stored copy would be wrong the moment a probe runs.
        f["reach_history"] = crime_forums.probe_summary(f.get("reach_log", ""))
        f["access_history"] = crime_forums.probe_summary(f.get("access_log", ""))
    # How many entries are still sitting on an inconclusive answer. This is
    # the number the operator acts on: it says how much of the pool has not
    # actually been measured yet, as opposed to measured and found dead.
    inconclusive = sum(
        1 for f in items
        if crime_forums.is_retryable(str(f.get("access_status") or ""),
                                     str(f.get("access_log") or "")))
    return {
        "forums": items,
        "inconclusive_access": inconclusive,
        "probe_log_len": crime_forums.PROBE_LOG_LEN,
        "total": len(items),
        "enabled": sum(1 for f in items if f["enabled"]),
        "categories": cats,
        "available_categories": crime_forums.CATEGORIES,
        # Split by surface: the clearnet count is what a hunt costs in
        # search-engine queries, the onion count is a recognition table and
        # costs nothing per search. One number for both would hide that.
        "clearnet": sum(1 for f in items if f["surface"] == "clearnet"),
        "onion": sum(1 for f in items if f["surface"] == "onion"),
        "enabled_clearnet": sum(1 for f in items
                                if f["enabled"] and f["surface"] == "clearnet"),
        "hunt_cap": int(os.environ.get("CRIME_FORUM_MAX") or "40"),
        # So the console can say "you are running the built-in list" instead
        # of showing an empty table that looks like a broken panel.
        "defaults_count": len(crime_forums.DEFAULT_FORUMS),
    }


@router.put("/crime-forums")
async def put_crime_forums(payload: ForumsUpdate):
    """Replace the whole list. Domains are public, stored in clear."""
    saved = await crime_forums.save_forums([f.model_dump() for f in payload.forums])
    return {"status": "saved", "total": len(saved),
            "enabled": sum(1 for f in saved if f["enabled"])}


@router.post("/crime-forums/bulk")
async def bulk_crime_forums(payload: ForumsBulk):
    """Add pasted domains. Accepts one per line, comma separated, bare hosts
    or full URLs, with `#` comments. Existing entries keep their settings."""
    parsed = crime_forums.parse_bulk(payload.text, category=payload.category,
                                     source="manual", enabled=payload.enabled)
    existing = await crime_forums.get_forums(force=True)
    merged, added = crime_forums.merge(existing, parsed)
    saved = await crime_forums.save_forums(merged)
    return {"status": "saved", "parsed": len(parsed), "added": added,
            "total": len(saved),
            "enabled": sum(1 for f in saved if f["enabled"])}


@router.post("/crime-forums/defaults")
async def seed_crime_forums(payload: ForumsDefaults):
    """Fold the runner's built-in list into the store.

    Used to populate an empty store on day one, and to pull in additions to
    the built-in list after an update. Already-stored domains are left
    exactly as they are — re-seeding must never re-enable a forum the
    operator switched off.
    """
    existing = await crime_forums.get_forums(force=True)
    merged, added = crime_forums.merge(
        existing, crime_forums.default_records(enabled=payload.enabled))
    saved = await crime_forums.save_forums(merged)
    return {"status": "seeded", "added": added, "total": len(saved),
            "enabled": sum(1 for f in saved if f["enabled"])}


class ForumCheckBody(BaseModel):
    """`index` is the default because it answers the question that decides
    whether a forum earns its slot, and does so without touching the host."""
    mode: str = "index"
    only_enabled: bool = False
    limit: int = 200
    # Re-probe entries whose last host-touching result was inconclusive
    # (unreachable / unknown / error) instead of preferring never-checked
    # ones. Without this, "unchecked first" means a row that once timed out
    # counts as measured forever — which leaves many entries sitting at
    # `unreachable` after a full sweep although almost all of them were
    # dropped Tor circuits rather than dead boards.
    recheck: bool = False
    # Re-ask verdicts that `is_retryable` considers settled — a `blocked`
    # entry whose log already confirms it three times. Off by default:
    # asking a settled host again on every sweep spends Tor circuits to
    # learn nothing, and Tor capacity is the scarce resource here. Worth
    # switching on after a change to the fingerprint approach, when the
    # question is genuinely open again.
    force_verdicts: bool = False


class ForumCleanupBody(BaseModel):
    """`remove=False` only disables — the safe default. A forum can drop out
    of an index for a while and come back, and the entry costs nothing while
    it is switched off."""
    remove: bool = False


@router.post("/crime-forums/import")
async def import_crime_forums():
    """Fold deepdarkCTI's `forum.md` into the pool.

    Imports arrive **disabled**: that file yields ~187 clearnet hosts and the
    hunt spends one search-engine query per ENABLED forum against a cap of
    40. Importing them active would not search more — it would make every
    hunt slow and then silently truncate.

    Onion entries come in too, tagged `surface: onion`. They are not dork
    targets (no clearnet index carries a hidden service); they are the
    recognition table that lets the darknet sweep name a hit.

    The upstream ONLINE/OFFLINE column is kept as a note and never used as a
    filter — it has listed `xss.is` as OFFLINE while a Tor probe found it
    online.
    """
    try:
        incoming, stats = await crime_forums.fetch_deepdarkcti()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502,
                            detail=f"deepdarkCTI unreachable: {e}") from e
    existing = await crime_forums.get_forums(force=True)
    merged, added = crime_forums.merge(existing, incoming)
    saved = await crime_forums.save_forums(merged)
    return {"status": "imported", "fetched": len(incoming), "added": added,
            "total": len(saved),
            "enabled": sum(1 for f in saved if f["enabled"]),
            "clearnet": stats["clearnet"], "onion": stats["onion"],
            # Rows whose URL was not a usable host at all. Reported rather
            # than swallowed: a silent drop and a clean import look the same.
            "unusable": stats["unusable"],
            "by_status": stats["by_status"]}


@router.post("/crime-forums/check")
async def check_crime_forums(payload: ForumCheckBody):
    """Probe the stored forums and record what came back.

    Two probes, deliberately separate (see `services/crime_forums.py`):

    * `index` — how much of the forum the search engine has. **No contact
      with the forum.** This is the operationally decisive one: the hunt
      asks a search engine, so an un-indexed forum yields nothing no matter
      how alive it is.
    * `reach` — is the host answering, asked **over Tor**, so the framework
      never connects to a crime forum from the operator's own address.
    """
    if payload.mode not in ("index", "reach", "access", "both"):
        raise HTTPException(status_code=400,
                            detail="mode must be index, reach, access or both")
    items = await crime_forums.get_forums(force=True)
    pool = [f for f in items if f["enabled"]] if payload.only_enabled else items
    # Never-checked entries first.
    #
    # One batch is capped at 200 (a probe per forum, and the search API has a
    # rate limit). Taking the list from the top meant a pool larger than that
    # could never be finished: on a pool of, say, 334 entries the first run
    # covers 200 and every further run re-checks the SAME 200 while 134
    # stay permanently unreachable — a cap that quietly turns into "these
    # rows can never be measured".
    #
    # Sorting unchecked-first makes repeated runs converge on full coverage,
    # and `remaining` tells the operator how many passes are left instead of
    # leaving them to guess whether the button did anything.
    #
    # Keyed on the field THIS mode writes, not always on `index_status`: an
    # `access` run sorted by index coverage would take the same head of the
    # list every time and re-probe forums it had already answered for, which is
    # the exact cap-becomes-a-wall defect that unchecked-first was added to fix.
    marker = {"index": "index_status", "reach": "reach_status",
              "access": "access_status", "both": "index_status"}[payload.mode]
    logfield = {"reach": "reach_log", "access": "access_log"}.get(payload.mode)

    if payload.recheck and logfield:
        # Ask again where the answer was inconclusive, fewest probes first so
        # coverage spreads instead of deepening on the same few hosts. This is
        # the counterpart to "unchecked first": that rule converges on full
        # coverage, this one converges on a REPEATED measurement, and only the
        # second can tell a flaky circuit from a dead board.
        # `blocked` is included. It used to be treated as final, and a large
        # share of such entries answered normally when asked by hand — silently dropped from the searchable set, and looking
        # decided rather than unchecked. `is_retryable` re-asks a verdict
        # until the log has confirmed it three times, so this converges
        # instead of spending Tor circuits on it forever.
        pool = [f for f in pool
                if payload.force_verdicts
                or crime_forums.is_retryable(str(f.get(marker) or ""),
                                             str(f.get(logfield) or ""))]
        pool = sorted(pool, key=lambda f: len(
            [p for p in str(f.get(logfield) or "").split(",") if p]))
        remaining_pool = pool
    else:
        pool = sorted(pool, key=lambda f: bool(f.get(marker)))
        remaining_pool = [f for f in pool if not f.get(marker)]
    # `access` makes two Tor requests per host where `index` makes one API call,
    # so a 200-host batch would run for the better part of an hour. Smaller
    # batch, same contract: the answer says how many are still open.
    ceiling = 50 if payload.mode == "access" else 200
    batch = max(1, min(payload.limit, ceiling))
    domains = [f["domain"] for f in pool][:batch]
    remaining = max(0, len(remaining_pool) - len(domains))
    if not domains:
        return {"status": "nothing to check", "checked": 0, "counts": {},
                "remaining": 0}
    try:
        results = await crime_forums.check_forums(domains, payload.mode)
    except httpx.HTTPError as e:
        # The module being down is an operator-side fact, not a statement
        # about any forum — never write a status on the back of it.
        raise HTTPException(status_code=502,
                            detail=f"module-forums unreachable: {e}") from e
    saved = await crime_forums.apply_check(results)
    counts: dict[str, int] = {}
    for res in results.values():
        for field in ("index_status", "reach_status", "access_status"):
            val = res.get(field)
            if val:
                counts[val] = counts.get(val, 0) + 1
    return {"status": "checked", "mode": payload.mode, "checked": len(results),
            "counts": counts, "total": len(saved),
            # How many entries this pass could NOT reach. Reported rather than
            # left implicit: a silent cap reads as "everything was measured".
            "remaining": remaining,
            "enabled": sum(1 for f in saved if f["enabled"])}


@router.post("/crime-forums/cleanup")
async def cleanup_crime_forums(payload: ForumCleanupBody):
    """Act on forums the index probe found nothing for.

    Default is to DISABLE, not delete: `not_indexed` is a statement about
    what a search engine currently has, and that can change back. Deleting
    stays available but has to be asked for. Forums whose check errored, or
    that were never checked, are never touched — an error is a statement
    about the probe, not about the forum.
    """
    items = await crime_forums.get_forums(force=True)
    # Onion entries can never be "indexed" — no clearnet engine carries a
    # hidden service — so they are excluded explicitly. Without this the
    # cleanup would offer to disable every onion forum in the pool for
    # failing a test that does not apply to it.
    hit = [f for f in items
           if f.get("index_status") == crime_forums.IDX_NOT_INDEXED
           and f.get("surface") != crime_forums.SURFACE_ONION]
    ids = {f["id"] for f in hit}
    if payload.remove:
        kept = [f for f in items if f["id"] not in ids]
    else:
        kept = [{**f, "enabled": False} if f["id"] in ids else f for f in items]
    saved = await crime_forums.save_forums(kept)
    return {"status": "cleaned", "affected": len(hit),
            "removed": len(hit) if payload.remove else 0,
            "disabled": 0 if payload.remove else len(hit),
            "total": len(saved),
            "enabled": sum(1 for f in saved if f["enabled"])}


class ForumIndexRefresh(BaseModel):
    index: str


@router.get("/forum-indexes")
async def get_forum_indexes():
    """Age, size and refresh state of the two forum reference indexes.

    These are the lookup tables `threat_actor_check` and `linkbase_lookup`
    read — content-independent reference data, no case link. Not to be
    confused with case findings, which live on the customer's agent.
    """
    return await forum_indexes.get_status()


@router.post("/forum-indexes/refresh")
async def refresh_forum_index(payload: ForumIndexRefresh):
    """Rebuild one index now. Returns immediately — the module runs it in a
    background thread; poll `GET /forum-indexes` for progress.

    One at a time by design: rebuilding the actor index holds the loaded
    copy and the new one at once, which can get module-forums OOM-killed.
    """
    try:
        return await forum_indexes.trigger(payload.index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502,
                            detail=f"module-forums unreachable: {e}") from e


@router.post("/news-feeds/test")
async def test_news_feed(payload: NewsFeedTest):
    """Fetch a feed once and report whether it yields entries.

    Reports the entry COUNT, not just reachability: a feed that answers 200
    with an HTML page parses to zero entries, and that failure would
    otherwise only show up as a search quietly covering one source less.
    """
    return await news_feeds.probe_feed(payload.url.strip())


# --- News harvester (background RSS cache) --------------------------------
# These read/trigger the framework-DB news cache. That is operator-global
# PUBLIC news data (the feed list lives in this same console) — NOT tenant
# case/entity data — so it stays within the platform sovereignty boundary.

@router.get("/news-harvester")
async def get_news_harvester(db: AsyncSession = Depends(get_db)):
    """Schedule + article statistics + per-feed poll state for the console."""
    return await news_store.harvester_status(db)


@router.put("/news-harvester")
async def put_news_harvester(payload: NewsHarvestUpdate):
    """Update the harvest schedule (intervals + on/off). Effective next tick."""
    vals = {k: v for k, v in payload.model_dump().items() if v is not None}
    return {"settings": await news_feeds.save_harvest_settings(vals)}


@router.post("/news-harvester/run")
async def run_news_harvester(db: AsyncSession = Depends(get_db)):
    """Fetch every enabled feed right now (ignores the due-timers and the
    on/off switch). The Owner-console 'fetch newest' button."""
    summary = await news_store.harvest_once(db, force=True)
    return {"status": "done", "summary": summary}


@router.post("/api-keys/test")
async def test_api_key(payload: KeyTest):
    """Live provider check. Tests the supplied value, or — if none — the
    currently stored/effective value for that key."""
    value = payload.value.strip()
    if not value:
        keys = await api_keys.load_keys(force=True)
        value = keys.get(payload.name, "")
    return await api_keys.validate_key(payload.name, value)


@router.post("/api-keys/test-telegram")
async def test_telegram(payload: TelegramTest):
    """Verify Telegram api_id/api_hash/StringSession by opening it in the
    messenger module (Telethon). Falls back to stored values for any empty
    field, so 'Test' works on already-saved creds."""
    keys = await api_keys.load_keys(force=True)
    api_id = payload.api_id.strip() or keys.get("TELEGRAM_API_ID", "")
    api_hash = payload.api_hash.strip() or keys.get("TELEGRAM_API_HASH", "")
    session = payload.session.strip() or keys.get("TELEGRAM_SESSION", "")
    return await api_keys.validate_telegram(api_id, api_hash, session)


@router.post("/api-keys/ghunt-derive")
async def ghunt_derive(payload: GhuntDeriveBody):
    """In-panel GHunt setup: derive a long-lived master token from the GHunt
    Companion base64 blob (or an oauth_token) — the server side of
    `ghunt login`. Returns {ok, master_token, account}; the UI drops the
    token into the GHUNT_CREDS field."""
    return await api_keys.derive_ghunt(payload.companion.strip())


# ── Case reconciliation ────────────────────────────
#
# The framework's case metadata and the customer's investigation store can
# drift apart: a case may exist only on the agent, or only in the framework.
#
# Why the agent-only direction is the one that matters: the auto-delete
# routine iterates FRAMEWORK cases. A case that exists only on the agent is
# therefore never examined and never deleted — its entities outlive every
# retention rule, unreachable through any user interface because the case
# they belong to does not exist there. For an authority that is the data
# controller, that is a retention problem, not untidiness.
#
# Deliberately NOT wired into the automatic purge. Deleting customer
# investigation data that has no counterpart here is a judgement about
# somebody else's case file; it belongs to a person who confirms it, not to a
# cron job that runs at 03:15.

class OrphanDeleteBody(BaseModel):
    """Explicit id list — no "delete all orphans" verb.

    Making the caller name each case is the point: this deletes investigation
    data in the customer's own store, and a bulk verb invites exactly the
    click nobody meant to make.
    """
    case_ids: list[str]


@router.get("/tenants/{tenant}/case-drift")
async def tenant_case_drift(tenant: str, db: AsyncSession = Depends(get_db)):
    """Compare this tenant's framework cases against its agent's.

    Read-only. Returns three groups so the operator can tell the harmless
    difference from the harmful one:

      * `agent_only`   — the retention problem described above.
      * `framework_only` — metadata whose findings never arrived. Usually a
        freshly created case that has not been searched yet, or one created
        while the agent was down. Harmless, but worth seeing.
      * `in_sync`      — count only.
    """
    fw_rows = (await db.execute(
        select(Case.id, Case.case_number, Case.title, Case.status)
        .where(Case.tenant == tenant)
    )).all()
    fw = {str(r[0]): {"id": str(r[0]), "case_number": r[1], "title": r[2],
                      "status": r[3]} for r in fw_rows}

    try:
        body = await get_from_agent(tenant, "/api/cases")
    except TenantNotConfigured:
        return {"tenant": tenant, "agent": "not configured",
                "agent_only": [], "framework_only": list(fw.values()),
                "in_sync": 0}
    except (AgentUnavailable, AgentAuthError) as e:
        # Never present "cannot ask" as "nothing to report" — the whole point
        # of this view is to surface a discrepancy.
        raise HTTPException(status_code=502, detail=f"Agent not reachable: {e}")

    ag = {c["id"]: c for c in (body.get("cases") or [])}
    agent_only = [ag[i] for i in ag.keys() - fw.keys()]
    framework_only = [fw[i] for i in fw.keys() - ag.keys()]
    return {
        "tenant": tenant,
        "agent_only": sorted(agent_only, key=lambda c: c.get("created_at") or ""),
        "framework_only": framework_only,
        "in_sync": len(ag.keys() & fw.keys()),
        "orphan_entities": sum(int(c.get("entities") or 0) for c in agent_only),
    }


@router.post("/tenants/{tenant}/case-drift/delete")
async def delete_orphan_cases(
    tenant: str, payload: OrphanDeleteBody, request: Request,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_platform_admin),
):
    """Delete agent-side cases that have no counterpart in the framework.

    Two guards, both deliberate:

    * **Re-checked server-side.** A case id that DOES exist in the framework
      is refused, not deleted. The ordinary cascade exists for those, it runs
      under the tenant's own admin, and it deletes both sides. This endpoint
      must never become a back door around it.
    * **Audited into the TENANT's chain**, not the operator's. The customer's
      own audit trail is where a deletion of their investigation data has to
      appear, even when the operator is the one who triggered it.
    """
    fw_ids = {str(r[0]) for r in (await db.execute(
        select(Case.id).where(Case.tenant == tenant))).all()}

    deleted, refused, failed = [], [], []
    for cid in payload.case_ids[:100]:
        if cid in fw_ids:
            refused.append(cid)
            continue
        try:
            await delete_on_agent(tenant, f"/api/cases/{cid}")
            deleted.append(cid)
            await audit.log_action(
                tenant, "case.orphan_delete", user=admin,
                target_type="case", target_id=cid,
                details={"reason": "agent-side case with no framework "
                                   "counterpart", "by": "platform_admin"},
                ip=audit.client_ip(request))
        except Exception as e:  # noqa: BLE001
            failed.append({"id": cid, "error": str(e)[:200]})
    return {"deleted": deleted, "refused_still_in_framework": refused,
            "failed": failed}
