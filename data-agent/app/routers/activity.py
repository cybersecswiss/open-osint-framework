"""The customer's own activity log — who did what in a case, and why.

Without it, the only record of a search would sit in the operator's
database, and there — by design — only as a fingerprint of the selector. The
data controller, who has to answer "why was this person looked up?", would
have nothing.

Entries here carry the selector in clear text and the stated purpose, because
this is the customer's store: the operator has no access to it.

Entries are hash-chained (`previous_hash` → `entry_hash`, SHA-256 over the
canonical fields). No key: the agent has no secret the customer does not also
hold, so this does not stop the customer's own DBA from rewriting history —
it makes an edit or a deleted row *visible*, which is what a reviewer needs.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_framework_key
from app.database import get_db
from app.models import AuditLog

router = APIRouter(tags=["activity"])


class ActivityIn(BaseModel):
    action: str = Field(min_length=1, max_length=50)
    user_name: Optional[str] = Field(default=None, max_length=100)
    case_id: Optional[uuid.UUID] = None
    details: dict = Field(default_factory=dict)
    ip_address: Optional[str] = Field(default=None, max_length=45)


def _hash(prev: Optional[str], fields: dict) -> str:
    canon = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(((prev or "") + canon).encode()).hexdigest()


def _fields(row_id, ts, a: ActivityIn) -> dict:
    return {"id": str(row_id), "ts": ts.isoformat(), "user_name": a.user_name,
            "action": a.action, "case_id": str(a.case_id) if a.case_id else None,
            "details": a.details, "ip": a.ip_address}


@router.post("/activity", status_code=201)
async def record(
    payload: ActivityIn,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    # One chain for the whole store; the advisory lock keeps two concurrent
    # writers from both chaining onto the same predecessor.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('audit_log'))"))
    prev = await db.scalar(
        select(AuditLog.entry_hash)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(1))
    row_id, ts = uuid.uuid4(), datetime.utcnow()
    db.add(AuditLog(
        id=row_id, timestamp=ts, user_name=payload.user_name, action=payload.action,
        case_id=payload.case_id, details=payload.details, ip_address=payload.ip_address,
        previous_hash=prev, entry_hash=_hash(prev, _fields(row_id, ts, payload)),
    ))
    await db.commit()
    return {"id": str(row_id)}


@router.get("/cases/{case_id}/activity")
async def list_for_case(
    case_id: uuid.UUID,
    action: Optional[str] = Query(default=None, max_length=50),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    q = select(AuditLog).where(AuditLog.case_id == case_id)
    if action:
        q = q.where(AuditLog.action == action)
    rows = (await db.execute(q.order_by(AuditLog.timestamp.desc()).limit(limit))).scalars().all()
    return {"entries": [{
        "id": str(r.id), "timestamp": r.timestamp.isoformat(), "user_name": r.user_name,
        "action": r.action, "details": r.details or {},
    } for r in rows]}


@router.get("/activity/verify")
async def verify_chain(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Recompute the chain. Rows written before the chain existed carry no hash and
    are counted separately rather than reported as broken."""
    rows = (await db.execute(
        select(AuditLog).order_by(AuditLog.timestamp, AuditLog.id))).scalars().all()
    prev, ok, broken, unchained = None, 0, [], 0
    for r in rows:
        if not r.entry_hash:
            unchained += 1
            continue
        a = ActivityIn(action=r.action, user_name=r.user_name, case_id=r.case_id,
                       details=r.details or {}, ip_address=r.ip_address)
        if r.previous_hash != prev or r.entry_hash != _hash(prev, _fields(r.id, r.timestamp, a)):
            broken.append(str(r.id))
        else:
            ok += 1
        prev = r.entry_hash
    return {"verified": ok, "broken": broken, "unchained": unchained}
