"""
Agent proxy with local-DB fallback.

Production: backend forwards graph/entities/alerts queries to the
customer's data agent. Without one configured, we serve the same
shape from the framework's own DB so the rest of the stack (frontend,
manual testing) can work end-to-end.

The fallback kicks in when:
  - LICENSE_CHECK_ENABLED is false (no agent registry), or
  - the agent registry has no URL for this tenant, or
  - the agent is unreachable.
"""
from __future__ import annotations

import logging
import uuid
from urllib.parse import quote

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.entity import Edge, Entity
from app.models.case import Case
from app.models.monitoring import Alert
from app.services.agent_client import (
    AgentAuthError,
    AgentUnavailable,
    delete_on_agent,
    get_from_agent,
    patch_on_agent,
    push_to_agent,
    put_on_agent,
)
from app.services import audit
from app.services.activity import record_activity
from app.services.case_access import assert_case_visible, visible_case_ids, visible_clause
from app.services.relevance import score_entities
from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

# A rejected/absent key is a misconfiguration, never a reason to serve or
# write the framework-local copy: doing so would quietly move the tenant's
# data out of their own store. Map both to a 502 the operator can act on.
_AGENT_AUTH_ERRORS = (AgentAuthError, AgentKeyUnavailable)

log = logging.getLogger("osint.agent_proxy")
router = APIRouter(tags=["agent-proxy"])


async def _try_remote_or_fallback(
    tenant: str, endpoint: str, fallback,
):
    try:
        return await get_from_agent(tenant, endpoint)
    except TenantNotConfigured as e:
        log.info("no agent for %s — local fallback (%s)", tenant, e)
        return await fallback()
    except AgentUnavailable as e:
        log.warning("agent down for %s — local fallback (%s)", tenant, e)
        return await fallback()
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))


# Case visibility lives in services/case_access.py (need-to-know).
# `_assert_case_owned` checked the tenant only; `assert_case_visible` checks
# tenant AND, for a restricted case, membership.


async def _local_graph(db: AsyncSession, tenant: str, case_id: uuid.UUID) -> dict:
    case = await db.scalar(select(Case).where(Case.id == case_id, Case.tenant == tenant))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    entities = (await db.execute(
        select(Entity).where(Entity.case_id == case_id, Entity.tenant == tenant)
    )).scalars().all()
    edges = (await db.execute(
        select(Edge).where(Edge.case_id == case_id, Edge.tenant == tenant)
    )).scalars().all()

    return {
        "source": "local-fallback",
        "case_id": str(case_id),
        "entities": [
            {
                "id": str(e.id),
                "entity_type": e.entity_type,
                "label": e.label,
                "data": e.data,
                "source": e.source,
                "confidence": float(e.confidence or 0),
                "is_relevant": e.is_relevant,
                # Same shape as the agent's /graph response — the report and
                # the frontend must not care which store answered.
                "url": e.url,
                "notes": e.notes,
                "corroborated_by": e.corroborated_by or [],
                "admiralty": e.admiralty,
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                "last_verified": e.last_verified.isoformat() if e.last_verified else None,
                "found_at": e.found_at.isoformat() if e.found_at else None,
            }
            for e in entities
        ],
        "edges": [
            {
                "id": str(e.id),
                "from_entity": str(e.from_entity),
                "to_entity": str(e.to_entity),
                "relation_type": e.relation_type,
                "confidence": float(e.confidence or 0),
                "source": e.source,
                "corroborated_by": e.corroborated_by or [],
                "data": e.data or {},
                "found_at": e.found_at.isoformat() if e.found_at else None,
            }
            for e in edges
        ],
    }


async def _local_entities(db: AsyncSession, tenant: str, case_id: uuid.UUID) -> dict:
    g = await _local_graph(db, tenant, case_id)
    return {"source": "local-fallback", "case_id": str(case_id), "entities": g["entities"]}


async def _local_alerts(db: AsyncSession, tenant: str, case_id: uuid.UUID) -> dict:
    """Read alerts the n8n change-detection workflow wrote into the
    framework-local `alerts` table. (When a customer agent is online it
    serves its own alerts; this is the fallback path.)"""
    rows = (await db.execute(
        select(Alert).where(Alert.case_id == case_id, Alert.tenant == tenant)
        .order_by(Alert.created_at.desc())
    )).scalars().all()
    out = [
        {
            "id": str(a.id),
            "case_id": str(a.case_id),
            "entity_id": str(a.entity_id),
            "monitoring_config_id": str(a.monitoring_config_id),
            "change_type": a.change_type,
            "old_value": a.old_value,
            "new_value": a.new_value,
            "is_read": a.is_read,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]
    return {
        "source": "local-fallback",
        "case_id": str(case_id),
        "alerts": await _resolve_alert_entities(db, tenant, out),
    }


def _with_relevance(payload: dict) -> dict:
    """Attach `relevance_score` to every entity in a graph payload.

    Computed here rather than stored, and computed HERE rather than in the
    browser, so the UI and the PDF rank the same case the same way — two
    implementations of a ranking is two rankings. See `services/relevance.py`
    for why it is not a column.
    """
    entities = payload.get("entities")
    if not entities:
        return payload
    scores = score_entities(entities, payload.get("edges") or [])
    for entity in entities:
        entity["relevance_score"] = scores.get(str(entity.get("id")), 0.0)
    return payload


@router.get("/cases/{case_id}/graph")
async def get_graph(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, case_id)
    payload = await _try_remote_or_fallback(
        user["tenant"], f"/api/cases/{case_id}/graph",
        lambda: _local_graph(db, user["tenant"], case_id),
    )
    return _with_relevance(payload)


@router.get("/cases/{case_id}/entities")
async def get_entities(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, case_id)
    payload = await _try_remote_or_fallback(
        user["tenant"], f"/api/cases/{case_id}/entities",
        lambda: _local_entities(db, user["tenant"], case_id),
    )
    # The entities endpoint carries no edges, so centrality and proximity
    # cannot be computed from it. Rather than rank on half the signals and
    # disagree with the graph view, the list re-uses the graph's scores.
    if payload.get("entities"):
        graph = await _try_remote_or_fallback(
            user["tenant"], f"/api/cases/{case_id}/graph",
            lambda: _local_graph(db, user["tenant"], case_id),
        )
        scores = score_entities(graph.get("entities") or [], graph.get("edges") or [])
        for entity in payload["entities"]:
            entity["relevance_score"] = scores.get(str(entity.get("id")), 0.0)
    return payload


@router.get("/cases/{case_id}/activity")
async def get_activity(
    case_id: uuid.UUID,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """The case's activity log from the customer's store — who searched what,
    when, and for what stated purpose. There is no local fallback: the
    operator holds no such record, so an unreachable store is said as such
    rather than answered with an empty list that reads as "nobody searched"."""
    await assert_case_visible(db, user, case_id)
    path = f"/api/cases/{case_id}/activity" + (f"?action={quote(action)}" if action else "")
    try:
        return await get_from_agent(user["tenant"], path)
    except AgentAuthError:
        raise
    except (AgentUnavailable, AgentKeyUnavailable, TenantNotConfigured) as e:
        raise HTTPException(status_code=503, detail="activity_log_unavailable") from e


@router.get("/cases/{case_id}/cross-hits")
async def cross_hits(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Findings of this case that also occur in other cases.

    The match runs in the customer's store. Here it is cut down to the cases
    THIS user may see: a restricted case must not reveal itself through a
    "also in case …" hint, which would say both that it exists and what it
    contains.
    """
    await assert_case_visible(db, user, case_id)
    try:
        res = await push_to_agent(user["tenant"], "/api/entities/cross-case",
                                  {"case_id": str(case_id)})
    except AgentAuthError:
        raise
    except (AgentUnavailable, AgentKeyUnavailable, TenantNotConfigured):
        return {"matches": {}, "cases": {}, "available": False}
    visible = await visible_case_ids(db, user)
    matches: dict[str, list[dict]] = {}
    for eid, hits in (res.get("matches") or {}).items():
        keep = [h for h in hits if uuid.UUID(h["case_id"]) in visible]
        if keep:
            matches[eid] = keep
    case_ids = {uuid.UUID(h["case_id"]) for hits in matches.values() for h in hits}
    cases = {}
    if case_ids:
        for c in (await db.execute(select(Case).where(Case.id.in_(case_ids)))).scalars().all():
            cases[str(c.id)] = {"case_number": c.case_number, "title": c.title, "status": c.status}
    return {"matches": matches, "cases": cases, "available": True}


@router.get("/cases/{case_id}/alerts")
async def get_alerts(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, case_id)
    # Framework database, UNCONDITIONALLY — not via _try_remote_or_fallback.
    #
    # Monitoring is operator-side by design: `monitoring_configs` and `alerts`
    # live here, and the agent's own `/api/cases/{id}/alerts` is a documented
    # stub that answers **HTTP 200 with an empty list**. The fallback helper
    # only falls back on TenantNotConfigured or AgentUnavailable, so that
    # successful empty answer won every time and this endpoint could never
    # return an alert even once alerts exist. The agent says as much in its
    # own docstring: "Callers that need alerts must read the framework
    # tables; the report generator does exactly that."
    #
    # Exactly the kind of thing that costs an afternoon to track down.
    return await _local_alerts(db, user["tenant"], case_id)


async def _resolve_alert_entities(
    db: AsyncSession, tenant: str, rows: list[dict],
) -> list[dict]:
    """Attach the label of the entity each alert points at.

    Alerts store identifiers, never findings (services/alerting.py). The
    label lives with the customer, so it is fetched here and attached to the
    response — it is never written back.

    ## One request, only the ids asked for

    The first version pulled `GET /cases/{id}/graph` per case to name a
    handful of rows. A single case of several hundred entities could push the
    api container past its 1 GB limit and get it OOM-killed — and an alert
    page legitimately spans a dozen cases. It now asks the agent for exactly
    the ids on the page, in one call.

    Falls back to the per-case graph when the agent is older than the
    lookup endpoint, and degrades to bare ids when the agent
    cannot be reached at all: `resolved = false`. A list that dropped the
    alerts it could not decorate would be worse than one showing an id.
    """
    if not rows:
        return rows
    from app.services.agent_client import (
        AgentAuthError, AgentUnavailable, push_to_agent,
    )
    from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

    ids = list({r["entity_id"] for r in rows})[:500]
    index: dict[str, dict] = {}
    try:
        # POST, not GET: a few hundred ids do not belong in a URL.
        payload = await push_to_agent(tenant, "/api/entities/lookup", {"ids": ids})
        index = {str(e.get("id")): e for e in (payload.get("entities") or [])}
    except AgentAuthError:
        # Never silently degrade an auth failure into "agent busy" — the
        # rule this whole path is built on. Surface it as unresolved and let
        # the health check be the place that screams.
        log.warning("alerts: agent rejected the framework key while resolving labels")
    except (AgentUnavailable, TenantNotConfigured, AgentKeyUnavailable):
        pass
    except Exception:  # noqa: BLE001 — most likely an agent without /api/entities/lookup
        try:
            from app.services.report.generator import fetch_agent_data

            for case_id in list({r["case_id"] for r in rows})[:5]:
                data = await fetch_agent_data(tenant, case_id, db)
                for e in (data.get("entities") or []):
                    index[str(e.get("id"))] = e
        except Exception:  # noqa: BLE001
            index = {}

    for r in rows:
        ent = index.get(r["entity_id"])
        r["entity_label"] = ent.get("label") if ent else None
        r["entity_url"] = ent.get("url") if ent else None
        r["admiralty"] = ent.get("admiralty") if ent else None
        r["resolved"] = bool(ent)
    return rows


@router.get("/alerts")
async def list_alerts(
    unread_only: bool = False,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Every alert for the tenant, newest first, with its case title.

    Case-scoped alerts already had an endpoint; this is the one the
    dashboard needs. A tile showing a 0 that merely looked like good news
    would be worse than none; with this endpoint the 0 means something.
    """
    stmt = (
        select(Alert, Case.title, Case.case_number)
        .join(Case, Case.id == Alert.case_id)
        .where(Alert.tenant == user["tenant"], visible_clause(user))
    )
    if unread_only:
        stmt = stmt.where(Alert.is_read.is_(False))
    rows = (await db.execute(
        stmt.order_by(Alert.created_at.desc()).limit(max(1, min(limit, 500)))
    )).all()
    out = [
        {
            "id": str(a.id),
            "case_id": str(a.case_id),
            "case_title": title,
            "case_number": number,
            "entity_id": str(a.entity_id),
            "monitoring_config_id": str(a.monitoring_config_id),
            "change_type": a.change_type,
            "old_value": a.old_value,
            "new_value": a.new_value,
            "is_read": a.is_read,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a, title, number in rows
    ]
    # The label comes from the customer's store, not from ours.
    return {"alerts": await _resolve_alert_entities(db, user["tenant"], out)}


class AlertReadPayload(BaseModel):
    alert_ids: list[uuid.UUID] | None = None
    is_read: bool = True


@router.post("/alerts/read")
async def mark_alerts_read(
    payload: AlertReadPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Mark alerts read (or unread). No ids = every alert of the tenant.

    Tenant-scoped in the WHERE clause, not just in the lookup: an id from
    another tenant simply matches nothing rather than being findable.
    """
    stmt = update(Alert).where(
        Alert.tenant == user["tenant"],
        # Only alerts of cases this user may see — "mark all read" must not
        # reach into a restricted case.
        Alert.case_id.in_(await visible_case_ids(db, user)))
    if payload.alert_ids:
        stmt = stmt.where(Alert.id.in_(payload.alert_ids))
    result = await db.execute(stmt.values(is_read=payload.is_read))
    await db.commit()
    await audit.log_action(
        user["tenant"], "alert.mark_read", user=user, target_type="alert",
        details={"count": result.rowcount, "is_read": payload.is_read},
        ip=audit.client_ip(request))
    return {"updated": result.rowcount, "is_read": payload.is_read}


@router.get("/entities/{entity_id}/diff")
async def entity_diff(
    entity_id: uuid.UUID,
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Provenance history of one entity.

    The n8n `change-detection-alert` workflow calls this route; without it
    the alert chain cannot produce anything.

    `case_id` is a required query parameter rather than being looked up from
    the entity: entities live in the customer's store and are fetched per
    case, so without it there is nothing to search. It also keeps the
    ownership check honest — the case is verified against the tenant before
    anything is read.
    """
    await assert_case_visible(db, user, case_id)
    from app.services import alerting

    result = await alerting.entity_history(user["tenant"], case_id, entity_id, db)
    if not result:
        raise HTTPException(status_code=404, detail="Entity not found in this case")
    return result


class EntityPatchPayload(BaseModel):
    is_relevant: bool | None = None
    label: str | None = None
    # The investigator's own assessment of the node. Lands in the customer's
    # store, not the operator's — it is case-file content.
    notes: str | None = None


async def _local_patch_entity(
    db: AsyncSession, tenant: str, entity_id: uuid.UUID, payload: dict,
    case_id: uuid.UUID,
) -> dict:
    row = await db.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.tenant == tenant,
                             Entity.case_id == case_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    await db.execute(
        update(Entity).where(Entity.id == entity_id).values(**payload)
    )
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "is_relevant": row.is_relevant,
            "label": row.label, "notes": row.notes}


async def _local_delete_entity(
    db: AsyncSession, tenant: str, entity_id: uuid.UUID, case_id: uuid.UUID,
) -> None:
    row = await db.scalar(
        select(Entity).where(Entity.id == entity_id, Entity.tenant == tenant,
                             Entity.case_id == case_id)
    )
    if not row:
        return  # idempotent — DELETE of unknown id is fine
    from sqlalchemy import delete as sqla_delete
    await db.execute(
        sqla_delete(Edge).where(
            (Edge.from_entity == entity_id) | (Edge.to_entity == entity_id)
        )
    )
    await db.execute(sqla_delete(Entity).where(Entity.id == entity_id))
    await db.commit()


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    entity_id: uuid.UUID,
    case_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Drop a single entity + every edge that touches it. Used when
    the investigator marks an OSINT hit as a false-positive from the
    graph context menu. Forwards to the customer agent if configured;
    otherwise falls back to the local table.

    `case_id` is required: the case is checked for visibility
    here, and the agent confirms the entity belongs to it."""
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    try:
        await delete_on_agent(tenant, f"/api/entities/{entity_id}?case_id={case_id}")
    except TenantNotConfigured:
        # No agent configured for this tenant (legacy/dev) — the
        # canonical rows live locally, so delete them here.
        log.info("no agent for %s — local entity delete", tenant)
        await _local_delete_entity(db, tenant, entity_id, case_id)
    except AgentUnavailable as e:
        # A configured-but-unreachable agent owns the canonical row.
        # Deleting only locally would silently desync the two stores, so
        # fail loudly (mirrors cases.cascade_delete_case's atomicity).
        log.warning("agent down for %s — refusing local-only entity delete (%s)", tenant, e)
        raise HTTPException(
            status_code=502,
            detail="Customer agent unreachable — entity not deleted to keep "
                   "framework and agent in sync. Try again when the agent is back.",
        )
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure on delete for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    await audit.log_action(tenant, "entity.delete", user=user,
                           target_type="entity", target_id=entity_id,
                           ip=audit.client_ip(request))


class NodePos(BaseModel):
    x: float
    y: float


class LayoutGroup(BaseModel):
    id: str = Field(max_length=64)
    label: str = Field(default="", max_length=80)
    color: str = Field(default="", max_length=16)
    members: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    collapsed: bool = False


class LayoutPayload(BaseModel):
    positions: dict[str, NodePos] = Field(default_factory=dict, max_length=2000)
    groups: list[LayoutGroup] = Field(default_factory=list, max_length=100)


@router.get("/cases/{case_id}/layout")
async def get_layout(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """How the investigator arranged this case's map.

    An empty object is a normal answer, not an error: a case nobody has laid
    out yet has no arrangement, and the client then falls back to automatic
    placement. Same for a tenant with no agent — the arrangement is case-file
    content and lives in the customer's store, so if there is none, there is
    nothing to serve rather than something to invent operator-side.
    """
    await assert_case_visible(db, user, case_id)
    try:
        return await get_from_agent(user["tenant"], f"/api/cases/{case_id}/layout")
    except (TenantNotConfigured, AgentUnavailable):
        return {}
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure on layout read for %s: %s", user["tenant"], e)
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/cases/{case_id}/layout")
async def put_layout(
    case_id: uuid.UUID,
    payload: LayoutPayload,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Store the arrangement. Fails loudly when the agent is unreachable.

    Deliberately NOT written operator-side as a fallback: the arrangement is
    the investigator's work on the case, and the whole point of the agent is
    that such content does not accumulate here. Silently keeping it locally
    would be the sovereignty leak the architecture exists to prevent — and it
    would be invisible, which is worse than an error the user can see.

    Not audited per write. A drag produces one of these every second or two;
    logging each would drown the audit trail that matters (who read, who
    exported, who deleted) in mouse movements.
    """
    await assert_case_visible(db, user, case_id)
    body = payload.model_dump(mode="json")
    try:
        return await put_on_agent(user["tenant"], f"/api/cases/{case_id}/layout", body)
    except TenantNotConfigured as e:
        raise HTTPException(
            status_code=409,
            detail="No customer agent configured for this tenant — the case "
                   "layout is case content and is only stored there.",
        ) from e
    except AgentUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail="Customer agent unreachable — layout not saved.",
        ) from e
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure on layout write for %s: %s", user["tenant"], e)
        raise HTTPException(status_code=502, detail=str(e))


async def _local_delete_manual_edge(
    db: AsyncSession, tenant: str, edge_id: uuid.UUID, case_id: uuid.UUID,
) -> None:
    """Local-table twin of the agent's rule. Same restriction, deliberately
    duplicated rather than assumed: whichever store happens to hold the row
    must apply it, or the fallback path becomes the way around the rule."""
    row = await db.scalar(
        select(Edge).where(Edge.id == edge_id, Edge.tenant == tenant, Edge.case_id == case_id)
    )
    if not row:
        return  # idempotent
    if (row.source or "") != "manual":
        raise HTTPException(
            status_code=409,
            detail=f"edge was asserted by '{row.source or 'an unnamed source'}' "
                   "and is part of the record — only links drawn by hand can "
                   "be retracted",
        )
    from sqlalchemy import delete as sqla_delete
    await db.execute(sqla_delete(Edge).where(Edge.id == edge_id))
    await db.commit()


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(
    edge_id: uuid.UUID,
    case_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retract a link the investigator drew by hand.

    Only `source = "manual"` edges can go, and the agent enforces that on the
    row itself — this endpoint does not pre-judge, it forwards and passes the
    refusal back. A tool-asserted edge is the record of what a source stated;
    deleting it would falsify the case rather than correct it.
    """
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    try:
        await delete_on_agent(tenant, f"/api/edges/{edge_id}?case_id={case_id}")
    except httpx.HTTPStatusError as e:
        # The agent refuses a tool-asserted edge with 409 and a reason. That
        # reason is the whole answer to "why can I not delete this", so it has
        # to survive the hop — `_raise_for_status` re-raises 4xx as an httpx
        # error that nothing else here catches, which would reach the
        # investigator as a bare 500.
        detail = e.response.text
        try:
            detail = e.response.json().get("detail") or detail
        except ValueError:
            pass
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except TenantNotConfigured:
        log.info("no agent for %s — local edge delete", tenant)
        await _local_delete_manual_edge(db, tenant, edge_id, case_id)
    except AgentUnavailable as e:
        # Same atomicity rule as the entity delete: the agent owns the
        # canonical row, so deleting only locally would desync the stores.
        log.warning("agent down for %s — refusing local-only edge delete (%s)", tenant, e)
        raise HTTPException(
            status_code=502,
            detail="Customer agent unreachable — link not retracted to keep "
                   "framework and agent in sync. Try again when the agent is back.",
        )
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure on edge delete for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    await audit.log_action(tenant, "edge.delete", user=user,
                           target_type="edge", target_id=edge_id,
                           ip=audit.client_ip(request))


class BulkRelevancePayload(BaseModel):
    entity_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    # None clears the mark entirely — "I looked and I am not sure" is a
    # legitimate third state and must stay reachable.
    is_relevant: bool | None = None


@router.post("/cases/{case_id}/entities/relevance")
async def bulk_set_relevance(
    case_id: uuid.UUID,
    payload: BulkRelevancePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Mark many findings at once.

    Why this exists as its own endpoint rather than N calls from the browser:
    a domain search returns several hundred entities (609 in the reference
    case), and triage one row at a time is triage nobody finishes. That
    matters beyond convenience — `is_relevant` drives BOTH the report's
    selection rule and the relevance ranking, so an abandoned triage leaves
    the investigative product resting on a half-made judgement, and the
    report cannot tell that the filtering was incomplete.

    Failures are counted, not swallowed: the response says how many rows were
    actually changed, so a partial result can never read as a complete one.
    """
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    fields = {"is_relevant": payload.is_relevant}
    changed, failed = 0, 0
    for eid in payload.entity_ids:
        try:
            try:
                await patch_on_agent(tenant, f"/api/entities/{eid}?case_id={case_id}", fields)
            except (TenantNotConfigured, AgentUnavailable):
                await _local_patch_entity(db, tenant, eid, fields, case_id)
            changed += 1
        except HTTPException:
            failed += 1          # entity gone or not ours — skip, keep going
        except _AGENT_AUTH_ERRORS as e:
            # An auth failure is not a per-row problem; stop rather than
            # report a partial success that hides a broken agent link.
            log.error("agent auth failure on bulk relevance for %s: %s", tenant, e)
            raise HTTPException(status_code=502, detail=str(e))
        except Exception:  # noqa: BLE001
            failed += 1
    await audit.log_action(tenant, "entities.relevance", user=user,
                           target_type="case", target_id=case_id,
                           details={"requested": len(payload.entity_ids),
                                    "changed": changed, "failed": failed,
                                    "is_relevant": payload.is_relevant},
                           ip=audit.client_ip(request))
    return {"requested": len(payload.entity_ids), "changed": changed,
            "failed": failed}


class BulkDeletePayload(BaseModel):
    entity_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)


@router.post("/cases/{case_id}/entities/delete")
async def bulk_delete_entities(
    case_id: uuid.UUID,
    payload: BulkDeletePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove many findings at once, with every edge that touches them.

    ONE call to the agent, not one per row. The bulk relevance endpoint above
    still loops because PATCH has no bulk form on the agent; here the whole
    point is a case where a type holds hundreds of rows, and hundreds of
    round trips would be slow enough that the removal never gets done.

    **This is the destructive path** and behaves differently from marking
    findings as noise: `is_relevant = false` keeps the row, so the judgement
    can be revisited and the report can still say what was excluded. Deleting
    takes the row out of the case. Both are offered because both are real
    needs — a whole type that is plainly off-target (a hundred Tor mirrors of
    one search page) is clutter, not a judgement worth preserving — but the
    caller has to be the one choosing, which is why they are separate actions
    with separate wording rather than one button.

    Reports what actually went, so a partial result cannot read as complete.
    """
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    ids = [str(x) for x in payload.entity_ids]
    try:
        result = await push_to_agent(tenant, "/api/entities/delete",
                                     {"ids": ids, "case_id": str(case_id)})
    except TenantNotConfigured:
        log.info("no agent for %s — local bulk delete", tenant)
        deleted = 0
        for eid in payload.entity_ids:
            await _local_delete_entity(db, tenant, eid, case_id)
            deleted += 1
        result = {"deleted": deleted, "not_found": 0, "invalid": 0}
    except AgentUnavailable as e:
        # Same atomicity rule as the single delete: the agent owns the rows,
        # so deleting only locally would desync the two stores.
        log.warning("agent down for %s — refusing local-only bulk delete (%s)", tenant, e)
        raise HTTPException(
            status_code=502,
            detail="Customer agent unreachable — nothing was deleted, to keep "
                   "framework and agent in sync. Try again when the agent is back.",
        )
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure on bulk delete for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))

    await audit.log_action(tenant, "entities.delete_bulk", user=user,
                           target_type="case", target_id=case_id,
                           details={"requested": len(ids), **(result or {})},
                           ip=audit.client_ip(request))
    return {"requested": len(ids), **(result or {})}


class MergePayload(BaseModel):
    target_id: uuid.UUID
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


@router.post("/cases/{case_id}/entities/merge")
async def merge_entities(
    case_id: uuid.UUID,
    payload: MergePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """"These are the same" — fold `source_ids` into `target_id`.

    Done in the customer's store (edges re-pointed, corroboration combined,
    an alias kept so the next search does not recreate the merged node). The
    operator side holds entity ids in exactly two places, alerts and watches;
    both are moved to the survivor so neither keeps pointing at a node that
    no longer exists.
    """
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    try:
        result = await push_to_agent(tenant, f"/api/cases/{case_id}/entities/merge", {
            "target_id": str(payload.target_id),
            "source_ids": [str(s) for s in payload.source_ids],
            "merged_by": user.get("username")})
    except httpx.HTTPStatusError as e:
        # 404 (not in this case) / 422 (nothing to merge) — the store's answer.
        try:
            detail = e.response.json().get("detail")
        except ValueError:
            detail = e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=str(detail)[:300])
    except TenantNotConfigured:
        raise HTTPException(status_code=409, detail="merge_needs_customer_store")
    except AgentUnavailable as e:
        raise HTTPException(status_code=503, detail="Customer agent unreachable — nothing merged.") from e
    except _AGENT_AUTH_ERRORS as e:
        raise HTTPException(status_code=502, detail=str(e))

    merged = [uuid.UUID(m["id"]) for m in result.get("merged") or []]
    if merged:
        from app.models.monitoring import MonitoringConfig
        await db.execute(update(Alert).where(
            Alert.tenant == tenant, Alert.case_id == case_id, Alert.entity_id.in_(merged)
        ).values(entity_id=payload.target_id))
        await db.execute(update(MonitoringConfig).where(
            MonitoringConfig.tenant == tenant, MonitoringConfig.case_id == case_id,
            MonitoringConfig.entity_id.in_(merged)
        ).values(entity_id=payload.target_id))
        await db.commit()
    await record_activity(
        tenant, "entity.merge", user_name=user.get("username"), case_id=case_id,
        ip=audit.client_ip(request),
        details={"target": {"id": result.get("target_id"), "label": result.get("target_label")},
                 "merged": result.get("merged"), "query": result.get("target_label")})
    await audit.log_action(tenant, "entity.merge", user=user, target_type="entity",
                           target_id=payload.target_id,
                           details={"merged_ids": [str(m) for m in merged]},
                           ip=audit.client_ip(request))
    return result


@router.patch("/entities/{entity_id}")
async def patch_entity(
    entity_id: uuid.UUID,
    payload: EntityPatchPayload,
    case_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Patch a single entity (is_relevant toggle or label rename).

    Forwards to the customer agent when configured (the agent owns the
    canonical row); otherwise mutates the local fallback table so the
    graph re-renders correctly during dev. Mirrors the agent's PATCH
    response shape either way."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    try:
        result = await patch_on_agent(tenant, f"/api/entities/{entity_id}?case_id={case_id}", fields)
    except httpx.HTTPStatusError as e:
        # The store's own answer — typically 404 for an entity that is not in
        # this case. Passed on as such, not as a 500.
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Entity not found")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text[:300])
    except TenantNotConfigured:
        log.info("no agent for %s — local entity patch", tenant)
        result = await _local_patch_entity(db, tenant, entity_id, fields, case_id)
    except AgentUnavailable as e:
        log.warning("agent down for %s — local entity patch (%s)", tenant, e)
        result = await _local_patch_entity(db, tenant, entity_id, fields, case_id)
    except _AGENT_AUTH_ERRORS as e:
        log.error("agent auth failure on patch for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    # Audit renames (an evidentiary change); skip the high-volume relevance
    # toggle to keep the log signal/noise sane.
    if "label" in fields:
        await audit.log_action(tenant, "entity.rename", user=user,
                               target_type="entity", target_id=entity_id,
                               details={"new_label": fields.get("label")},
                               ip=audit.client_ip(request))
    return result
