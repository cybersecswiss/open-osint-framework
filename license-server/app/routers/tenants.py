import hmac
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt, is_set
from app.models import License, get_db, settings

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


def verify_internal(x_internal_key: str = Header(..., alias="X-Internal-Key")):
    if not hmac.compare_digest(x_internal_key, settings.internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _require_secure_url(url: str, field: str) -> str:
    """Reject plaintext endpoints that would carry data across the internet.

    Case data and the framework key travel to the agent URL; investigator
    passwords travel to the IdP URL. `http://` is only tolerated for
    internal names (docker service names, *.local, RFC1918 literals), which
    is what dev and on-prem-internal deployments use — never for a public
    hostname. Set ALLOW_INSECURE_TENANT_URLS=true to override in a lab.
    """
    import ipaddress
    import os
    from urllib.parse import urlparse

    value = (url or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field} must not be empty")
    parsed = urlparse(value)
    if parsed.scheme == "https":
        return value
    if parsed.scheme != "http":
        raise HTTPException(status_code=400,
                            detail=f"{field} must be an http(s) URL")
    if os.environ.get("ALLOW_INSECURE_TENANT_URLS", "").lower() in ("1", "true", "yes"):
        return value

    host = (parsed.hostname or "").lower()
    internal = host in ("localhost", "127.0.0.1") or host.endswith(".local") or "." not in host
    if not internal:
        try:
            internal = ipaddress.ip_address(host).is_private
        except ValueError:
            internal = False
    if internal:
        return value
    raise HTTPException(
        status_code=400,
        detail=(f"{field} must use https:// — a public http endpoint would carry "
                f"investigation data and credentials in the clear. The agent "
                f"installer provisions a certificate automatically; register the "
                f"https URL it prints."),
    )


class AgentUrlUpdate(BaseModel):
    agent_url: str


class IdpUrlUpdate(BaseModel):
    idp_url: str
    backend_secret: str | None = None


class EmailDomainsUpdate(BaseModel):
    email_domains: list[str]


class EnabledModulesUpdate(BaseModel):
    # null or [] => reset to "all modules enabled" (stored as NULL).
    enabled_modules: list[str] | None = None


class AiEnabledUpdate(BaseModel):
    ai_enabled: bool


class LicenseRenew(BaseModel):
    # Extend validity by this many days (from today or the current
    # expiry, whichever is later — so renewing early doesn't lose time).
    valid_days: int = 365


class ActiveUpdate(BaseModel):
    is_active: bool


class Contact(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    role: str | None = None


class ContactsUpdate(BaseModel):
    contacts: list[Contact]


def _license_summary(lic: License) -> dict:
    now = datetime.utcnow()
    return {
        "tenant": lic.tenant,
        "is_active": lic.is_active,
        "valid_until": lic.valid_until.isoformat(),
        "days_remaining": (lic.valid_until - now).days,
        "is_expired": now > lic.valid_until,
        "contact_email": lic.contact_email,
        "display_name": lic.display_name,
        "agent_url": lic.agent_url,
        "idp_url": lic.idp_url,
        "email_domains": lic.email_domains or [],
        "enabled_modules": lic.enabled_modules,
        "ai_enabled": bool(lic.ai_enabled),
        "contacts": lic.contacts or [],
        "created_at": lic.created_at.isoformat(),
    }


class TenantSettingsUpdate(BaseModel):
    """Branding + display settings the tenant-admin
    edits via the framework's /admin/settings page. All fields
    optional — omitted ones stay at their current value."""
    display_name: str | None = None
    logo_b64: str | None = None
    default_alert_email: str | None = None
    session_timeout_minutes: int | None = None
    auto_delete_months: int | None = None
    default_language: Literal["de", "fr", "it", "en"] | None = None
    require_search_purpose: bool | None = None
    default_playbook: str | None = Field(default=None, max_length=50)
    report_classification: str | None = Field(default=None, max_length=80)
    disabled_modules: list[str] | None = Field(default=None, max_length=50)


# Operator: list every tenant/license (summary). Declared before the
# /{tenant} routes so it isn't shadowed. Used by the platform admin panel.
@router.get("")
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    rows = (await db.execute(select(License).order_by(License.tenant))).scalars().all()
    return [_license_summary(l) for l in rows]


# Static path declared first so 'expiring' isn't matched as a tenant.
@router.get("/expiring")
async def get_expiring(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    cutoff = datetime.utcnow() + timedelta(days=days)
    result = await db.execute(
        select(License).where(License.valid_until <= cutoff, License.is_active == True)  # noqa: E712
    )
    return [
        {
            "tenant": l.tenant,
            "email": l.contact_email,
            "valid_until": l.valid_until.isoformat(),
        }
        for l in result.scalars().all()
    ]


@router.get("/{tenant}/agent-url")
async def get_agent_url(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not lic.agent_url:
        raise HTTPException(status_code=404, detail="Agent URL not configured for this tenant")
    return {"agent_url": lic.agent_url}


@router.get("/{tenant}/agent-key")
async def get_agent_key(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    """The per-tenant key the framework must present to THAT tenant's data
    agent (`X-Framework-Key`).

    This is the same value `install.sh` bakes into the customer's agent as
    `FRAMEWORK_KEY` (it fetches it via /license/agent-key with the license
    key). Sending the framework's own global API_SECRET_KEY instead would
    only match where both had been set to the same value by hand — every
    separately installed data server would answer 401 to every push, read
    and delete.

    Operator-internal (X-Internal-Key). An inactive or expired license
    stops handing the key out, mirroring /license/agent-key.
    """
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not lic.is_active or lic.valid_until < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Licence inactive or expired")
    return {"agent_key": lic.agent_api_key}


@router.put("/{tenant}/agent-url")
async def set_agent_url(
    tenant: str,
    payload: AgentUrlUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    lic.agent_url = _require_secure_url(payload.agent_url, 'agent_url')
    await db.commit()
    return {"ok": True}


# ── IdP URL ─────────────────────────────────────────────────────

@router.get("/{tenant}/idp-url")
async def get_idp_url(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"idp_url": lic.idp_url}


@router.put("/{tenant}/idp-url")
async def set_idp_url(
    tenant: str,
    payload: IdpUrlUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    lic.idp_url = _require_secure_url(payload.idp_url, 'idp_url')
    if payload.backend_secret is not None:
        # Encrypted at rest. Callers keep sending
        # plaintext — the encoding is this service's business, not theirs.
        lic.idp_backend_secret = encrypt(payload.backend_secret)
    await db.commit()
    return {"ok": True}


# Internal-only: returns the IdP credentials the framework backend needs
# to call the customer's Keycloak Admin API. Never exposed publicly —
# it's how the framework's user-management proxy fetches tokens against
# the customer-side IdP.
@router.get("/{tenant}/idp-credentials")
async def get_idp_credentials(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "idp_url": lic.idp_url,
        # Legacy plaintext rows decrypt to themselves, so this keeps
        # working for tenants registered before encryption at rest.
        "backend_secret": decrypt(lic.idp_backend_secret),
    }


# ── Email domains ───────────────────────────────────────────────

@router.get("/{tenant}/email-domains")
async def get_email_domains(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"email_domains": lic.email_domains or []}


@router.put("/{tenant}/email-domains")
async def set_email_domains(
    tenant: str,
    payload: EmailDomainsUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Normalize: lowercase + dedupe + strip
    domains = sorted({d.strip().lower() for d in payload.email_domains if d.strip()})
    lic.email_domains = domains
    await db.commit()
    return {"ok": True, "email_domains": domains}


# ── Module pack / module licensing ──────────────────────────────
# Operator-controlled allow-list of OSINT modules per tenant. NULL/empty
# = all modules enabled (default). The framework backend reads this to
# filter /search/modules and to reject un-licensed modules in /search.

@router.get("/{tenant}/enabled-modules")
async def get_enabled_modules(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # None => "all modules" (the backend degrades open on None/empty).
    return {"tenant": lic.tenant, "enabled_modules": lic.enabled_modules}


@router.put("/{tenant}/enabled-modules")
async def set_enabled_modules(
    tenant: str,
    payload: EnabledModulesUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    mods = payload.enabled_modules or []
    # Normalize: lowercase + strip + dedupe + sort. Empty list => NULL,
    # i.e. "all modules enabled".
    normalized = sorted({m.strip().lower() for m in mods if m.strip()})
    lic.enabled_modules = normalized or None
    await db.commit()
    return {"ok": True, "enabled_modules": lic.enabled_modules}


# ── AI function (licensable add-on) — opt-in, default OFF ────────
@router.get("/{tenant}/ai-enabled")
async def get_ai_enabled(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"tenant": lic.tenant, "ai_enabled": bool(lic.ai_enabled)}


@router.put("/{tenant}/ai-enabled")
async def set_ai_enabled(
    tenant: str,
    payload: AiEnabledUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    lic.ai_enabled = payload.ai_enabled
    await db.commit()
    return {"ok": True, "ai_enabled": lic.ai_enabled}


# ── Contact persons per tenant ──────────────────────────────────

@router.get("/{tenant}/contacts")
async def get_contacts(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"tenant": lic.tenant, "contacts": lic.contacts or []}


@router.put("/{tenant}/contacts")
async def set_contacts(
    tenant: str,
    payload: ContactsUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    lic.contacts = [c.model_dump() for c in payload.contacts]
    await db.commit()
    return {"ok": True, "contacts": lic.contacts}


# ── Lifecycle: renew / suspend / reactivate / delete ────────────

@router.post("/{tenant}/renew")
async def renew_license(
    tenant: str,
    payload: LicenseRenew,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    base = max(lic.valid_until, datetime.utcnow())
    lic.valid_until = base + timedelta(days=payload.valid_days)
    await db.commit()
    return {"ok": True, "valid_until": lic.valid_until.isoformat()}


@router.put("/{tenant}/active")
async def set_active(
    tenant: str,
    payload: ActiveUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    lic.is_active = payload.is_active
    await db.commit()
    return {"ok": True, "is_active": lic.is_active}


@router.delete("/{tenant}")
async def delete_tenant(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(lic)
    await db.commit()
    return {"ok": True, "deleted": tenant}


# Internal — list of tenants that have auto_delete_months set. Used by
# the framework backend's auto-purge scheduler so it knows which tenants
# to evaluate. NULL = never delete, so we filter those out.
@router.get("/with-auto-delete")
async def list_tenants_with_auto_delete(
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    rows = (await db.execute(
        select(License).where(
            License.auto_delete_months.is_not(None),
            License.is_active == True,  # noqa: E712
        )
    )).scalars().all()
    return [
        {"tenant": l.tenant, "auto_delete_months": l.auto_delete_months}
        for l in rows
    ]


# Public endpoint — resolves an email address to the tenant that owns
# the email's domain. Used by the framework's pre-auth email-entry
# page so it knows which Customer-IdP to redirect the user to.
# No auth: this is the entry point for unauthenticated users.
@router.get("/resolve-by-email")
async def resolve_by_email(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    if "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="Invalid email")
    domain = email.rsplit("@", 1)[-1].strip().lower()
    if not domain:
        raise HTTPException(status_code=400, detail="Invalid email")
    # ARRAY search: find the row whose email_domains list contains the domain.
    from sqlalchemy import any_  # local import keeps the file's import block tidy
    lic = await db.scalar(
        select(License).where(
            domain == any_(License.email_domains),
            License.is_active == True,  # noqa: E712
        )
    )
    if not lic:
        raise HTTPException(status_code=404, detail="No tenant matches this email domain")
    return {"tenant": lic.tenant}


# ── Tenant settings ─────────────────────────────────────────────

@router.get("/{tenant}/settings")
async def get_tenant_settings(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant": lic.tenant,
        "display_name": lic.display_name,
        "logo_b64": lic.logo_b64,
        "default_alert_email": lic.default_alert_email,
        "session_timeout_minutes": lic.session_timeout_minutes,
        "auto_delete_months": lic.auto_delete_months,
        "default_language": lic.default_language,
        "require_search_purpose": bool(lic.require_search_purpose),
        "default_playbook": lic.default_playbook,
        "report_classification": lic.report_classification,
        "disabled_modules": lic.disabled_modules or [],
    }


# Soft cap — keeps the DB row and JWT-bearing requests from blowing up
# on someone uploading a 5 MB photo. ~200 KB base64 is plenty for an
# org logo (a 100 KB PNG ≈ 137 KB base64).
_MAX_LOGO_B64_BYTES = 220_000


@router.put("/{tenant}/settings")
async def set_tenant_settings(
    tenant: str,
    payload: TenantSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    data = payload.model_dump(exclude_unset=True)
    if "logo_b64" in data and data["logo_b64"]:
        if len(data["logo_b64"]) > _MAX_LOGO_B64_BYTES:
            raise HTTPException(status_code=413, detail=f"Logo too large (max {_MAX_LOGO_B64_BYTES // 1024} KB base64)")
    for k, v in data.items():
        setattr(lic, k, v)
    await db.commit()
    return {"ok": True}


# ── Alert delivery settings ─────────────────────────────────────
#
# Three endpoints, and the split between them is the whole point:
#
#   GET  /notification-settings   what the customer's admin may SEE.
#                                 Secrets are reported as booleans.
#   PUT  /notification-settings   what the customer's admin may SET.
#   GET  /notification-config     the decrypted transport, for the
#                                 dispatcher only.
#
# Without the third one the dispatcher would have to read the raw column
# and know about Fernet; without the first two the browser would end up
# holding an SMTP password it has no reason to see. A settings screen that
# round-trips a password back to the client is how passwords end up in
# browser caches, screenshots and support tickets.


class NotificationSettingsUpdate(BaseModel):
    """Every field optional — an omitted field keeps its stored value.

    `smtp_password` and `webhook_secret` follow the convention the API-key
    panel already uses: omit to keep, empty string to clear, a value to
    replace. Without the three-way distinction there is no way to say
    "leave the password alone" from a form that never received it.
    """
    notify_email_enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_security: str | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_verify_tls: bool | None = None

    notify_webhook_enabled: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None

    notify_events: list[str] | None = None


_SMTP_SECURITY = {"starttls", "ssl", "none"}
_SECRET_FIELDS = {"smtp_password", "webhook_secret"}


def _notification_view(lic: License) -> dict:
    """What the tenant admin sees. Never contains a secret."""
    return {
        "tenant": lic.tenant,
        "notify_email_enabled": bool(lic.notify_email_enabled),
        "smtp_host": lic.smtp_host,
        "smtp_port": lic.smtp_port or 587,
        "smtp_security": lic.smtp_security or "starttls",
        "smtp_username": lic.smtp_username,
        "smtp_password_set": is_set(lic.smtp_password),
        "smtp_from": lic.smtp_from,
        "smtp_verify_tls": lic.smtp_verify_tls if lic.smtp_verify_tls is not None else True,
        "notify_webhook_enabled": bool(lic.notify_webhook_enabled),
        "webhook_url": lic.webhook_url,
        "webhook_secret_set": is_set(lic.webhook_secret),
        "notify_events": lic.notify_events or [],
        # Delivery health — the honest answer to "does this work?", which
        # a saved form cannot give.
        "notify_last_ok_at": lic.notify_last_ok_at.isoformat() if lic.notify_last_ok_at else None,
        "notify_last_attempt_at": (
            lic.notify_last_attempt_at.isoformat() if lic.notify_last_attempt_at else None
        ),
        "notify_last_error": lic.notify_last_error,
        # Default recipient shown next to the transport, because "mail is
        # configured but nobody is addressed" is the failure people
        # actually hit.
        "default_alert_email": lic.default_alert_email,
    }


@router.get("/{tenant}/notification-settings")
async def get_notification_settings(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _notification_view(lic)


@router.put("/{tenant}/notification-settings")
async def set_notification_settings(
    tenant: str,
    payload: NotificationSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")

    data = payload.model_dump(exclude_unset=True)

    if "smtp_security" in data and data["smtp_security"] not in _SMTP_SECURITY:
        raise HTTPException(
            status_code=422,
            detail=f"smtp_security must be one of {sorted(_SMTP_SECURITY)}",
        )
    if "smtp_port" in data and data["smtp_port"] is not None:
        if not (1 <= int(data["smtp_port"]) <= 65535):
            raise HTTPException(status_code=422, detail="smtp_port out of range")
    if data.get("webhook_url"):
        # Same rule as agent_url/idp_url: a webhook carrying a case
        # identifier and a changed value must not travel in the clear.
        # An internal hostname stays allowed, exactly as it does there,
        # so an on-premise receiver on the organisation's own network works.
        data["webhook_url"] = _require_secure_url(data["webhook_url"], "webhook_url")

    # Refuse to arm a transport that cannot possibly deliver. The
    # alternative — save it and fail silently at 03:00 — is the behaviour
    # this whole feature exists to remove.
    prospective = {**_notification_view(lic), **{k: v for k, v in data.items() if k not in _SECRET_FIELDS}}
    if prospective.get("notify_email_enabled") and not (prospective.get("smtp_host") or "").strip():
        raise HTTPException(status_code=422, detail="Email alerts need an SMTP host.")
    if prospective.get("notify_webhook_enabled") and not (prospective.get("webhook_url") or "").strip():
        raise HTTPException(status_code=422, detail="Webhook alerts need a webhook URL.")

    for k, v in data.items():
        if k in _SECRET_FIELDS:
            # "" clears, a value replaces, omission never reaches here.
            setattr(lic, k, "" if v == "" else encrypt(v))
        else:
            setattr(lic, k, v)

    await db.commit()
    await db.refresh(lic)
    return _notification_view(lic)


@router.get("/{tenant}/notification-config")
async def get_notification_config(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    """Decrypted transport for the framework's dispatcher. Internal-key
    only, like /idp-credentials, and never proxied to a browser."""
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant": lic.tenant,
        "notify_email_enabled": bool(lic.notify_email_enabled),
        "smtp_host": lic.smtp_host,
        "smtp_port": lic.smtp_port or 587,
        "smtp_security": lic.smtp_security or "starttls",
        "smtp_username": lic.smtp_username,
        "smtp_password": decrypt(lic.smtp_password),
        "smtp_from": lic.smtp_from,
        "smtp_verify_tls": lic.smtp_verify_tls if lic.smtp_verify_tls is not None else True,
        "notify_webhook_enabled": bool(lic.notify_webhook_enabled),
        "webhook_url": lic.webhook_url,
        "webhook_secret": decrypt(lic.webhook_secret),
        "notify_events": lic.notify_events or [],
        "default_alert_email": lic.default_alert_email,
    }


class DeliveryReport(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/{tenant}/notification-result")
async def record_notification_result(
    tenant: str,
    payload: DeliveryReport,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    """The dispatcher reports back what happened. Kept here rather than in
    the framework DB so the settings screen can show delivery health from
    the same row it reads everything else from — one round-trip, and no
    way for the two to disagree."""
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    now = datetime.utcnow()
    lic.notify_last_attempt_at = now
    if payload.ok:
        lic.notify_last_ok_at = now
        lic.notify_last_error = None
    else:
        # Truncated: an SMTP server can answer with a paragraph, and this
        # column is read by a settings screen, not by a log aggregator.
        lic.notify_last_error = (payload.error or "unknown error")[:500]
    await db.commit()
    return {"ok": True}


# Read-only view for the tenant-admin's License tab. Returns license
# status + masked keys so the operator-issued secrets aren't echoed
# in full to anyone with admin role on the tenant side.
@router.get("/{tenant}/license-info")
async def get_license_info(
    tenant: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant))
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")

    def mask(s: str | None) -> str | None:
        if not s or len(s) < 8:
            return s
        return f"{s[:4]}…{s[-4:]}"

    now = datetime.utcnow()
    days_left = (lic.valid_until - now).days
    return {
        "tenant": lic.tenant,
        "is_active": lic.is_active,
        "valid_until": lic.valid_until.isoformat(),
        "days_remaining": days_left,
        "is_expired": now > lic.valid_until,
        "license_key_masked": mask(lic.license_key),
        "agent_api_key_masked": mask(lic.agent_api_key),
        "agent_url": lic.agent_url,
        "idp_url": lic.idp_url,
        "email_domains": lic.email_domains or [],
        # None => all modules enabled (frontend renders this as "all").
        "enabled_modules": lic.enabled_modules,
        "ai_enabled": bool(lic.ai_enabled),
        "contacts": lic.contacts or [],
        "contact_email": lic.contact_email,
        "created_at": lic.created_at.isoformat(),
    }


# Public endpoint (no internal-key) — frontend bootstraps OIDC config from this.
# Returns only non-secret values: the IdP base URL and which realm to use.
# Frontend caches it for the session.
@router.get("/{tenant}/oidc-config")
async def public_oidc_config(
    tenant: str,
    db: AsyncSession = Depends(get_db),
):
    lic = await db.scalar(select(License).where(License.tenant == tenant, License.is_active == True))  # noqa: E712
    if not lic:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not lic.idp_url:
        # Legacy / dev tenant — frontend should fall back to its build-time
        # VITE_KEYCLOAK_URL (the framework-side shared Keycloak).
        return {"idp_url": None, "tenant": tenant}
    return {"idp_url": lic.idp_url, "tenant": tenant}
