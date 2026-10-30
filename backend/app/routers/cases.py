import logging
import re
import uuid
from datetime import datetime

from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services import audit
from app.services.activity import record_activity
from app.services.case_access import can_manage_access, get_visible_case, visible_clause
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.audit import AuditLog
from app.models.case import Case
from app.models.entity import Edge, Entity
from app.models.monitoring import Alert, MonitoringConfig
from app.models.search import SearchJob
from app.schemas.case import CaseCreate, CaseResponse, CaseUpdate
from app.services.agent_client import (
    AgentAuthError,
    AgentUnavailable,
    delete_on_agent,
    put_on_agent,
)
from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

log = logging.getLogger("osint.cases")
router = APIRouter(tags=["cases"])


async def sync_case_to_agent(case: Case, tenant: str) -> None:
    """Mirror case metadata into the customer's store.

    Best-effort by design: a case must still be creatable and renameable
    while the agent is down, and the next search push carries the same
    metadata anyway (see `_agent_payload`). So every agent-side problem is
    logged and swallowed — including an auth error, which is loud enough in
    the search path where it actually costs data.
    """
    from app.routers.search import _case_metadata

    try:
        await put_on_agent(tenant, f"/api/cases/{case.id}", _case_metadata(case))
    except TenantNotConfigured:
        log.debug("case %s: no agent for tenant=%s — metadata stays local",
                  case.id, tenant)
    except (AgentAuthError, AgentKeyUnavailable) as e:
        log.error("case %s: agent auth failure on metadata sync: %s", case.id, e)
    except AgentUnavailable as e:
        log.warning("case %s: agent unreachable on metadata sync (%s) — the next "
                    "search push will carry it", case.id, e)


async def _next_case_number(db: AsyncSession, tenant: str) -> str:
    """Build the next case_number for this tenant.

    Earlier we used `COUNT(*) + 1` here, which collides whenever a case
    in the middle of the sequence was deleted (next_number returns one
    that already exists → unique-constraint 500). Now: take MAX of the
    parsed numeric suffix for this year+tenant, +1. Ignores rows whose
    case_number doesn't match the YYYY-NNN pattern (defensive)."""
    # Serialise per tenant for the length of this transaction. Without it,
    # two people creating a case in the same instant both read the same MAX
    # and both write MAX+1 — `uq_cases_tenant_case_number` then hands one of
    # them an unexplained 500. Unlikely, but the failure is opaque and the
    # idiom is already in the house: the audit chain serialises the same way.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"),
                     {"t": f"caseno:{tenant}"})
    year = datetime.utcnow().year
    rows = (await db.execute(
        select(Case.case_number).where(
            Case.tenant == tenant,
            Case.case_number.like(f"{year}-%"),
        )
    )).scalars().all()
    pattern = re.compile(rf"^{year}-(\d+)$")
    max_n = 0
    for cn in rows:
        m = pattern.match(cn or "")
        if m:
            try:
                max_n = max(max_n, int(m.group(1)))
            except ValueError:
                pass
    return f"{year}-{str(max_n + 1).zfill(3)}"


@router.get("/cases", response_model=list[CaseResponse])
async def list_cases(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(Case).where(visible_clause(user)).order_by(Case.created_at.desc())
    )
    return result.scalars().all()


@router.get("/cases/overview")
async def cases_overview(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """What moved, across all of the caller's cases.

    The situation report on /lagebild answers "what happened in the world".
    This answers the only question that matters at eight in the morning to
    somebody holding twelve open cases: **which of mine moved?**

    Pure aggregation over rows that already exist — search jobs, alerts and
    the case's own timestamps. No new collection, no new storage, and
    deliberately NO agent round-trip: this runs once per page load across
    every case, and asking each customer agent for entity counts would turn
    a dashboard into a fan-out. Counts of findings therefore come from the
    job rows, which is what the job itself recorded.

    `stale_days` is the quiet half of the question. A case nobody has touched
    for three weeks is not visible anywhere today, and an investigation that
    is silently going cold is worth surfacing next to the ones that are busy.
    """
    tenant = user["tenant"]
    cases = (await db.execute(
        select(Case).where(visible_clause(user), Case.status != "closed")
        .order_by(Case.updated_at.desc())
    )).scalars().all()
    if not cases:
        return {"cases": [], "generated_at": datetime.utcnow().isoformat()}

    ids = [c.id for c in cases]

    # Newest job per case, plus what it recorded.
    jobs = (await db.execute(
        select(SearchJob)
        .where(SearchJob.case_id.in_(ids), SearchJob.tenant == tenant)
        .order_by(SearchJob.started_at.desc())
    )).scalars().all()
    latest: dict = {}
    running: dict = {}
    for j in jobs:
        latest.setdefault(j.case_id, j)
        if j.status == "running":
            running[j.case_id] = running.get(j.case_id, 0) + 1

    # Unread alerts per case.
    alert_rows = (await db.execute(
        select(Alert.case_id, func.count())
        .where(Alert.case_id.in_(ids), Alert.tenant == tenant,
               Alert.is_read.is_(False))
        .group_by(Alert.case_id)
    )).all()
    alerts = {cid: n for cid, n in alert_rows}

    now = datetime.utcnow()
    out = []
    for c in cases:
        j = latest.get(c.id)
        last_activity = max(
            [d for d in (c.updated_at, j.started_at if j else None) if d],
            default=c.created_at)
        out.append({
            "id": str(c.id),
            "case_number": c.case_number,
            "title": c.title,
            "priority": c.priority,
            "status": c.status,
            "assigned_to": c.assigned_to,
            "alerts": alerts.get(c.id, 0),
            "running_searches": running.get(c.id, 0),
            "last_search": {
                "query": j.query, "query_type": j.query_type,
                "status": j.status,
                "started_at": j.started_at.isoformat() if j and j.started_at else None,
                "entities": j.entities_count, "edges": j.edges_count,
            } if j else None,
            "last_activity": last_activity.isoformat() if last_activity else None,
            "stale_days": (now - last_activity).days if last_activity else None,
        })

    # Busy first: alerts, then a running search, then recency. A case that
    # needs attention must not sit below one that is merely newer.
    out.sort(key=lambda r: (-(r["alerts"] or 0), -(r["running_searches"] or 0),
                            r["stale_days"] if r["stale_days"] is not None else 9999))
    return {"cases": out, "generated_at": now.isoformat()}


_NOT_PEOPLE = {"scheduler", "system", "n8n"}


@router.get("/cases/assignable-users")
async def assignable_users(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Usernames to offer when assigning a case or adding members.

    Two sources, because one is not always there. If this framework can
    administer the tenant's IdP, its tenant group is the authoritative list.
    A customer running its own IdP (the production case) gives no such
    access — so the names this tenant has already used here (case creators,
    assignees, members, anyone in the audit trail) are offered too. The UI
    still accepts a name typed by hand: a colleague who has never logged in
    must be addable before their first case, not after.
    """
    tenant = user["tenant"]
    names: set[str] = set()
    source = "history"
    try:
        from app.services import keycloak_admin as kc
        g = await kc.find_group_by_name(tenant, tenant)
        if g:
            for m in await kc.group_members(tenant, g["id"]):
                if m.get("username") and m.get("enabled", True):
                    names.add(m["username"])
            source = "idp"
    except Exception as e:  # noqa: BLE001 — own IdP, or KC down: history only
        log.info("assignable-users: IdP not listable for %s (%s)", tenant, e)
    for col in (Case.created_by, Case.assigned_to):
        names.update(n for n in (await db.execute(
            select(col).where(Case.tenant == tenant).distinct())).scalars().all() if n)
    for arr in (await db.execute(select(Case.members).where(Case.tenant == tenant))).scalars().all():
        names.update(arr or [])
    names.update(n for n in (await db.execute(
        select(AuditLog.user_name).where(AuditLog.tenant == tenant).distinct()
    )).scalars().all() if n)
    return {"users": sorted(n for n in names if n not in _NOT_PEOPLE), "source": source}


@router.post("/cases", response_model=CaseResponse, status_code=201)
async def create_case(
    payload: CaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    case = Case(
        tenant=user["tenant"],
        case_number=await _next_case_number(db, user["tenant"]),
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        created_by=user["username"],
        restricted=payload.restricted,
        members=payload.members,
        template=payload.template,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    await sync_case_to_agent(case, user["tenant"])
    await audit.log_action(user["tenant"], "case.create", user=user,
                           target_type="case", target_id=case.id,
                           details={"case_number": case.case_number, "title": case.title,
                                    "template": case.template},
                           ip=audit.client_ip(request))
    return case


@router.get("/cases/{case_id}/retention")
async def case_retention(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """When would this case be deleted, and what suspends it.

    The rule was invisible. `Case.delete_after` exists in the model and the
    purge does not read it — the actual condition is the tenant's
    `auto_delete_months` AND `status == "closed"` AND `updated_at` older than
    that frist. So an OPEN case is never auto-deleted, and reopening a closed
    one suspends the clock. Both are sound; neither was discoverable, which
    meant an investigator could neither rely on the data still being there
    nor know how to keep it.

    Read-only, and honest when it cannot tell: if the license-server is
    unreachable the answer says so instead of implying "no deletion
    configured", which would be the dangerous direction to guess in.
    """
    case = await get_visible_case(db, user, case_id)

    months: int | None = None
    known = True
    try:
        from app.routers.maintenance import _tenants_with_auto_delete
        for tenant, m in await _tenants_with_auto_delete():
            if tenant == user["tenant"]:
                months = int(m)
                break
    except Exception as e:  # noqa: BLE001
        log.warning("retention lookup failed for %s: %s", user["tenant"], e)
        known = False

    purge_at = None
    if known and months and case.status == "closed" and case.updated_at:
        purge_at = (case.updated_at + relativedelta(months=months)).isoformat()

    return {
        "case_id": str(case_id),
        "status": case.status,
        "months": months,
        "known": known,
        # Only ever set for a closed case — an open one has no deletion date,
        # and inventing one would be worse than showing none.
        "purge_at": purge_at,
        "last_activity": case.updated_at.isoformat() if case.updated_at else None,
        "note": ("Only CLOSED cases are deleted, and only after the retention "
                 "period has passed since their last change. Reopening a case "
                 "suspends the deletion."),
    }


@router.get("/cases/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await get_visible_case(db, user, case_id)


@router.put("/cases/{case_id}", response_model=CaseResponse)
async def update_case(
    case_id: uuid.UUID,
    payload: CaseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    case = await get_visible_case(db, user, case_id)
    changed = payload.model_dump(exclude_none=True)
    access_fields = {"restricted", "members"} & changed.keys()
    if access_fields and not can_manage_access(case, user):
        # Who sees a case is decided by whoever opened it, or an admin — not
        # by anyone already inside, who could otherwise widen the circle.
        raise HTTPException(status_code=403, detail="case_access_forbidden")
    before = {"restricted": case.restricted, "members": list(case.members or []),
              "assigned_to": case.assigned_to}
    for field, value in changed.items():
        setattr(case, field, value)
    await db.commit()
    await db.refresh(case)
    await sync_case_to_agent(case, user["tenant"])
    await audit.log_action(user["tenant"], "case.update", user=user,
                           target_type="case", target_id=case.id,
                           details={"fields": list(changed.keys())},
                           ip=audit.client_ip(request))
    if access_fields or "assigned_to" in changed:
        # Who was given or lost access, in the customer's own record. The
        # operator's audit above keeps only the field names.
        after = {"restricted": case.restricted, "members": list(case.members or []),
                 "assigned_to": case.assigned_to}
        if after != before:
            await record_activity(
                user["tenant"], "case.access_change", user_name=user.get("username"),
                case_id=case.id, ip=audit.client_ip(request),
                details={"before": before, "after": after})
    return case


async def cascade_delete_case(db: AsyncSession, case: Case, tenant: str) -> None:
    """Shared "restlos löschen" cascade — used by both the user-driven
    DELETE endpoint and the auto-delete scheduler. Caller is
    responsible for tenant authorization. Order:
      1. Agent-side wipe first (atomic semantics: abort on
         AgentUnavailable so the framework and agent stay in sync).
      2. Local cascade in FK order: Alert → MonitoringConfig →
         SearchJob → Edge → Entity → Case.
    Raises HTTPException(502) on AgentUnavailable so callers can
    surface a clean error to the user."""
    case_id = case.id
    try:
        await delete_on_agent(tenant, f"/api/cases/{case_id}")
    except TenantNotConfigured:
        log.info("case %s delete: no agent for tenant=%s, local-only", case_id, tenant)
    except (AgentAuthError, AgentKeyUnavailable) as e:
        log.error("case %s delete: agent auth failure (%s) — aborting", case_id, e)
        raise HTTPException(status_code=502, detail=str(e))
    except AgentUnavailable as e:
        log.warning("case %s delete: agent unreachable (%s) — aborting", case_id, e)
        raise HTTPException(
            status_code=502,
            detail=(
                "Customer agent unreachable — case NOT deleted. "
                "Investigation data on the agent would have been orphaned. "
                "Try again once the agent is reachable."
            ),
        )

    await db.execute(delete(Alert).where(Alert.case_id == case_id, Alert.tenant == tenant))
    await db.execute(delete(MonitoringConfig).where(
        MonitoringConfig.case_id == case_id, MonitoringConfig.tenant == tenant
    ))
    await db.execute(delete(SearchJob).where(
        SearchJob.case_id == case_id, SearchJob.tenant == tenant
    ))
    await db.execute(delete(Edge).where(Edge.case_id == case_id, Edge.tenant == tenant))
    await db.execute(delete(Entity).where(Entity.case_id == case_id, Entity.tenant == tenant))
    await db.delete(case)
    await db.commit()


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Wipe a case completely — framework metadata + agent investigation
    data. The user explicitly confirms this in the UI; once we get
    here we're in "restlos löschen" mode."""
    if "admin" not in user["roles"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    case = await get_visible_case(db, user, case_id)
    case_number = case.case_number
    await cascade_delete_case(db, case, user["tenant"])
    await audit.log_action(user["tenant"], "case.delete", user=user,
                           target_type="case", target_id=case_id,
                           details={"case_number": case_number},
                           ip=audit.client_ip(request))
