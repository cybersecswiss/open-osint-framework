"""
Monitoring CRUD + pending-scans endpoint for n8n.

The pending-scans endpoint is internal-only
(n8n calls it from inside the docker network) and uses
X-Internal-Key (= API_SECRET_KEY) instead of a JWT — n8n doesn't have
a Keycloak identity.
"""
from __future__ import annotations

import hmac
import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.services import audit
from app.services.agent_client import AgentAuthError, push_to_agent
from app.services.osint_orchestrator import known_query_types
from app.services.activity import ActivityLogUnavailable, record_activity
from app.services.tenant_registry import get_tenant_settings
from app.services.case_access import assert_case_visible, visible_case_ids
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.config import settings
from app.models.monitoring import MonitoringConfig
from app.schemas.monitoring import MonitoringCreate, MonitoringResponse, MonitoringUpdate

log = logging.getLogger("osint.monitoring")

router = APIRouter(tags=["monitoring"])


def _verify_internal(x_internal_key: str = Header(..., alias="X-Internal-Key")):
    # Constant-time compare to avoid leaking the internal key via timing.
    if not hmac.compare_digest(x_internal_key, settings.internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/monitoring/triggers")
async def list_triggers(_: dict = Depends(get_current_user)):
    """Which alert triggers actually fire, and which ones never could.

    The UI offered six (spec §5.7), written for the n8n workflow that was
    never built. Three of them cannot be produced by this pipeline at all,
    and a checkbox that silently does nothing is a defect in itself. Rather than deleting them quietly — which would
    lose the setting of every monitor that uses one — they are reported here
    as unavailable with the reason, so the form can say so.
    """
    from app.services import alerting

    reasons = {
        "profile_changed": ("Entities are not snapshotted, so there is no "
                            "before-state to compare against."),
        "account_deleted": ("Removals are not tracked: a tool that failed and "
                            "a profile that was taken down look identical here."),
        "new_public_post": ("No source reports posting events as such; a new "
                            "post arrives as an ordinary new finding."),
    }
    return {
        "available": [
            {"value": alerting.NEW_ENTITY,
             "description": "Any new finding was added to the case."},
            {"value": alerting.NEW_ACCOUNT,
             "description": "A new account, profile or identifier turned up."},
            {"value": alerting.NEW_EDGE,
             "description": "A watched entity gained a connection."},
        ],
        "unavailable": [
            {"value": key, "reason": reasons.get(key, "Not detectable."),
             "mapped_to": alerting.LEGACY_TRIGGER_MAP.get(key)}
            for key in alerting.UNDETECTABLE_TRIGGERS
        ],
        "legacy_map": {k: v for k, v in alerting.LEGACY_TRIGGER_MAP.items() if v},
        "note": ("An empty list means every available trigger. Stored values "
                 "from the old vocabulary keep working and are translated."),
    }


@router.get("/monitoring", response_model=list[MonitoringResponse])
async def list_monitoring(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    rows = (await db.execute(
        select(MonitoringConfig).where(
            MonitoringConfig.tenant == user["tenant"],
            # Watches of restricted cases are as invisible as the case: the
            # query column is the selector.
            MonitoringConfig.case_id.in_(await visible_case_ids(db, user)))
    )).scalars().all()
    return rows


async def resolve_selector(tenant: str, case_id, entity_id) -> tuple[str, str] | None:
    """(query, query_type) for a watched entity, read from the customer's store.

    The quick-create dialog in the case view sends only the entity id. Stored
    without a selector, such a config would be skipped by the scheduler
    ("no stored selector"), so a watch created from the graph would show as
    active and never run once.
    """
    try:
        res = await push_to_agent(tenant, "/api/entities/lookup", {"ids": [str(entity_id)]})
    except AgentAuthError:
        raise
    except Exception as e:  # noqa: BLE001 — unavailable store, unknown tenant
        log.warning("monitoring: cannot resolve entity %s: %s", entity_id, e)
        return None
    for ent in res.get("entities") or []:
        if str(ent.get("id")) == str(entity_id) and str(ent.get("case_id")) == str(case_id):
            label = (ent.get("label") or "").strip()
            if not label:
                return None
            etype = ent.get("entity_type") or ""
            return label, (etype if etype in known_query_types() else "keyword")
    return None


@router.post("/monitoring", response_model=MonitoringResponse, status_code=201)
async def create_monitoring(
    payload: MonitoringCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, payload.case_id)
    purpose = (payload.purpose or "").strip() or None
    purpose_required = bool((await get_tenant_settings(user["tenant"])).get("require_search_purpose"))
    if purpose_required and not purpose:
        raise HTTPException(status_code=422, detail="purpose_required")

    query, query_type = (payload.query or "").strip() or None, payload.query_type
    if not query:
        resolved = await resolve_selector(user["tenant"], payload.case_id, payload.entity_id)
        if resolved is None:
            # Refused rather than stored: a watch without a selector cannot run.
            raise HTTPException(status_code=422, detail="monitoring_selector_unknown")
        query, query_type = resolved

    config = MonitoringConfig(
        tenant=user["tenant"],
        entity_id=payload.entity_id,
        case_id=payload.case_id,
        interval_hours=payload.interval_hours,
        query=query,
        query_type=query_type,
        modules=payload.modules or [],
        alert_on=payload.alert_on,
        alert_email=payload.alert_email,
        alert_webhook=payload.alert_webhook,
        next_scan=datetime.utcnow() + timedelta(hours=payload.interval_hours),
        created_by=user["username"],
    )
    db.add(config)
    await db.flush()
    # Recorded at the customer before the config is committed: every later
    # unattended rescan points back at this entry (by monitoring_id) for its
    # purpose, so a watch that could not be recorded must not exist.
    try:
        await record_activity(
            user["tenant"], "monitoring.create", user_name=user.get("username"),
            case_id=payload.case_id, ip=audit.client_ip(request), required=purpose_required,
            details={"monitoring_id": str(config.id), "query": query,
                     "query_type": query_type, "purpose": purpose,
                     "interval_hours": payload.interval_hours, "modules": payload.modules})
    except ActivityLogUnavailable as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail="activity_log_unavailable") from e
    await db.commit()
    await db.refresh(config)
    await audit.log_action(user["tenant"], "monitoring.create", user=user,
                           target_type="monitoring", target_id=config.id,
                           details={"case_id": str(config.case_id), "query": config.query,
                                    "purpose_given": bool(purpose)},
                           ip=audit.client_ip(request))
    return config


@router.get("/monitoring/pending-scans")
async def get_pending_scans(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_internal),
):
    """Called by n8n. Internal-only endpoint.

    Returns every active config whose `next_scan` is due, and — critically —
    advances `last_scan`/`next_scan` on the way out so the same config is
    not handed back on every poll (which previously caused an endless
    rescan loop). Each row carries the real selector persisted at create
    time so the rescan reproduces the original search.
    """
    now = datetime.utcnow()
    rows = (await db.execute(
        select(MonitoringConfig).where(
            MonitoringConfig.is_active == True,  # noqa: E712
            MonitoringConfig.next_scan <= now,
        )
    )).scalars().all()

    out = []
    for c in rows:
        # Reproduce the original selector. Fall back to a best-effort
        # module set only for legacy rows created before query columns
        # existed; query_type then comes from the stored value or a
        # generic 'keyword' so it still matches at least some manifests.
        query = c.query or ""
        query_type = c.query_type or "keyword"
        modules = c.modules or ["alias", "leaks", "infra"]
        out.append({
            "config_id": str(c.id),
            "entity_id": str(c.entity_id),
            "case_id": str(c.case_id),
            "tenant": c.tenant,
            "query": query,
            "query_type": query_type,
            "modules": modules,
            "alert_email": c.alert_email,
            "alert_webhook": c.alert_webhook,
        })
        # Mark as scanned and schedule the next run so this config is not
        # re-emitted until the interval elapses again.
        c.last_scan = now
        c.next_scan = now + timedelta(hours=c.interval_hours or 24)

    await db.commit()
    return out


async def _config_visible(db: AsyncSession, user: dict, config: MonitoringConfig) -> bool:
    try:
        await assert_case_visible(db, user, config.case_id)
        return True
    except HTTPException:
        return False


@router.get("/monitoring/{config_id}", response_model=MonitoringResponse)
async def get_monitoring(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    config = await db.scalar(
        select(MonitoringConfig).where(
            MonitoringConfig.id == config_id,
            MonitoringConfig.tenant == user["tenant"],
        )
    )
    if not config or not await _config_visible(db, user, config):
        raise HTTPException(status_code=404, detail="Config not found")
    return config


@router.put("/monitoring/{config_id}", response_model=MonitoringResponse)
async def update_monitoring(
    config_id: uuid.UUID,
    payload: MonitoringUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Partial update. If
    interval_hours changes, we rebase next_scan onto the new cadence
    counted from now (otherwise the user could shorten the interval
    and still wait the original delay)."""
    config = await db.scalar(
        select(MonitoringConfig).where(
            MonitoringConfig.id == config_id,
            MonitoringConfig.tenant == user["tenant"],
        )
    )
    if not config or not await _config_visible(db, user, config):
        raise HTTPException(status_code=404, detail="Config not found")

    data = payload.model_dump(exclude_unset=True)
    interval_changed = "interval_hours" in data and data["interval_hours"] != config.interval_hours
    for k, v in data.items():
        setattr(config, k, v)
    if interval_changed:
        config.next_scan = datetime.utcnow() + timedelta(hours=config.interval_hours)
    await db.commit()
    await db.refresh(config)
    await audit.log_action(user["tenant"], "monitoring.update", user=user,
                           target_type="monitoring", target_id=config.id,
                           details={"fields": list(data.keys())}, ip=audit.client_ip(request))
    return config


@router.delete("/monitoring/{config_id}", status_code=204)
async def delete_monitoring(
    config_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    config = await db.scalar(
        select(MonitoringConfig).where(
            MonitoringConfig.id == config_id,
            MonitoringConfig.tenant == user["tenant"],
        )
    )
    if not config or not await _config_visible(db, user, config):
        raise HTTPException(status_code=404, detail="Config not found")
    await db.delete(config)
    await db.commit()
    await audit.log_action(user["tenant"], "monitoring.delete", user=user,
                           target_type="monitoring", target_id=config_id,
                           ip=audit.client_ip(request))
