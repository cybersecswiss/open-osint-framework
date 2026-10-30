"""
Alert delivery — email and webhook, per tenant.

## What was broken

The alerting half of monitoring used to not exist. Three independent breaks, and this module plus
`services/alerting.py` close the third of them — there was no transport at
all. `MonitoringConfig.alert_email` and `.alert_webhook` had been columns
nobody read.

## The shape

The customer's admin configures the **transport** once, tenant-wide, in
/admin → Settings (mail server, credentials, webhook URL and secret). Each
monitor keeps saying **who** is addressed, falling back to the tenant's
default recipient. That split is why the SMTP password is entered once
rather than per case, and revoked in one place.

## Why stdlib smtplib in a thread

No new dependency, and the call is short-lived and blocking — the same
reason `report/generator.py` runs WeasyPrint in `asyncio.to_thread`.
aiosmtplib would buy nothing here except another pin to keep coordinated.

## Errors are returned, not swallowed

Every function reports *what* failed in terms an administrator can act on:
authentication rejected, connection refused, certificate not trusted, relay
denied. A settings screen that says "sending failed" sends its user to the
mail admin with nothing to go on, and the whole point of the test button is
to end that round trip.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any, Iterable

import httpx

from app.config import settings
from app.services import safe_fetch

log = logging.getLogger("osint.notify")

# Short cache: a rescan can raise several alerts in a row and each one
# would otherwise re-fetch the transport. Cleared explicitly when the
# settings are saved, so a corrected password takes effect on the next
# test click rather than a minute later.
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60.0

SMTP_TIMEOUT = 20
WEBHOOK_TIMEOUT = 15

# A development setup talks to a mail catcher and a webhook receiver on the docker
# network, both of which resolve to private addresses that
# safe_fetch.assert_public_url refuses by design. This opens that door and
# nothing else, and it is off unless explicitly set.
_ALLOW_PRIVATE = os.environ.get("NOTIFY_ALLOW_PRIVATE_TARGETS", "").lower() in ("1", "true", "yes")


class NotifyError(Exception):
    """Delivery failed for a reason worth showing to an administrator."""


@dataclass
class DeliveryResult:
    channel: str            # "email" | "webhook"
    ok: bool
    detail: str             # human-readable, safe to show in the UI
    duration_ms: int = 0

    def as_dict(self) -> dict:
        return {"channel": self.channel, "ok": self.ok,
                "detail": self.detail, "duration_ms": self.duration_ms}


# ── transport config ────────────────────────────────────────────────

async def _license_request(method: str, path: str, **kw) -> httpx.Response:
    url = f"{settings.license_server_url}{path}"
    headers = kw.pop("headers", {})
    headers["X-Internal-Key"] = settings.internal_secret
    async with httpx.AsyncClient(timeout=10) as client:
        return await client.request(method, url, headers=headers, **kw)


async def get_config(tenant: str, *, use_cache: bool = True) -> dict:
    """Decrypted transport for a tenant. Empty dict when the tenant is not
    registered — a dev tenant that never went through the licence server
    must not crash a rescan."""
    now = time.time()
    if use_cache:
        hit = _CACHE.get(tenant)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    try:
        r = await _license_request("GET", f"/api/v1/tenants/{tenant}/notification-config")
        if r.status_code == 404:
            cfg: dict = {}
        else:
            r.raise_for_status()
            cfg = r.json()
    except Exception as exc:  # licence server down — not the tenant's fault
        log.warning("notify: cannot read transport for tenant=%s: %s", tenant, exc)
        return {}
    _CACHE[tenant] = (now, cfg)
    return cfg


def invalidate(tenant: str) -> None:
    _CACHE.pop(tenant, None)


async def record_result(tenant: str, ok: bool, error: str | None = None) -> None:
    """Write delivery health back so the settings screen can show it.
    Best-effort: failing to record a failure must not mask the failure."""
    try:
        await _license_request(
            "POST", f"/api/v1/tenants/{tenant}/notification-result",
            json={"ok": ok, "error": error},
        )
    except Exception as exc:
        log.warning("notify: cannot record delivery result for tenant=%s: %s", tenant, exc)


# ── email ───────────────────────────────────────────────────────────

def _smtp_error_text(exc: Exception) -> str:
    """Translate the exception into something a mail administrator can act
    on. The stdlib messages are accurate but assume you already know SMTP."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (f"Authentication rejected by the server ({exc.smtp_code}). "
                f"Check user name and password — many providers require an "
                f"app-specific password rather than the account password.")
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return (f"The server refused the sender address '{exc.sender}'. "
                f"It usually must match the authenticated account.")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        who = ", ".join(exc.recipients) if exc.recipients else "the recipient"
        return f"The server refused the recipient(s): {who}."
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return ("The server does not offer the requested feature — with "
                "STARTTLS selected this usually means it wants 'SSL' (port "
                "465) or no encryption instead.")
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ("The server's TLS certificate is not trusted. For an "
                "internal relay with a self-signed certificate, switch off "
                "'verify certificate' — deliberately, and knowing what it "
                "costs.")
    if isinstance(exc, ssl.SSLError):
        return (f"TLS handshake failed ({exc}). A mismatch between the port "
                f"and the encryption mode is the usual cause: 587 wants "
                f"STARTTLS, 465 wants SSL.")
    if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
        return f"No answer within {SMTP_TIMEOUT} s — host, port or a firewall."
    if isinstance(exc, ConnectionRefusedError):
        return "Connection refused — nothing is listening on that host and port."
    if isinstance(exc, socket.gaierror):
        return "The host name does not resolve."
    if isinstance(exc, smtplib.SMTPResponseException):
        return f"Server answered {exc.smtp_code}: {exc.smtp_error!r}"
    return f"{type(exc).__name__}: {exc}"


def _build_message(cfg: dict, recipients: list[str], subject: str,
                   body_text: str, body_html: str | None) -> EmailMessage:
    msg = EmailMessage()
    sender = (cfg.get("smtp_from") or cfg.get("smtp_username") or "").strip()
    if not sender:
        raise NotifyError("No sender address configured (From).")
    msg["From"] = formataddr(("OOF", sender))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or "osint.local")
    # Marks the mail as automatic so a recipient's out-of-office does not
    # answer it and so mail filters can route it.
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-OOF"] = "alert"
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")
    return msg


def _send_email_sync(cfg: dict, msg: EmailMessage) -> str:
    host = (cfg.get("smtp_host") or "").strip()
    port = int(cfg.get("smtp_port") or 587)
    security = (cfg.get("smtp_security") or "starttls").lower()
    username = (cfg.get("smtp_username") or "").strip()
    password = cfg.get("smtp_password") or ""
    verify = cfg.get("smtp_verify_tls", True)

    if not host:
        raise NotifyError("No SMTP host configured.")

    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT, context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
    try:
        server.ehlo()
        if security == "starttls":
            server.starttls(context=ctx)
            # A second EHLO after STARTTLS is required by RFC 3207: the
            # capability list before and after the upgrade may differ, and
            # AUTH is frequently only advertised afterwards.
            server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(msg)
        return f"Accepted by {host}:{port}."
    finally:
        try:
            server.quit()
        except Exception:
            # The mail is already handed over; a rude close is not a
            # delivery failure and must not be reported as one.
            pass


async def send_email(cfg: dict, recipients: Iterable[str], subject: str,
                     body_text: str, body_html: str | None = None) -> DeliveryResult:
    to = [r.strip() for r in recipients if (r or "").strip()]
    if not to:
        return DeliveryResult("email", False, "No recipient address configured.")
    started = time.monotonic()
    try:
        msg = _build_message(cfg, to, subject, body_text, body_html)
        detail = await asyncio.to_thread(_send_email_sync, cfg, msg)
        ms = int((time.monotonic() - started) * 1000)
        return DeliveryResult("email", True, detail, ms)
    except NotifyError as exc:
        return DeliveryResult("email", False, str(exc),
                              int((time.monotonic() - started) * 1000))
    except Exception as exc:
        log.warning("notify: SMTP delivery failed: %s", exc)
        return DeliveryResult("email", False, _smtp_error_text(exc),
                              int((time.monotonic() - started) * 1000))


# ── webhook ─────────────────────────────────────────────────────────

def sign_payload(secret: str, body: bytes, timestamp: str) -> str:
    """`X-OSINT-Signature: sha256=<hex>` over "<timestamp>.<body>".

    The timestamp is inside the signed string so a captured POST cannot be
    replayed later with its signature still valid; the receiver checks that
    `X-OSINT-Timestamp` is recent and then recomputes. Signing the body
    alone would authenticate the content but not its freshness.
    """
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


async def send_webhook(cfg: dict, payload: dict) -> DeliveryResult:
    url = (cfg.get("webhook_url") or "").strip()
    if not url:
        return DeliveryResult("webhook", False, "No webhook URL configured.")

    started = time.monotonic()
    # The URL is administrator-supplied and this request leaves from inside
    # the operator's docker network, where `http://updater:9999` is
    # reachable. Without this check the webhook field is a request
    # forwarder into our own internals — the exact hole safe_fetch was
    # written for after module-image had it.
    if not _ALLOW_PRIVATE:
        try:
            await safe_fetch.assert_public_url(url, allow_http=False)
        except safe_fetch.BlockedURL as exc:
            return DeliveryResult(
                "webhook", False,
                f"Target refused: {exc}. The webhook must be a public https "
                f"endpoint — a receiver inside the framework's own network "
                f"is not a customer system.",
                int((time.monotonic() - started) * 1000))

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "OOF-Alerts/1",
        "X-OSINT-Timestamp": ts,
        "X-OSINT-Event": str(payload.get("event") or "alert"),
    }
    secret = cfg.get("webhook_secret") or ""
    if secret:
        headers["X-OSINT-Signature"] = sign_payload(secret, body, ts)

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, follow_redirects=False) as client:
            r = await client.post(url, content=body, headers=headers)
        ms = int((time.monotonic() - started) * 1000)
        if 200 <= r.status_code < 300:
            return DeliveryResult("webhook", True, f"Receiver answered {r.status_code}.", ms)
        # Redirects are not followed on purpose: a 30x on a signed POST
        # would re-send the payload to a target the administrator never
        # entered, and most receivers that redirect are misconfigured.
        snippet = (r.text or "")[:200].replace("\n", " ")
        return DeliveryResult("webhook", False,
                              f"Receiver answered {r.status_code}. {snippet}".strip(), ms)
    except httpx.TimeoutException:
        return DeliveryResult("webhook", False,
                              f"No answer within {WEBHOOK_TIMEOUT} s.",
                              int((time.monotonic() - started) * 1000))
    except httpx.HTTPError as exc:
        return DeliveryResult("webhook", False, f"{type(exc).__name__}: {exc}",
                              int((time.monotonic() - started) * 1000))


# ── the two public entry points ─────────────────────────────────────

def _recipients_for(cfg: dict, override: str | None) -> list[str]:
    raw = (override or cfg.get("default_alert_email") or "").strip()
    # A monitor may address several people; comma or semicolon, because
    # both are what people actually type.
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


async def send_test(tenant: str, channel: str, recipient: str | None = None) -> DeliveryResult:
    """Behind the 'Send test' button. Reads the transport uncached so a
    just-saved password is used, and never touches case data — the test
    payload is synthetic on purpose."""
    cfg = await get_config(tenant, use_cache=False)
    if not cfg:
        return DeliveryResult(channel, False,
                              "This tenant is not registered with the licence server.")

    if channel == "email":
        to = _recipients_for(cfg, recipient)
        if not to:
            return DeliveryResult("email", False,
                                  "Enter a recipient address, or set a default one.")
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        result = await send_email(
            cfg, to,
            "OOF — test message",
            "This is a test message from the OOF.\n\n"
            f"Tenant: {tenant}\nSent:   {now}\n\n"
            "If you are reading this, alert emails will reach you at this "
            "address. No case data is contained in this message.\n",
            f"<p>This is a test message from the <strong>OOF</strong>.</p>"
            f"<table><tr><td>Tenant</td><td><code>{tenant}</code></td></tr>"
            f"<tr><td>Sent</td><td>{now}</td></tr></table>"
            f"<p>If you are reading this, alert emails will reach you at this "
            f"address. No case data is contained in this message.</p>",
        )
    elif channel == "webhook":
        result = await send_webhook(cfg, {
            "event": "test",
            "tenant": tenant,
            "sent_at": datetime.utcnow().isoformat() + "Z",
            "message": "Test delivery from the OOF. No case data.",
        })
    else:
        return DeliveryResult(channel, False, f"Unknown channel '{channel}'.")

    await record_result(tenant, result.ok, None if result.ok else result.detail)
    return result


async def deliver_alerts(tenant: str, alerts: list[dict], *,
                         case_title: str | None = None,
                         recipient: str | None = None,
                         webhook_override: str | None = None,
                         partial: bool = False) -> list[DeliveryResult]:
    """Send one notification covering a batch of alerts.

    One message per rescan, not one per alert: a monitored domain that
    gains forty subdomains overnight would otherwise send forty mails, and
    the recipient would filter the lot into a folder — which is how an
    alerting system stops being read.

    Case *content* stays out of the mail body. It carries counts, change
    types and a deep link; the finding itself is looked at in the
    application, behind the customer's own login. A mail server is not
    inside the sovereign boundary, and this is the one place where the
    framework would otherwise put case data into it.
    """
    if not alerts:
        return []
    cfg = await get_config(tenant)
    if not cfg:
        return []

    wanted = set(cfg.get("notify_events") or [])
    if wanted:
        alerts = [a for a in alerts if a.get("change_type") in wanted]
        if not alerts:
            return []

    results: list[DeliveryResult] = []
    by_type: dict[str, int] = {}
    for a in alerts:
        key = str(a.get("change_type") or "changed")
        by_type[key] = by_type.get(key, 0) + 1
    summary = ", ".join(f"{n}× {k}" for k, n in sorted(by_type.items()))
    case_id = str(alerts[0].get("case_id") or "")
    base = settings.public_base_url
    link = f"{base}/cases/{case_id}" if case_id else base
    label = case_title or (f"case {case_id[:8]}" if case_id else "a monitored case")

    caveat_text = (
        "\nNote: some tools failed during this run, so this list may be "
        "incomplete.\n" if partial else "")
    caveat_html = (
        '<p style="color:#a60">Some tools failed during this run, so this '
        'list may be incomplete.</p>' if partial else "")

    if cfg.get("notify_email_enabled"):
        to = _recipients_for(cfg, recipient)
        subject = f"[OSINT] {len(alerts)} change(s) in {label}"
        text = (
            f"Monitoring found {len(alerts)} change(s) in {label}.\n\n"
            f"Breakdown: {summary}\n"
            f"{caveat_text}\n"
            f"Open the case: {link}\n\n"
            "This message deliberately contains no findings. Details are in "
            "the application, behind your own login.\n"
        )
        html = (
            f"<p>Monitoring found <strong>{len(alerts)}</strong> change(s) in "
            f"<strong>{label}</strong>.</p><p>Breakdown: {summary}</p>"
            f"{caveat_html}"
            f'<p><a href="{link}">Open the case</a></p>'
            "<p style=\"color:#888\">This message deliberately contains no "
            "findings. Details are in the application, behind your own login.</p>"
        )
        results.append(await send_email(cfg, to, subject, text, html))

    if cfg.get("notify_webhook_enabled") or webhook_override:
        wcfg = dict(cfg)
        if webhook_override:
            wcfg["webhook_url"] = webhook_override
        results.append(await send_webhook(wcfg, {
            "event": "alerts",
            "tenant": tenant,
            "case_id": case_id,
            "case_url": link,
            "count": len(alerts),
            "by_change_type": by_type,
            "run_was_partial": partial,
            "sent_at": datetime.utcnow().isoformat() + "Z",
            # Identifiers and change types, not values. A webhook receiver
            # is a customer system, but it is reached over the public
            # internet and the payload is not end-to-end encrypted.
            "alerts": [
                {
                    "id": str(a.get("id") or ""),
                    "entity_id": str(a.get("entity_id") or ""),
                    "change_type": a.get("change_type"),
                    "created_at": a.get("created_at"),
                }
                for a in alerts[:100]
            ],
            "truncated": len(alerts) > 100,
        }))

    if results:
        failed = [r for r in results if not r.ok]
        await record_result(tenant, not failed,
                            "; ".join(f"{r.channel}: {r.detail}" for r in failed) or None)
    return results
