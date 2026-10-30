"""Append-only, per-tenant, tamper-evident audit log.

``log_action`` appends one hash-chained ``AuditLog`` row. The chain is
serialized per tenant with a Postgres advisory lock so concurrent workers
can't fork it. Writing is best-effort — an audit failure must never break
the action it records (it is logged, not raised).

``verify_chain`` recomputes the whole chain to detect any tampering.

Three things make the chain worth something against a DB-level attacker:

1. **Keyed hashing.** Entries are chained with HMAC-SHA256 under
   ``settings.audit_key``, which lives in the environment, not in the
   database. An unkeyed SHA-256 chain (what this used to be) can be
   recomputed end-to-end by anyone with write access to the table, so it
   only ever proved the DB hadn't been edited by someone *without* DB
   access. Rows written before the switch still verify under the old
   scheme — see ``_legacy_hash`` — so history stays checkable.

2. **Append-only enforcement in the DB.** A trigger rejects UPDATE and
   DELETE on ``audit_log`` (installed by app/bootstrap.py). Nothing in the
   application ever needs either.

3. **External anchors.** ``anchor_chains`` periodically appends each
   tenant's current chain head to a file outside Postgres. A rewritten
   chain no longer matches its anchors, which is what ``verify_chain``
   reports as ``anchors_ok: false``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, text

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.audit import AuditLog

log = logging.getLogger("osint.audit")

# Keys in `details` that carry an investigative selector — what a tenant
# searched for. Redacted according to settings.audit_selector_mode.
_SELECTOR_FIELDS = ("query", "facets", "new_label")


def _canon(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev: Optional[str], fields: dict) -> str:
    """Keyed chain hash (current scheme)."""
    return hmac.new(
        settings.audit_key.encode(),
        _canon({"prev": prev, **fields}).encode(),
        hashlib.sha256,
    ).hexdigest()


def _legacy_hash(prev: Optional[str], fields: dict) -> str:
    """Unkeyed legacy scheme (before keyed hashing). Verification only — never
    used to write a new entry."""
    return hashlib.sha256(_canon({"prev": prev, **fields}).encode()).hexdigest()


def redact_selectors(details: Optional[dict]) -> Optional[dict]:
    """Apply the operator-side selector policy to an audit `details` dict.

    Framework-side audit rows live in the OPERATOR's database. With
    `audit_selector_mode=hashed` the operator can still tell that the same
    selector was searched twice without learning what it was — which is the
    property an authority actually needs from a processor.
    """
    mode = (settings.audit_selector_mode or "full").lower()
    if mode == "full" or not details:
        return details
    out = dict(details)
    for field in _SELECTOR_FIELDS:
        if field not in out or out[field] in (None, "", [], {}):
            continue
        if mode == "off":
            out[field] = "<redacted>"
        else:  # hashed
            raw = _canon(out[field]) if not isinstance(out[field], str) else out[field]
            digest = hmac.new(settings.audit_key.encode(), raw.encode(),
                              hashlib.sha256).hexdigest()[:16]
            out[field] = f"sha256:{digest}"
    return out


def client_ip(request) -> Optional[str]:
    """Best-effort real client IP (honours Cloudflare's forwarded header)."""
    if request is None:
        return None
    h = request.headers
    return (h.get("cf-connecting-ip") or h.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else None) or None)


async def log_action(
    tenant: str,
    action: str,
    *,
    user: Optional[dict] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    details: Optional[dict] = None,
    ip: Optional[str] = None,
) -> None:
    try:
        details = redact_selectors(details)
        async with AsyncSessionLocal() as db:
            # Serialize this tenant's chain across workers/requests.
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"), {"t": tenant})
            prev = await db.scalar(
                select(AuditLog.entry_hash)
                .where(AuditLog.tenant == tenant)
                .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
                .limit(1)
            )
            eid = uuid.uuid4()
            ts = datetime.utcnow()
            tid = str(target_id) if target_id is not None else None
            fields = {
                "id": str(eid), "tenant": tenant, "ts": ts.isoformat(),
                "user_id": (user or {}).get("user_id"),
                "user_name": (user or {}).get("username"),
                "action": action, "target_type": target_type, "target_id": tid,
                "details": details or {}, "ip": ip,
            }
            db.add(AuditLog(
                id=eid, tenant=tenant, timestamp=ts,
                user_id=fields["user_id"], user_name=fields["user_name"],
                action=action, target_type=target_type, target_id=tid,
                details=details or {}, ip_address=ip,
                previous_hash=prev, entry_hash=_hash(prev, fields),
            ))
            await db.commit()
    except Exception as e:  # noqa: BLE001 — audit must never break the action
        # ERROR, not WARNING: a silent gap in an evidentiary log is exactly
        # the kind of thing that must show up in monitoring.
        log.error("AUDIT WRITE FAILED for %s/%s: %s", tenant, action, e)


async def verify_chain(tenant: str) -> dict:
    """Recompute the whole tenant chain; report the first tampered entry.

    Accepts both the keyed (current) and the legacy unkeyed hash per row, so
    entries written before the switch keep verifying. Also checks the
    external anchors, which is what catches a wholesale rewrite: a full
    recomputation of the table would be internally consistent but no longer
    match the heads recorded outside the database.
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AuditLog).where(AuditLog.tenant == tenant)
            .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        )).scalars().all()
    prev = None
    legacy_entries = 0
    for i, r in enumerate(rows):
        fields = {
            "id": str(r.id), "tenant": r.tenant, "ts": r.timestamp.isoformat(),
            "user_id": r.user_id, "user_name": r.user_name,
            "action": r.action, "target_type": r.target_type, "target_id": r.target_id,
            "details": r.details or {}, "ip": r.ip_address,
        }
        if r.previous_hash != prev:
            return {"ok": False, "checked": len(rows), "broken_at": i + 1,
                    "broken_id": str(r.id), "broken_ts": r.timestamp.isoformat(),
                    "reason": "previous_hash does not match the preceding entry"}
        if r.entry_hash == _hash(prev, fields):
            pass
        elif r.entry_hash == _legacy_hash(prev, fields):
            legacy_entries += 1
        else:
            return {"ok": False, "checked": len(rows), "broken_at": i + 1,
                    "broken_id": str(r.id), "broken_ts": r.timestamp.isoformat(),
                    "reason": "entry_hash does not match its content"}
        prev = r.entry_hash

    anchors_ok, anchor_note = _check_anchors(tenant, rows)
    return {"ok": True, "checked": len(rows), "legacy_entries": legacy_entries,
            "anchors_ok": anchors_ok, "anchors": anchor_note}


# ── external anchors ────────────────────────────────────────────────

def _anchor_file(tenant: str) -> Path:
    safe = "".join(c for c in tenant if c.isalnum() or c in "-_") or "unknown"
    return Path(settings.audit_anchor_dir) / f"{safe}.jsonl"


def _check_anchors(tenant: str, rows: list) -> tuple[bool | None, str]:
    """Every recorded anchor must still appear in the chain at the same
    position. Returns (ok, human note); ok is None when nothing is anchored
    yet (fresh install), which is not a failure."""
    path = _anchor_file(tenant)
    if not path.exists():
        return None, "no anchors recorded yet"
    hashes = [r.entry_hash for r in rows]
    checked = 0
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            head, count = rec.get("head"), rec.get("count")
            if not head or not count:
                continue
            checked += 1
            # The anchored head must sit at exactly the position it had when
            # it was written; a truncated or rewritten chain fails here.
            if len(hashes) < count or hashes[count - 1] != head:
                return False, (f"anchor #{checked} (count={count}) no longer matches "
                               f"the chain — the audit table was altered")
    except Exception as e:  # noqa: BLE001
        return None, f"anchors unreadable: {e}"
    return True, f"{checked} anchor(s) verified"


async def anchor_chains() -> int:
    """Append each tenant's current chain head to its anchor file.

    Called on a schedule. The file is outside Postgres, so restoring or
    rewriting the database does not rewrite the anchors with it.
    """
    written = 0
    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(
            select(AuditLog.tenant).distinct()
        )).scalars().all()
        for tenant in tenants:
            rows = (await db.execute(
                select(AuditLog.entry_hash).where(AuditLog.tenant == tenant)
                .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
            )).scalars().all()
            if not rows:
                continue
            path = _anchor_file(tenant)
            try:
                os.makedirs(path.parent, exist_ok=True)
                rec = {"ts": datetime.utcnow().isoformat(),
                       "count": len(rows), "head": rows[-1]}
                with path.open("a") as fh:
                    fh.write(json.dumps(rec) + "\n")
                written += 1
            except OSError as e:
                log.error("audit anchor write failed for %s: %s", tenant, e)
    return written
