import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_framework_key
from app.database import get_db
from app.models import Case, Edge, Entity, Evidence

router = APIRouter(tags=["query"])


def _parse(case_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="case_id must be a UUID")


@router.get("/cases")
async def list_cases(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Every case this agent holds, with its row counts.

    Exists for reconciliation. The framework and this store can drift
    apart: cases can exist here with no counterpart in the framework, and
    the other way round. Without this endpoint the framework has no way to
    see that, and it matters more than untidiness: the
    auto-delete routine iterates FRAMEWORK cases, so a case that exists only
    here is never examined and never deleted. Its entities outlive every
    retention rule, unreachable through any user interface because the case
    they belong to does not exist there.

    Two properties matter here:

    **It requires the framework key**, like every other endpoint in this
    router — otherwise anything able to reach the agent's port could
    enumerate the customer's entire case index unauthenticated.

    **It does not return `title`.** In investigative work the title very
    often IS the what: an operation name, a suspect, an offence. For the
    cases this endpoint exists to surface — the ones the framework has no
    record of — that title has never been on the operator's side at all,
    so the reconciliation view must not be the thing carrying it across.

    What remains is genuinely a bucket list: id, case number, status, phase,
    creation date, row counts. Enough to identify an orphan, decide it is
    orphaned, and count what deleting it would cost. Not enough to learn
    what anyone is being investigated for.
    """
    rows = (await db.execute(text("""
        SELECT c.id, c.case_number, c.status, c.created_at, c.phase,
               (SELECT count(*) FROM entities e WHERE e.case_id = c.id) AS entities,
               (SELECT count(*) FROM edges g WHERE g.case_id = c.id) AS edges
        FROM cases c ORDER BY c.created_at DESC
    """))).all()
    return {"cases": [
        {"id": str(r[0]), "case_number": r[1], "status": r[2],
         "created_at": r[3].isoformat() if r[3] else None, "phase": r[4],
         "entities": r[5], "edges": r[6]}
        for r in rows
    ]}


@router.get("/cases/{case_id}/graph")
async def get_graph(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    cid = _parse(case_id)
    entities = (await db.execute(
        select(Entity).where(Entity.case_id == cid)
    )).scalars().all()
    edges = (await db.execute(
        select(Edge).where(Edge.case_id == cid)
    )).scalars().all()

    return {
        "source": "agent",
        "case_id": case_id,
        "entities": [
            {
                "id": str(e.id),
                "entity_type": e.entity_type,
                "label": e.label,
                "data": e.data,
                "source": e.source,
                "confidence": float(e.confidence or 0),
                "is_relevant": e.is_relevant,
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


@router.get("/cases/{case_id}/entities")
async def get_entities(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    cid = _parse(case_id)
    rows = (await db.execute(select(Entity).where(Entity.case_id == cid))).scalars().all()
    return {
        "source": "agent",
        "case_id": case_id,
        "entities": [
            {
                "id": str(e.id),
                "entity_type": e.entity_type,
                "label": e.label,
                "data": e.data,
                "confidence": float(e.confidence or 0),
                "is_relevant": e.is_relevant,
                "url": e.url,
                "notes": e.notes,
                "corroborated_by": e.corroborated_by or [],
                "admiralty": e.admiralty,
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
            }
            for e in rows
        ],
    }


class EntityLookup(BaseModel):
    """Ids to name. Bounded — this is a label lookup, not an export."""
    ids: list[str] = Field(default_factory=list, max_length=500)


@router.post("/entities/lookup")
async def lookup_entities(
    payload: EntityLookup,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Names for a handful of entity ids, across cases.

    ## Why this exists

    The framework's alert list stores identifiers only — the finding itself
    stays here, with the customer. To show a readable list it therefore has
    to ask for the labels, and the only way to do that used to be
    `GET /cases/{id}/graph`, i.e. pull the entire case to name three rows.

    Doing that for one case with several hundred entities can push the
    framework's api container past its 1 GB limit, and a page showing
    alerts from a dozen cases would do it reliably.

    Returns the minimum the list needs — no `data`, no notes, no edges.
    Anything more would make this a back door around
    `GET /cases/{id}/entities`, which is the endpoint for actually reading
    a case.
    """
    out: list[dict] = []
    if not payload.ids:
        return {"source": "agent", "entities": out}
    parsed = []
    for raw in payload.ids[:500]:
        try:
            parsed.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError, TypeError):
            continue          # an unparseable id names nothing; not an error
    if not parsed:
        return {"source": "agent", "entities": out}
    rows = (await db.execute(select(Entity).where(Entity.id.in_(parsed)))).scalars().all()
    return {
        "source": "agent",
        "entities": [
            {"id": str(e.id), "case_id": str(e.case_id), "entity_type": e.entity_type,
             "label": e.label, "url": e.url, "admiralty": e.admiralty}
            for e in rows
        ],
    }


@router.get("/cases/{case_id}/alerts")
async def get_alerts(
    case_id: str,
    _db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Always empty — monitoring is framework-side.

    `monitoring_configs` and `alerts` live in the operator's database, so
    this agent has no alerts to serve. The endpoint stays (returning an
    empty array rather than a 404) because older framework builds call it.

    Callers that need alerts must read the framework tables; the report
    generator does exactly that. Do not "fix" this by inventing an alerts
    table here — whether monitoring data belongs in the sovereign store is
    an open architectural decision, not an oversight.
    """
    return {"source": "agent", "case_id": case_id, "alerts": [],
            "note": "monitoring is framework-side; this endpoint is intentionally empty"}


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case_data(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Delete everything we know about this case: entities, edges, the
    case stub itself. Edges and entities have ON DELETE CASCADE from
    `cases.id`, so the row delete propagates. Idempotent — deleting a
    case the agent has never heard of returns 204 (no rows touched).

    Called from the framework's `DELETE /api/v1/cases/{id}` after the
    user confirms a "delete restlos" — see backend cases.py."""
    cid = _parse(case_id)
    # Belt-and-braces: delete edges/entities explicitly even though the
    # CASCADE on cases would do it. Some early dev DBs were created
    # before the cascade was added, so this is the safe path.
    await db.execute(delete(Edge).where(Edge.case_id == cid))
    await db.execute(delete(Entity).where(Entity.case_id == cid))
    await db.execute(delete(Evidence).where(Evidence.case_id == cid))
    await db.execute(delete(Case).where(Case.id == cid))
    await db.commit()


async def _entity_in_case(db: AsyncSession, eid: uuid.UUID, case_id: uuid.UUID) -> bool:
    return (await db.scalar(
        select(Entity.id).where(Entity.id == eid, Entity.case_id == case_id))) is not None


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    entity_id: str,
    case_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Drop a single entity + every edge that touches it. Used when
    the investigator marks an OSINT hit as a false-positive from the
    graph context menu. Idempotent — DELETEs of unknown ids return 204.

    `case_id` scopes the delete to that case: the
    framework checks the caller may see the case, and this check makes sure
    the entity actually belongs to it — otherwise a visible case would be a
    door into a restricted one."""
    try:
        eid = uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="entity_id must be a UUID")
    if case_id is not None and not await _entity_in_case(db, eid, case_id):
        return
    await db.execute(
        delete(Edge).where((Edge.from_entity == eid) | (Edge.to_entity == eid))
    )
    await db.execute(delete(Entity).where(Entity.id == eid))
    await db.commit()


class NodePos(BaseModel):
    x: float
    y: float


class LayoutGroup(BaseModel):
    """A box the investigator drew around some nodes.

    `members` are entity ids. The box itself is NOT stored as coordinates —
    it is derived from where its members sit, so a group can never drift out
    of sync with what it contains. What IS stored is the grouping decision
    and its name, because that is the part the investigator made.
    """
    id: str = Field(max_length=64)
    label: str = Field(default="", max_length=80)
    color: str = Field(default="", max_length=16)
    members: list[str] = Field(default_factory=list, max_length=500)
    collapsed: bool = False


class LayoutIn(BaseModel):
    """Bounded on purpose. This blob is written from the browser on every
    drag, so an unbounded field here is an unbounded write into the case
    database. The caps are far above any real map (a curated case map holds
    tens of nodes, not thousands)."""
    positions: dict[str, NodePos] = Field(default_factory=dict, max_length=2000)
    groups: list[LayoutGroup] = Field(default_factory=list, max_length=100)


@router.get("/cases/{case_id}/layout")
async def get_layout(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """How this case's map is arranged. Empty dict for a case never laid out
    — the caller then falls back to an automatic layout."""
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="case_id must be a UUID")
    row = await db.scalar(select(Case).where(Case.id == cid))
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    return row.layout or {}


@router.put("/cases/{case_id}/layout")
async def put_layout(
    case_id: str,
    payload: LayoutIn,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Replace the arrangement wholesale.

    Whole-document replace rather than a patch: the map is one coherent
    picture, and merging two half-updates from two open tabs would produce an
    arrangement neither investigator made. Last write wins, which is what a
    layout should do — unlike the findings themselves, nothing is lost that
    cannot be redone by dragging.
    """
    try:
        cid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="case_id must be a UUID")
    row = await db.scalar(select(Case).where(Case.id == cid))
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    row.layout = payload.model_dump()
    await db.commit()
    return {"ok": True, "positions": len(payload.positions),
            "groups": len(payload.groups)}


class BulkDeleteIn(BaseModel):
    """Ids to remove. Bounded because this is the destructive path: an
    unbounded list is an unbounded delete against a case file."""
    ids: list[str] = Field(min_length=1, max_length=1000)
    # Scope to one case: ids from any other case count as
    # not found. Optional so an older framework build keeps working.
    case_id: Optional[uuid.UUID] = None


@router.post("/entities/delete")
async def delete_entities(
    payload: BulkDeleteIn,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Remove many entities at once, with every edge that touches them.

    Exists so removing a whole type of finding is ONE round trip instead of
    one per row. A case here holds 553 open selectors; doing that as 553
    separate deletes would be slow enough that people would stop doing it,
    and each one is a separate chance to fail half way.

    Reports what actually went. The caller must be able to tell a complete
    result from a partial one — "deleted" for a request that removed 40 of
    50 rows would be a false statement about a case file.
    """
    ids: list[uuid.UUID] = []
    invalid = 0
    for raw in payload.ids:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            invalid += 1
    if not ids:
        return {"deleted": 0, "not_found": 0, "invalid": invalid}

    cond = Entity.id.in_(ids)
    if payload.case_id is not None:
        cond = cond & (Entity.case_id == payload.case_id)
    present = set((await db.execute(select(Entity.id).where(cond))).scalars().all())

    if present:
        await db.execute(delete(Edge).where(
            Edge.from_entity.in_(present) | Edge.to_entity.in_(present)))
        await db.execute(delete(Entity).where(Entity.id.in_(present)))
        await db.commit()

    return {
        "deleted": len(present),
        # Already gone is not an error — a second click, or another
        # investigator got there first. Reported separately so the caller
        # does not have to guess which it was.
        "not_found": len(ids) - len(present),
        "invalid": invalid,
    }


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(
    edge_id: str,
    case_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Retract a link the investigator drew by hand.

    **Only `source = "manual"` rows may go.** An edge a tool asserted is the
    record of what a source said at the time it was asked; removing it would
    not correct the case, it would falsify what was found — and the finding it
    came from would still be sitting in the graph, now unexplained. A
    hand-drawn link is the investigator's own assertion, so retracting it is
    theirs to do.

    The rule is enforced HERE, in the sovereign store, and not only in the
    operator's UI. A menu that hides the option is a convenience; a check that
    exists nowhere else is not a check at all, because the endpoint stays
    reachable by anyone holding a session.

    Idempotent for unknown ids (204, like the entity delete). Refusing a
    tool-asserted edge is a 409 and says why, because silently doing nothing
    would read as "deleted".
    """
    try:
        eid = uuid.UUID(edge_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="edge_id must be a UUID")

    row = await db.scalar(select(Edge).where(Edge.id == eid))
    if row is None or (case_id is not None and row.case_id != case_id):
        return                      # already gone, or not this case's edge
    if (row.source or "") != "manual":
        raise HTTPException(
            status_code=409,
            detail=f"edge was asserted by '{row.source or 'an unnamed source'}' "
                   "and is part of the record — only links drawn by hand can "
                   "be retracted",
        )
    await db.execute(delete(Edge).where(Edge.id == eid))
    await db.commit()


class EntityPatch(BaseModel):
    is_relevant: bool | None = None
    label: str | None = None
    # The investigator's own assessment. Stored here, in the sovereign
    # database — it belongs in the case file, not in the operator's DB.
    notes: str | None = None


@router.patch("/entities/{entity_id}")
async def patch_entity(
    entity_id: str,
    payload: EntityPatch,
    case_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Mutate a single entity. Currently only `is_relevant` is patchable —
    the investigator's "mark as relevant" toggle from the graph context
    menu hits this. Returns the updated row so the framework can mirror."""
    try:
        eid = uuid.UUID(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="entity_id must be a UUID")
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    cond = Entity.id == eid
    if case_id is not None:
        cond = cond & (Entity.case_id == case_id)
    res = await db.execute(update(Entity).where(cond).values(**fields).returning(Entity.id))
    if res.first() is None:
        raise HTTPException(status_code=404, detail="entity not found")
    await db.commit()
    row = (await db.execute(select(Entity).where(Entity.id == eid))).scalar_one()
    return {
        "id": str(row.id),
        "is_relevant": row.is_relevant,
        "label": row.label,
        "notes": row.notes,
    }



class CrossCaseIn(BaseModel):
    case_id: uuid.UUID


# Types whose label is a name for something shared by very many cases rather
# than an identifier (a country, a platform) would drown the real matches.
_NOT_IDENTIFYING = {"country", "location", "platform", "tag", "category", "language"}


@router.post("/entities/cross-case")
async def cross_case(payload: CrossCaseIn, db: AsyncSession = Depends(get_db),
                     _: bool = Depends(verify_framework_key)):
    """Which findings of this case also occur in other cases.

    Entity ids are per case (uuid5 over case, type, label), so the match is on
    type + case-folded label. Runs entirely in the customer's store; the
    framework filters the answer down to cases the asking user may see.
    Placeholders are left out — a shell standing in for an edge endpoint says
    nothing about the other case.
    """
    rows = (await db.execute(text("""
        SELECT a.id AS entity_id, b.case_id AS other_case, b.id AS other_entity
        FROM entities a
        JOIN entities b
          ON b.entity_type = a.entity_type AND lower(b.label) = lower(a.label)
         AND b.case_id <> a.case_id
        WHERE a.case_id = :cid
          AND a.entity_type NOT IN ({skip})
          AND COALESCE((a.data->>'virtual')::boolean, false) = false
          AND COALESCE((b.data->>'virtual')::boolean, false) = false
        LIMIT 5000
    """.format(skip=", ".join(f"'{t}'" for t in sorted(_NOT_IDENTIFYING)))),
        {"cid": payload.case_id})).all()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r.entity_id), []).append(
            {"case_id": str(r.other_case), "entity_id": str(r.other_entity)})
    return {"matches": out}
