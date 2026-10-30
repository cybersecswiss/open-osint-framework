"""
Tenant-side administration.

⚠️ **Every state-changing action here is audited.** Without that, this router
would be the only one carrying no audit call, and Keycloak's own admin events are switched off in the
realm export. The chain could therefore prove *who searched for what* and not
*who granted them the ability to* — an account could be created, used and
deleted leaving only the searches of an identity nobody could account for.
That is the one hole an HMAC-chained, append-only log cannot have.

Read-only endpoints are deliberately NOT audited: listing users is not an
act, and logging every page view would bury the acts that matter.

## What this router is

Admin user management — proxy to Keycloak Admin REST API (tenant-aware).

Each admin call is routed to the user's own tenant's Keycloak. After
the per-customer-IdP migration, the framework operator literally has
no admin access to customer Keycloaks — this proxy is the only way.

Scope: an admin sees and manages only users in their *own* tenant
group (which, with per-customer IdPs, equals the realm name in the customer's
own Keycloak).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from app.auth import get_current_user, require_role
from app.services import audit
from app.services.keycloak_admin import IdPNotManaged
from app.config import settings
from app.services import keycloak_admin as kc
from app.services import tenant_registry
from app.services.osint_orchestrator import supported_modules

log = logging.getLogger("osint.admin")

async def _idp_managed_guard(user: dict = Depends(require_role("admin"))) -> dict:
    """Turn "this tenant runs its own IdP" into a 409 with a sentence.

    Sits on the whole user-management group rather than in nine handlers: the
    condition is a property of the tenant, not of the individual call, and
    every one of those calls would otherwise end in the same unhandled 500.
    409 rather than 501 or 403 — nothing is missing and nothing is forbidden;
    the request conflicts with how this tenant is set up.
    """
    try:
        await kc.ensure_manageable(user["tenant"])
    except IdPNotManaged as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return user


router = APIRouter(prefix="/admin", tags=["admin"])


# ── Schemas ─────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    username: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool = True
    roles: list[str] = []
    required_actions: list[str] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    password: str = Field(min_length=8)
    roles: list[str] = []
    temporary_password: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool | None = None
    roles: list[str] | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8)
    temporary: bool = True


# ── Helpers ─────────────────────────────────────────────────────

_HIDDEN_ROLES = {"default-roles-osint", "offline_access", "uma_authorization"}


async def _tenant_group(user: dict) -> dict[str, Any]:
    """Look up the realm group named after the tenant. In customer KCs
    this is the only group; in the framework KC (legacy) it's one of
    several."""
    g = await kc.find_group_by_name(user["tenant"], user["tenant"])
    if not g:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant group '{user['tenant']}' not found in IdP",
        )
    return g


async def _ensure_user_in_tenant(user: dict, user_id: str, tenant_group_id: str) -> dict[str, Any]:
    members = await kc.group_members(user["tenant"], tenant_group_id)
    for m in members:
        if m["id"] == user_id:
            return m
    raise HTTPException(status_code=404, detail="User not found in your tenant")


async def _to_response(user: dict, u: dict[str, Any]) -> UserResponse:
    roles = await kc.user_roles(user["tenant"], u["id"])
    # Filter out the per-realm default-roles-* role too (name varies
    # between realms: default-roles-osint vs default-roles-default).
    visible_roles = [
        r["name"] for r in roles
        if r["name"] not in _HIDDEN_ROLES and not r["name"].startswith("default-roles-")
    ]
    return UserResponse(
        id=u["id"],
        username=u["username"],
        email=u.get("email"),
        first_name=u.get("firstName"),
        last_name=u.get("lastName"),
        enabled=u.get("enabled", True),
        roles=visible_roles,
        required_actions=list(u.get("requiredActions") or []),
    )


# ── Routes ──────────────────────────────────────────────────────

@router.get("/groups", response_model=list[dict])
async def list_tenant_groups(user: dict = Depends(_idp_managed_guard)):
    return await kc.list_groups(user["tenant"])


@router.get("/roles", response_model=list[dict])
async def list_realm_roles(user: dict = Depends(_idp_managed_guard)):
    return await kc.list_realm_roles(user["tenant"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(user: dict = Depends(_idp_managed_guard)):
    group = await _tenant_group(user)
    members = await kc.group_members(user["tenant"], group["id"])
    return [await _to_response(user, m) for m in members]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(payload: UserCreate, request: Request,
                      user: dict = Depends(_idp_managed_guard)):
    group = await _tenant_group(user)
    try:
        new_id = await kc.create_user(user["tenant"], {
            "username": payload.username,
            "email": payload.email,
            "firstName": payload.first_name,
            "lastName": payload.last_name,
            "enabled": True,
            "emailVerified": True,
            "requiredActions": [] if not payload.temporary_password else ["UPDATE_PASSWORD"],
        })
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    await kc.set_password(user["tenant"], new_id, payload.password, temporary=payload.temporary_password)
    await kc.add_user_to_group(user["tenant"], new_id, group["id"])

    if payload.roles:
        all_roles = {r["name"]: r for r in await kc.list_realm_roles(user["tenant"])}
        to_add = [all_roles[name] for name in payload.roles if name in all_roles]
        await kc.add_user_roles(user["tenant"], new_id, to_add)

    created = await kc.get_user(user["tenant"], new_id)
    await audit.log_action(
        user["tenant"], "user.create", user=user,
        target_type="user", target_id=new_id,
        details={"username": payload.username, "roles": payload.roles},
        ip=audit.client_ip(request))
    return await _to_response(user, created)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, user: dict = Depends(_idp_managed_guard)):
    group = await _tenant_group(user)
    u = await _ensure_user_in_tenant(user, user_id, group["id"])
    return await _to_response(user, u)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    group = await _tenant_group(user)
    await _ensure_user_in_tenant(user, user_id, group["id"])

    update_payload: dict[str, Any] = {}
    if payload.email is not None:      update_payload["email"] = payload.email
    if payload.first_name is not None: update_payload["firstName"] = payload.first_name
    if payload.last_name is not None:  update_payload["lastName"] = payload.last_name
    if payload.enabled is not None:    update_payload["enabled"] = payload.enabled
    if update_payload:
        await kc.update_user(user["tenant"], user_id, update_payload)

    if payload.roles is not None:
        all_roles = {r["name"]: r for r in await kc.list_realm_roles(user["tenant"])}
        current = await kc.user_roles(user["tenant"], user_id)
        current_names = {r["name"] for r in current}
        wanted_names = set(payload.roles)
        to_add    = [all_roles[n] for n in (wanted_names - current_names) if n in all_roles]
        to_remove = [r for r in current if r["name"] in (current_names - wanted_names)]
        await kc.add_user_roles(user["tenant"], user_id, to_add)
        await kc.remove_user_roles(user["tenant"], user_id, to_remove)

    refreshed = await kc.get_user(user["tenant"], user_id)
    await audit.log_action(
        user["tenant"], "user.update", user=user,
        target_type="user", target_id=user_id,
        details={"fields": sorted(update_payload.keys()),
                 "roles": payload.roles},
        ip=audit.client_ip(request))
    return await _to_response(user, refreshed)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, request: Request,
                      user: dict = Depends(_idp_managed_guard)):
    group = await _tenant_group(user)
    # Held on to for the audit entry: after the delete the name is gone, and
    # "user.delete <uuid>" alone is not something anyone can read later.
    target = await _ensure_user_in_tenant(user, user_id, group["id"])
    if user["user_id"] == user_id:
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    await kc.delete_user(user["tenant"], user_id)
    await audit.log_action(
        user["tenant"], "user.delete", user=user,
        target_type="user", target_id=user_id,
        details={"username": (target or {}).get("username")},
        ip=audit.client_ip(request))


@router.post("/users/{user_id}/reset-password", status_code=204)
async def reset_password(
    user_id: str,
    payload: PasswordReset,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    group = await _tenant_group(user)
    await _ensure_user_in_tenant(user, user_id, group["id"])
    await kc.set_password(user["tenant"], user_id, payload.password, temporary=payload.temporary)
    # The password itself is never logged — only that it was reset, by whom
    # and whether the user must change it on next sign-in.
    await audit.log_action(
        user["tenant"], "user.password_reset", user=user,
        target_type="user", target_id=user_id,
        details={"temporary": payload.temporary},
        ip=audit.client_ip(request))


@router.post("/users/{user_id}/reset-2fa")
async def reset_2fa(user_id: str, request: Request,
                    user: dict = Depends(_idp_managed_guard)):
    """Wipe the user's TOTP credentials and force them to re-enroll on
    the next login. Returns how many OTP credentials were removed (0 =
    user had no 2FA configured yet)."""
    group = await _tenant_group(user)
    await _ensure_user_in_tenant(user, user_id, group["id"])
    removed = await kc.reset_totp(user["tenant"], user_id)
    await audit.log_action(
        user["tenant"], "user.2fa_reset", user=user,
        target_type="user", target_id=user_id,
        details={"credentials_removed": removed},
        ip=audit.client_ip(request))
    return {"removed": removed}


class RequiredActionsUpdate(BaseModel):
    required_actions: list[str]


@router.put("/users/{user_id}/required-actions")
async def set_required_actions(
    user_id: str,
    payload: RequiredActionsUpdate,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    """Replace the user's pending required actions. Clearing the list is
    how an operator releases a service or test account from a pending
    TOTP enrolment (e.g. for password-grant flows). For regular accounts,
    leave CONFIGURE_TOTP in place for compliance."""
    group = await _tenant_group(user)
    await _ensure_user_in_tenant(user, user_id, group["id"])
    await kc.set_required_actions(user["tenant"], user_id, payload.required_actions)
    await audit.log_action(
        user["tenant"], "user.required_actions", user=user,
        target_type="user", target_id=user_id,
        details={"required_actions": payload.required_actions},
        ip=audit.client_ip(request))
    return {"required_actions": payload.required_actions}


@router.post("/users/{user_id}/disable-2fa-requirement")
async def disable_2fa_requirement(
    user_id: str,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    """Convenience: drop CONFIGURE_TOTP from required-actions but keep
    other pending actions (e.g. UPDATE_PASSWORD) intact. Returns the
    new required-actions list. Existing TOTP credentials, if any, are
    NOT wiped — the user keeps their current authenticator if they
    set one up; we just stop *forcing* setup on next login."""
    group = await _tenant_group(user)
    await _ensure_user_in_tenant(user, user_id, group["id"])
    current = await kc.get_required_actions(user["tenant"], user_id)
    new_actions = [a for a in current if a != "CONFIGURE_TOTP"]
    if new_actions != current:
        await kc.set_required_actions(user["tenant"], user_id, new_actions)
    # A security requirement being switched OFF is exactly the kind of act an
    # audit trail exists for.
    await audit.log_action(
        user["tenant"], "user.2fa_requirement_off", user=user,
        target_type="user", target_id=user_id,
        details={"changed": new_actions != current},
        ip=audit.client_ip(request))
    return {"required_actions": new_actions, "removed_totp_requirement": new_actions != current}


@router.post("/users/{user_id}/enable-2fa-requirement")
async def enable_2fa_requirement(
    user_id: str,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    """Counterpart to disable-2fa-requirement: add CONFIGURE_TOTP to
    required-actions so the user is forced to set up an authenticator
    on their next login. Idempotent — returns current state if it was
    already required."""
    group = await _tenant_group(user)
    await _ensure_user_in_tenant(user, user_id, group["id"])
    current = await kc.get_required_actions(user["tenant"], user_id)
    if "CONFIGURE_TOTP" in current:
        return {"required_actions": current, "added_totp_requirement": False}
    new_actions = current + ["CONFIGURE_TOTP"]
    await kc.set_required_actions(user["tenant"], user_id, new_actions)
    await audit.log_action(
        user["tenant"], "user.2fa_requirement_on", user=user,
        target_type="user", target_id=user_id,
        ip=audit.client_ip(request))
    return {"required_actions": new_actions, "added_totp_requirement": True}


@router.get("/me", response_model=dict)
async def whoami(user: dict = Depends(get_current_user)):
    return user


# ── Tenant settings + license-info ───────────────
# Both routes proxy to the license-server with the operator's internal
# key. The tenant in the path is *always* the caller's own tenant —
# we don't accept a tenant parameter so a tenant-admin can't read or
# mutate another tenant's settings.

class TenantSettings(BaseModel):
    display_name: str | None = None
    logo_b64: str | None = None
    default_alert_email: str | None = None
    session_timeout_minutes: int | None = None
    auto_delete_months: int | None = None
    default_language: Literal["de", "fr", "it", "en"] | None = None
    require_search_purpose: bool | None = None
    default_playbook: str | None = Field(default=None, max_length=50)
    # Printed in CSS `content:` on every report page — so no quotes, no
    # backslashes, no line breaks. Validated here rather than escaped later.
    report_classification: str | None = Field(default=None, max_length=80,
                                              pattern=r'^[^"\\\r\n]*$')
    disabled_modules: list[str] | None = Field(default=None, max_length=50)


async def _license_request(method: str, path: str, **kw) -> httpx.Response:
    url = f"{settings.license_server_url}{path}"
    headers = kw.pop("headers", {})
    headers["X-Internal-Key"] = settings.internal_secret
    async with httpx.AsyncClient(timeout=10) as client:
        return await client.request(method, url, headers=headers, **kw)


# Read by every user of the tenant, not only admins: the header shows the
# display name and logo, and the UI language default applies to everyone.
# Deliberately NOT behind _idp_managed_guard — these settings live in the
# license server and have nothing to do with whether this framework can
# administer the tenant's IdP. Behind that guard a customer running its own
# IdP (the production case) got 409 on its own branding.
@router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    r = await _license_request("GET", f"/api/v1/tenants/{user['tenant']}/settings")
    if r.status_code == 404:
        # Tenant not in license-server yet (e.g. dev "default" before
        # configure-license.sh ran). Return empty defaults so the form
        # still renders.
        return {
            "tenant": user["tenant"],
            "display_name": None,
            "logo_b64": None,
            "default_alert_email": None,
            "session_timeout_minutes": 30,
            "auto_delete_months": None,
            "default_language": None,
            "require_search_purpose": False,
            "default_playbook": None,
            "report_classification": None,
            "disabled_modules": [],
        }
    r.raise_for_status()
    out = r.json()
    # What the licence allows, so the admin screen can offer exactly those
    # modules to switch off (and not suggest a module that is not licensed).
    licensed = await tenant_registry.get_enabled_modules(user["tenant"])
    out["licensed_modules"] = sorted(licensed if licensed is not None else supported_modules())
    return out


@router.put("/settings")
async def update_settings(
    payload: TenantSettings,
    request: Request,
    user: dict = Depends(require_role("admin")),
):
    data = payload.model_dump(exclude_unset=True)
    if data.get("disabled_modules") is not None:
        known = set(supported_modules())
        data["disabled_modules"] = sorted({m for m in data["disabled_modules"] if m in known})
    if data.get("default_playbook"):
        from app.services.playbooks import PLAYBOOKS
        if data["default_playbook"] not in {p["key"] for p in PLAYBOOKS}:
            raise HTTPException(status_code=422, detail="unknown playbook")
    if "report_classification" in data and data["report_classification"] is not None:
        data["report_classification"] = data["report_classification"].strip() or None
    r = await _license_request(
        "PUT", f"/api/v1/tenants/{user['tenant']}/settings",
        json=data,
    )
    if r.status_code == 413:
        raise HTTPException(status_code=413, detail=r.json().get("detail", "Logo too large"))
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Tenant not registered with license server")
    r.raise_for_status()
    result = r.json()
    tenant_registry.invalidate_tenant_settings(user["tenant"])
    await audit.log_action(
        user["tenant"], "tenant.settings_change", user=user,
        target_type="tenant", target_id=user["tenant"],
        # Field names only. A logo is a blob and a retention period is a
        # policy — the names say what was touched without copying values
        # into a log that is append-only by design.
        details={"fields": sorted(data.keys())},
        ip=audit.client_ip(request))

    # When session_timeout_minutes changes, also push
    # it to the tenant's Keycloak realm so the OIDC idle/max lifespans
    # actually take effect. Best-effort: log on failure but don't fail
    # the whole settings save (the value is persisted in license-server
    # either way and a later retry can re-sync).
    if "session_timeout_minutes" in data and data["session_timeout_minutes"]:
        try:
            await kc.update_realm_session_timeout(user["tenant"], data["session_timeout_minutes"])
            result["realm_session_timeout_synced"] = True
        except IdPNotManaged:
            # The tenant runs its own IdP; its session policy is set there.
            # Not a failure of this save, so no warning in the UI.
            result["realm_session_timeout_synced"] = None
        except Exception as e:
            log.warning("realm session-timeout sync failed for tenant=%s: %s", user["tenant"], e)
            result["realm_session_timeout_synced"] = False
    return result


# ── Alert delivery settings ────────────────────────
#
# The customer's own admin configures how alerts reach them. Two things
# this deliberately does NOT do:
#
#   * It never returns a stored password or webhook secret. The licence
#     server reports them as `smtp_password_set: true`, and the form shows
#     an empty field with a "stored" hint. A settings screen that echoes a
#     password back puts it into browser caches and screenshots.
#   * It never reports a save as a success for delivery. Saving proves the
#     form validated; only the test button proves a mail arrives.


class NotificationSettingsPayload(BaseModel):
    notify_email_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str | None = None
    smtp_username: str | None = None
    # Omit to keep the stored one, "" to clear, a value to replace.
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_verify_tls: bool | None = None
    notify_webhook_enabled: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    notify_events: list[str] | None = None


class NotificationTestPayload(BaseModel):
    channel: str = Field(pattern="^(email|webhook)$")
    # Try a different address without saving it first — the common case
    # when someone is debugging their relay.
    recipient: str | None = None


@router.get("/notification-settings")
async def get_notification_settings(user: dict = Depends(_idp_managed_guard)):
    r = await _license_request("GET", f"/api/v1/tenants/{user['tenant']}/notification-settings")
    if r.status_code == 404:
        # Same shape as an unconfigured tenant so the form renders rather
        # than erroring — matches how /settings handles the dev tenant.
        return {
            "tenant": user["tenant"],
            "notify_email_enabled": False, "smtp_host": None, "smtp_port": 587,
            "smtp_security": "starttls", "smtp_username": None,
            "smtp_password_set": False, "smtp_from": None, "smtp_verify_tls": True,
            "notify_webhook_enabled": False, "webhook_url": None,
            "webhook_secret_set": False, "notify_events": [],
            "notify_last_ok_at": None, "notify_last_attempt_at": None,
            "notify_last_error": None, "default_alert_email": None,
            "unregistered": True,
        }
    r.raise_for_status()
    return r.json()


@router.put("/notification-settings")
async def update_notification_settings(
    payload: NotificationSettingsPayload,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    data = payload.model_dump(exclude_unset=True)
    r = await _license_request(
        "PUT", f"/api/v1/tenants/{user['tenant']}/notification-settings", json=data)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Tenant not registered with license server")
    if r.status_code == 422:
        raise HTTPException(status_code=422, detail=r.json().get("detail", "Invalid settings"))
    if r.status_code == 400:
        raise HTTPException(status_code=400, detail=r.json().get("detail", "Invalid settings"))
    r.raise_for_status()

    from app.services import notify
    # The dispatcher caches the transport for a minute. Without this, a
    # corrected password would not be used by the test button the user
    # clicks two seconds later — and they would conclude it is still wrong.
    notify.invalidate(user["tenant"])

    await audit.log_action(
        user["tenant"], "tenant.notification_settings_change", user=user,
        target_type="tenant", target_id=user["tenant"],
        # Field names only — one of these fields is a password.
        details={"fields": sorted(data.keys())},
        ip=audit.client_ip(request))
    return r.json()


@router.post("/notification-settings/test")
async def test_notification(
    payload: NotificationTestPayload,
    request: Request,
    user: dict = Depends(_idp_managed_guard),
):
    """Send a test message and report exactly what happened.

    Always HTTP 200, including on a delivery failure: a non-2xx here would
    be indistinguishable in the client from "you are not allowed to do
    this", and the failure detail is the entire value of the button.
    """
    from app.services import notify

    result = await notify.send_test(user["tenant"], payload.channel, payload.recipient)
    await audit.log_action(
        user["tenant"], "tenant.notification_test", user=user,
        target_type="tenant", target_id=user["tenant"],
        details={"channel": payload.channel, "ok": result.ok},
        ip=audit.client_ip(request))
    return result.as_dict()


@router.get("/selftest")
async def selftest(user: dict = Depends(require_role("admin"))):
    """Is this authority's installation working? Health and configuration
    only — see services/selftest.py."""
    from app.services import selftest as st
    checks = await st.run(user["tenant"])
    worst = "fail" if any(c["status"] == "fail" for c in checks) else (
        "warn" if any(c["status"] == "warn" for c in checks) else "ok")
    return {"overall": worst, "checks": checks,
            "checked_at": __import__("datetime").datetime.utcnow().isoformat()}


def update_verdict(installed: str | None, latest: str | None, missing: list[str]) -> str:
    """Both versions known → compare them. An agent too old to report its
    version is judged by what it can do."""
    if installed and latest:
        return "outdated" if installed != latest else "current"
    return "outdated" if missing else "current"


@router.get("/update-status")
async def update_status(user: dict = Depends(require_role("admin"))):
    """Is a newer customer-agent release published than the one running?

    Installed: what the agent reports about itself (`/health` version;
    older agents report none, then the capability list decides).
    Latest: the manifest the operator published (`/agent/version.json`), the
    same file `update.sh` reads. The answer carries the command to run, so
    the admin does not have to look it up.
    """
    import json as _json
    from pathlib import Path
    from app.services import selftest as st
    manifest: dict = {}
    try:
        manifest = _json.loads(Path("/srv/agent-manifest/version.json").read_text())
    except Exception:  # noqa: BLE001
        pass
    latest = manifest.get("version") or None
    installed, caps = None, set()
    try:
        agent_url = await tenant_registry.get_agent_url(user["tenant"])
        async with httpx.AsyncClient(timeout=8, verify=settings.tls_verify_idp) as c:
            h = (await c.get(f"{agent_url.rstrip('/')}/health")).json()
        installed, caps = h.get("version"), set(h.get("capabilities") or [])
    except Exception:  # noqa: BLE001
        return {"state": "unknown", "latest": latest}
    missing = sorted(st.EXPECTED_CAPABILITIES - caps)
    return {
        "state": update_verdict(installed, latest, missing),
        "installed": installed, "latest": latest,
        "released_at": manifest.get("released_at"),
        "changes": manifest.get("changes") or {},
        "missing_capabilities": missing,
        "command": "cd /opt/oof-agent && sudo ./update.sh",
    }


# Not behind _idp_managed_guard: the licence is the license server's, not the
# IdP's — a customer with its own IdP (production) got 409 on its own licence.
@router.get("/license")
async def get_license_info(user: dict = Depends(require_role("admin"))):
    r = await _license_request("GET", f"/api/v1/tenants/{user['tenant']}/license-info")
    if r.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail="No license registered for this tenant. Contact the framework operator.",
        )
    r.raise_for_status()
    return r.json()
