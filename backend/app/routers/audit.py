"""Tenant-admin view of the audit log + a chain-integrity check.

Gated by the tenant `admin` role — NOT platform_admin (the operator must
never read tenant investigative activity).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_role
from app.database import get_db
from app.models.audit import AuditLog
from app.services import audit as audit_service

router = APIRouter(tags=["audit"])


@router.get("/audit")
async def list_audit(
    limit: int = Query(100, le=500),
    offset: int = 0,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role("admin")),
):
    tenant = user["tenant"]
    q = select(AuditLog).where(AuditLog.tenant == tenant)
    if action:
        q = q.where(AuditLog.action == action)
    total = await db.scalar(
        select(func.count()).select_from(q.subquery()))
    rows = (await db.execute(
        q.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(limit).offset(offset)
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


@router.get("/audit/verify")
async def verify_audit(user: dict = Depends(require_role("admin"))):
    """Recompute the per-tenant hash chain end-to-end."""
    return await audit_service.verify_chain(user["tenant"])
