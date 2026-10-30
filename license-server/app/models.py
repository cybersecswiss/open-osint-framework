"""
License server models + DB session + Settings.

The plan groups all of these into a single file. We follow that layout
so the rest of the plan's import paths (`from app.models import ...`)
work without modification.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import ARRAY, JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    # Shared secret for internal service-to-service calls (backend →
    # license-server, n8n → license-server). Split out of `secret_key` so
    # the platform's master secret is no longer handed to every component
    # that merely needs to talk to this service. Empty → fall back to
    # `secret_key`, so an existing deployment keeps working unchanged.
    internal_key: str = ""

    # Key-encryption key for customer secrets stored in this DB
    # (idp_backend_secret, smtp_password, webhook_secret). Empty → derive
    # from `secret_key`, so an existing deployment needs no new secret.
    # See app/crypto.py for the rotation consequence.
    license_kek: str = ""

    @property
    def internal_secret(self) -> str:
        return self.internal_key or self.secret_key

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as s:
        yield s


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    license_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    agent_api_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    agent_url: Mapped[str | None] = mapped_column(String(500))
    # Per-tenant Identity Provider URL. When set, the framework
    # backend validates JWTs against THIS Keycloak's JWKS, not against the
    # framework-side shared Keycloak. Format:
    #   https://idp.tenant-a.example/auth/realms/tenant-a
    # NULL = legacy: tenant uses the framework-side shared Keycloak realm
    # (only acceptable for an all-in-one/test tenant; rejected for new tenants).
    idp_url: Mapped[str | None] = mapped_column(String(500))
    # Client secret for the `osint-backend` confidential client
    # in the customer-side Keycloak realm. Framework backend uses this
    # to fetch admin-API tokens against the customer's IdP. Generated
    # by data-agent install.sh and pushed here.
    # Text, not String(128): Fernet ciphertext of a 64-char secret is
    # longer than the plaintext secret (encrypted at rest, app/crypto.py).
    idp_backend_secret: Mapped[str | None] = mapped_column(Text)
    # Email domains owned by this tenant. The framework
    # router resolves a typed-in email address to a tenant by matching
    # the domain part against this list. n:1 (one tenant can own many
    # domains, e.g. ['tenant-a.example', 'tenant-a-mail.example']). Empty/NULL means tenant
    # users cannot reach the framework via the email-routing entry page.
    email_domains: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")
    # Per-tenant module pack (module licensing). NULL / empty = ALL
    # modules enabled — the default, so existing tenants are unchanged
    # and newly-added modules become available automatically. A non-empty
    # list restricts the tenant to exactly those module names (must match
    # modules/<name> / the backend MODULE_REGISTRY). Operator-controlled
    # only (X-Internal-Key); the tenant-admin sees it read-only in the
    # License tab. Enforced by the framework backend's /search/modules +
    # /search. Kept here (not in Keycloak) so it rides with the license.
    enabled_modules: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255))
    # Contact persons per tenant (product-owner managed).
    # List of {name, email, phone, role}. NULL/empty = only contact_email.
    contacts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Tenant-side branding + display settings. The
    # tenant-admin reads/edits these via /admin/settings; they show up
    # in headers and PDF reports. Stored here (not in Keycloak) so the
    # operator can also see what each customer chose for support.
    display_name: Mapped[str | None] = mapped_column(String(255))
    # Logo as data-URI (image/png;base64,...). Capped at ~200 KB by the
    # backend route to keep DB and JWT-bearing requests sane. Bigger
    # logos should go behind a CDN — out of scope here.
    logo_b64: Mapped[str | None] = mapped_column(Text)
    default_alert_email: Mapped[str | None] = mapped_column(String(255))
    # Session timeout the tenant-admin would *like* to enforce. Currently
    # informational only — actual Keycloak realm session-timeout sync is
    # a follow-up (would require admin-API call into the customer KC).
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    # Auto-delete frist for closed cases (months). NULL = never delete.
    # Enforced by the framework's scheduled auto-delete routine.
    auto_delete_months: Mapped[int | None] = mapped_column(Integer)
    # UI language a user of this tenant gets until they pick one themselves
    # (de/fr/it/en). NULL = follow the browser.
    default_language: Mapped[str | None] = mapped_column(String(5))
    # A search must carry a stated purpose (file number, order, reason).
    # The purpose itself is never stored here — it goes to the customer's
    # own activity log.
    require_search_purpose: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Tenant-admin defaults. `disabled_modules` can only NARROW
    # the licence (enabled_modules above is the operator's commercial
    # decision); `default_playbook` preselects a playbook in the search form;
    # `report_classification` is printed on every report page.
    default_playbook: Mapped[str | None] = mapped_column(String(50))
    report_classification: Mapped[str | None] = mapped_column(String(80))
    disabled_modules: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    # Licensable "AI function" add-on (KI-Verknüpfung). Opt-in, default
    # OFF — unlike enabled_modules (default-all), this is a paid extra the
    # operator switches on per customer. Gates the case-view AI-link button
    # + the /cases/{id}/ai-link route.
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # ── Alert delivery ──────────────────────────────────────────────
    # The customer configures HOW an alert reaches them; the individual
    # MonitoringConfig keeps saying WHO gets it (alert_email /
    # alert_webhook), falling back to these defaults when it says nothing.
    #
    # The split matters: mail server and credentials are one decision the
    # organisation's IT makes once, while "who watches this entity" is a
    # decision an investigator makes per case. Putting the SMTP password
    # on every monitor would mean re-entering it per case and revoking it
    # in n places.
    #
    # Sovereignty note: these rows live operator-side, like the monitoring
    # configs and alerts they serve. That is consistent with today's
    # topology, not a new leak — but it is part of the same open
    # architecture question (should alerts and monitoring configs move into
    # the sovereign store?), and it now has one more field in it.
    # The password is encrypted at rest (app/crypto.py); the operator can
    # see that a server is configured, not what the password is.
    notify_email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    smtp_host: Mapped[str | None] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, server_default="587")
    # starttls (587, the default and what nearly every server wants) |
    # ssl (465, implicit TLS) | none (25, only sane for an internal relay).
    smtp_security: Mapped[str] = mapped_column(String(20), default="starttls", server_default="starttls")
    smtp_username: Mapped[str | None] = mapped_column(String(255))
    # Fernet ciphertext — never returned by any read endpoint.
    smtp_password: Mapped[str | None] = mapped_column(Text)
    smtp_from: Mapped[str | None] = mapped_column(String(255))
    # Off only for an internal relay with a self-signed certificate. The
    # UI says so, because a silently unverified TLS session to a mail
    # server carrying case-related subject lines is worse than no TLS:
    # it looks encrypted in the settings screen.
    smtp_verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    notify_webhook_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    # Shared secret for the X-OSINT-Signature HMAC. Optional but strongly
    # recommended: without it the receiver cannot tell our POST from
    # anyone else's. Fernet ciphertext.
    webhook_secret: Mapped[str | None] = mapped_column(Text)

    # Which change types raise a notification at all. Empty = all of them.
    # Stored as names matching Alert.change_type.
    notify_events: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    # Delivery health, written by the dispatcher. The settings screen shows
    # this instead of claiming success from a saved form: a form that saves
    # is not a mail that arrives.
    notify_last_ok_at: Mapped[datetime | None] = mapped_column(DateTime)
    notify_last_error: Mapped[str | None] = mapped_column(Text)
    notify_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)


class SupportTicket(Base):
    """Support ticket/thread between a tenant and
    the product owners. Framework-side operational data (NOT investigation
    data): the operator legitimately sees these. One ticket = one thread
    of SupportMessage rows."""
    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(index=True, nullable=False)
    author_role: Mapped[str] = mapped_column(String(20))  # tenant | operator
    author_name: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlatformSetting(Base):
    """Operator-global key/value store — currently the OSINT-module API
    keys + Telegram credentials, managed from the Product-Owner console
    Settings tab. These are the FRAMEWORK OPERATOR's own service-provider
    accounts (VirusTotal, HIBP, …), NOT tenant data — every tenant's
    searches run through the operator's shared keys. Stored here (the
    platform-config store) so they survive without editing .env; the
    backend loads them and passes them to the modules per /run request,
    with the .env values kept as a fallback."""
    __tablename__ = "platform_settings"

    skey: Mapped[str] = mapped_column(String(120), primary_key=True)
    svalue: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
