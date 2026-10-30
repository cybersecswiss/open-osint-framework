"""
Internal maintenance endpoints — the auto-delete scheduler in main.py
calls these via in-process HTTP-or-direct invocation, and operators can
trigger them manually with the X-Internal-Key for ad-hoc cleanups.

The actual scheduling lives in app.services.scheduler and runs as an
asyncio task in the FastAPI lifespan. This router is the do-the-work
side; the scheduler is the when-to-do-it side.
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime

import httpx
from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.case import Case
from app.routers.cases import cascade_delete_case
from app.services import audit

log = logging.getLogger("osint.maintenance")
router = APIRouter(prefix="/maintenance", tags=["maintenance"])


def _verify_internal(x_internal_key: str = Header(..., alias="X-Internal-Key")):
    if not hmac.compare_digest(x_internal_key, settings.internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _tenants_with_auto_delete() -> list[tuple[str, int]]:
    """Ask license-server for tenants that have set an auto-delete frist.
    Returns list of (tenant, months) tuples."""
    url = f"{settings.license_server_url}/api/v1/tenants/with-auto-delete"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
    if r.status_code == 404:
        # Endpoint not deployed yet — return empty list rather than crashing.
        log.warning("license-server doesn't expose /tenants/with-auto-delete yet")
        return []
    r.raise_for_status()
    return [(row["tenant"], row["auto_delete_months"]) for row in r.json()]


async def run_purge(db: AsyncSession) -> dict:
    """The real work: for each tenant with auto_delete_months set, find
    closed cases whose last update is older than that frist, and run
    the same cascade-delete the user-driven DELETE uses (so agent data
    is wiped too). Returns a summary the caller can log / surface.

    A single agent-unreachable per tenant aborts only that tenant's
    purge — other tenants continue. We don't want one offline customer
    to wedge the whole job."""
    summary: dict = {"started_at": datetime.utcnow().isoformat(), "tenants": {}}
    tenant_configs = await _tenants_with_auto_delete()
    log.info("auto-purge: %d tenants have auto_delete_months set", len(tenant_configs))

    for tenant, months in tenant_configs:
        # Use calendar months, not 30-day approximations — a legally
        # relevant deletion frist must not drift (12 months = 1 year,
        # not 360 days).
        cutoff = datetime.utcnow() - relativedelta(months=months)
        rows = (await db.execute(
            select(Case).where(
                Case.tenant == tenant,
                Case.status == "closed",
                Case.updated_at < cutoff,
            )
        )).scalars().all()
        deleted = 0
        errors = 0
        for case in rows:
            try:
                cn = case.case_number
                cid = case.id
                await cascade_delete_case(db, case, tenant)
                deleted += 1
                # A legally-mandated deletion must leave a provable trail.
                await audit.log_action(
                    tenant, "case.auto_delete",
                    user={"user_id": "system", "username": "auto-delete-scheduler"},
                    target_type="case", target_id=cid,
                    details={"case_number": cn, "frist_months": months})
            except HTTPException as e:
                # Most likely 502 (agent unreachable). Log + skip the
                # remaining cases for this tenant — better to retry the
                # whole batch tomorrow than half-purge.
                log.warning(
                    "auto-purge: tenant=%s case=%s skipped: %s",
                    tenant, case.id, e.detail,
                )
                errors += 1
                break
            except Exception:
                log.exception("auto-purge: tenant=%s case=%s unexpected error", tenant, case.id)
                errors += 1
        summary["tenants"][tenant] = {
            "frist_months": months,
            "candidates": len(rows),
            "deleted": deleted,
            "errors": errors,
        }
        log.info("auto-purge: tenant=%s frist=%dmo cases=%d deleted=%d errors=%d",
                 tenant, months, len(rows), deleted, errors)
    summary["finished_at"] = datetime.utcnow().isoformat()
    return summary


@router.post("/purge-old-cases")
async def purge_old_cases(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_internal),
):
    """Manual / scheduler trigger. Idempotent — running twice in a row
    is fine, the second run finds no new candidates."""
    return await run_purge(db)
