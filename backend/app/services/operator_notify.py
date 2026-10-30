"""The operator's own outbound mail — licence expiry, and nothing else yet.

## Why this is separate from services/notify.py

`notify.py` sends on behalf of a TENANT, through the mail server that tenant
configured. This sends on behalf of the OPERATOR, to a customer's contact
address, about the business relationship. Two different senders, two
different mailboxes, two different sets of credentials — and exactly one
transport implementation, because `notify.send_email()` takes a plain config
dict and knows nothing about who owns it.

## Why the licence-expiry job moved out of n8n

Same three reasons the monitoring rescan moved (see services/scheduler.py):

  * it works on a fresh install with no workflow import — the n8n workflows
    are NOT imported automatically, so on a new server the expiry warning
    simply would not exist and nothing would say so;
  * no second authentication path — n8n called the licence server with the
    internal key, which is a credential in a place it need not be;
  * the action gets an honest actor in the audit trail.

The n8n workflow `License Expiry Monitor` is superseded by this and should
be deleted rather than left importable — an inactive workflow that still
works is a duplicate mail waiting for whoever activates it.

## Storage

`platform_settings` in the licence server, the same operator-global KV bag
as the API keys, with the password Fernet-encrypted by `api_keys._encrypt`
(so `APIKEY_KEK` protects it, like every other operator secret).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

import httpx

from app.config import settings
from app.services import api_keys, notify

log = logging.getLogger("osint.operator_notify")

_KEY = "OPERATOR_SMTP_JSON"
_PW_KEY = "OPERATOR_SMTP_PASSWORD"
# What has already been warned about, so a threshold is not mailed twice.
# {tenant: {"valid_until": "<iso>", "sent": [30, 14]}}
_SENT_KEY = "OPERATOR_EXPIRY_SENT_JSON"
_cache: dict[str, tuple[float, dict]] = {}
_TTL = 20.0

# Which fields the console may set. The password travels separately so it
# can be encrypted with the same helper the API keys use, and so a GET can
# return the rest of the config without it.
_FIELDS = ("enabled", "smtp_host", "smtp_port", "smtp_security",
           "smtp_username", "smtp_from", "smtp_verify_tls",
           "warn_days", "reply_to")

DEFAULTS = {
    "enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_security": "starttls",
    "smtp_username": "",
    "smtp_from": "",
    "smtp_verify_tls": True,
    # A licence that expires in 30 days is a renewal conversation; one that
    # expires in 3 is an outage next week. Warning once at 30 and then going
    # quiet is how these get missed, so the thresholds are a list and the
    # job fires on each of them exactly once per day.
    "warn_days": [30, 14, 7, 3, 1],
    "reply_to": "",
}


async def _platform_settings() -> dict[str, str]:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
        r.raise_for_status()
        return r.json() or {}


async def get_config(force: bool = False) -> dict:
    """Operator transport, password included. Never returned to a browser."""
    now = time.time()
    if not force and "v" in _cache and now - _cache["v"][0] < _TTL:
        return _cache["v"][1]
    cfg = dict(DEFAULTS)
    try:
        raw = await _platform_settings()
        blob = (raw.get(_KEY) or "").strip()
        if blob:
            # Stored as plain JSON: none of these fields is a secret. The
            # password lives under its own key, encrypted.
            cfg.update({k: v for k, v in json.loads(blob).items() if k in _FIELDS})
        stored_pw = (raw.get(_PW_KEY) or "").strip()
        cfg["smtp_password"] = api_keys._decrypt(stored_pw) if stored_pw else ""
    except Exception as exc:  # noqa: BLE001 — store down → unconfigured
        log.warning("operator_notify: cannot read settings: %s", exc)
        cfg["smtp_password"] = ""
    _cache["v"] = (now, cfg)
    return cfg


async def save_config(values: dict) -> dict:
    """Persist. `smtp_password` omitted keeps the stored one, '' clears it."""
    current = await get_config(force=True)
    merged = {k: values.get(k, current.get(k, DEFAULTS[k])) for k in _FIELDS}
    if merged["smtp_security"] not in ("starttls", "ssl", "none"):
        raise ValueError("smtp_security must be starttls, ssl or none")
    if merged["enabled"] and not str(merged["smtp_host"] or "").strip():
        # Same refusal as the tenant side: arming a transport that cannot
        # deliver just moves the failure to 08:00, where nobody sees it.
        raise ValueError("Enabling operator mail needs an SMTP host.")
    merged["warn_days"] = sorted(
        {int(d) for d in (merged.get("warn_days") or DEFAULTS["warn_days"]) if int(d) > 0},
        reverse=True,
    ) or DEFAULTS["warn_days"]

    payload: dict[str, str] = {_KEY: json.dumps(merged)}
    if "smtp_password" in values:
        pw = (values.get("smtp_password") or "").strip()
        payload[_PW_KEY] = api_keys._encrypt(pw) if pw else ""

    url = f"{settings.license_server_url}/api/v1/platform-settings"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(url, headers={"X-Internal-Key": settings.internal_secret},
                        json={"values": payload})
        r.raise_for_status()
    _cache.pop("v", None)
    return await describe()


async def describe() -> dict:
    """What the Product-Owner console may see. No password."""
    cfg = await get_config(force=True)
    out = {k: cfg.get(k, DEFAULTS[k]) for k in _FIELDS}
    out["smtp_password_set"] = bool(cfg.get("smtp_password"))
    return out


async def send_test(recipient: str | None = None) -> notify.DeliveryResult:
    cfg = await get_config(force=True)
    to = (recipient or cfg.get("smtp_from") or "").strip()
    if not to:
        return notify.DeliveryResult(
            "email", False, "Enter a recipient address for the test.")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return await notify.send_email(
        cfg, [to], "OOF — operator mail test",
        f"Operator mail is working.\n\nSent: {now}\n\n"
        "This address is used for licence-expiry warnings to customers.\n",
    )


# ── the job ─────────────────────────────────────────────────────────

async def _expiring(days: int) -> list[dict]:
    url = f"{settings.license_server_url}/api/v1/tenants/expiring?days={days}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
        r.raise_for_status()
        return r.json() or []


async def _load_sent() -> dict:
    try:
        raw = (await _platform_settings()).get(_SENT_KEY) or ""
        return json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        return {}


async def _save_sent(sent: dict) -> None:
    url = f"{settings.license_server_url}/api/v1/platform-settings"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(url, headers={"X-Internal-Key": settings.internal_secret},
                        json={"values": {_SENT_KEY: json.dumps(sent)}})
        r.raise_for_status()


async def run_license_expiry_check(force: bool = False) -> dict:
    """Warn each customer whose licence crosses a threshold today.

    **One mail per tenant per threshold, ever** — not per run. The daily
    Redis lock stops the scheduler from firing twice, but the "run now"
    button in the operator console calls this directly and would otherwise
    send the customer a second identical warning on every click.

    So what has been sent is recorded, keyed by the licence's expiry date.
    Renewing a licence changes that date and therefore clears the record —
    which is right: the next expiry is a new conversation.

    Days below the smallest threshold are silent. By then it is a phone
    call, not a mail.

    `force` re-sends thresholds already recorded. Only for the console, and
    the button says what it does.
    """
    cfg = await get_config()
    warn_days = cfg.get("warn_days") or DEFAULTS["warn_days"]
    out: dict = {"checked": 0, "warned": [], "skipped": []}

    try:
        rows = await _expiring(max(warn_days))
    except Exception as exc:  # noqa: BLE001
        log.warning("license expiry: cannot read the licence server: %s", exc)
        return {"error": str(exc)}

    out["checked"] = len(rows)
    if not rows:
        return out

    if not cfg.get("enabled") or not str(cfg.get("smtp_host") or "").strip():
        # Loud on purpose. A licence that expires unnoticed takes a customer
        # offline, and "operator mail was never configured" must not be a
        # silent condition.
        log.warning("license expiry: %d licence(s) inside the warning window, "
                    "but operator mail is not configured — nobody is being told",
                    len(rows))
        out["skipped"] = [{"tenant": r["tenant"], "reason": "operator mail not configured"}
                          for r in rows]
        return out

    today = datetime.utcnow().date()
    sent = await _load_sent()
    sent_changed = False
    for row in rows:
        try:
            until = datetime.fromisoformat(str(row["valid_until"]).replace("Z", "")).date()
        except (ValueError, KeyError):
            continue
        days_left = (until - today).days
        if days_left not in warn_days:
            continue

        tenant = row["tenant"]
        record = sent.get(tenant) or {}
        if record.get("valid_until") != until.isoformat():
            # A different expiry date than the one we last warned about:
            # the licence was renewed (or shortened). Start over.
            record = {"valid_until": until.isoformat(), "sent": []}
        if days_left in (record.get("sent") or []) and not force:
            out["skipped"].append({"tenant": tenant, "days": days_left,
                                   "reason": "already warned"})
            sent[tenant] = record
            continue

        to = (row.get("email") or "").strip()
        if not to:
            out["skipped"].append({"tenant": row["tenant"], "reason": "no contact address"})
            continue
        subject = (f"OOF — licence for {row['tenant']} expires in "
                   f"{days_left} day{'s' if days_left != 1 else ''}")
        body = (
            f"The licence for {row['tenant']} expires on {until.isoformat()} "
            f"({days_left} day{'s' if days_left != 1 else ''} from now).\n\n"
            "When it expires, OSINT searches stop working until it is renewed. "
            "Existing case data is not affected and stays on your own server.\n\n"
            "Please contact the framework operator to renew.\n"
        )
        if cfg.get("reply_to"):
            body += f"\nContact: {cfg['reply_to']}\n"
        result = await notify.send_email(cfg, [to], subject, body)
        out["warned"].append({"tenant": tenant, "days": days_left,
                              "ok": result.ok, "detail": result.detail})
        if result.ok:
            # Recorded only on success. A mail that did not go out must be
            # retried tomorrow, not marked as delivered.
            record.setdefault("sent", []).append(days_left)
            sent[tenant] = record
            sent_changed = True
        else:
            log.error("license expiry: could not warn %s (%s): %s",
                      tenant, to, result.detail)

    if sent_changed:
        try:
            await _save_sent(sent)
        except Exception:  # noqa: BLE001
            # Worth a line, not worth failing the run: the cost of losing
            # this record is one duplicate warning, the cost of raising here
            # is that the remaining tenants never get theirs.
            log.warning("license expiry: could not persist the sent-record")
    return out
