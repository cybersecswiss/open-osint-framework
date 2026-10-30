"""
Search router.

Flow:
  1. POST /search creates a SearchJob row (status=running) and kicks
     off a background task.
  2. The background task runs all requested modules concurrently
     (osint_orchestrator), turns the results into Entity+Edge ORM
     objects (graph_builder), then pushes the payload to the
     customer's data agent (push_to_agent → tenant_registry).
  3. If no agent is reachable yet (agent / licence server not running), the
     payload is persisted into the framework's own DB instead. This
     keeps GET /cases/{id}/graph working end-to-end. Once the agent
     is online the push succeeds and the local fallback no longer
     fires.
  4. GET /search/{id} returns current status + entity/edge counts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.database import AsyncSessionLocal, get_db
from app.models.case import Case
from app.models.entity import Edge, Entity
from app.models.search import SearchJob
from app.services import audit
from app.services.case_access import assert_case_visible, get_visible_case
from app.services.activity import ActivityLogUnavailable, record_activity
from app.services.agent_client import AgentAuthError, AgentUnavailable, push_to_agent
from app.services.graph_builder import build_graph
from app.services.playbooks import for_query_type
from app.services.relevance import rank as rank_entities
from app.services.osint_orchestrator import (
    get_manifests,
    tool_reliability,
    known_query_types,
    refresh_manifests,
    run_modules,
    supported_modules,
)
from app.services.tenant_registry import (
    AgentKeyUnavailable,
    TenantNotConfigured,
    get_enabled_modules,
    get_tenant_settings,
    get_usable_modules,
)

# Conditions under which writing to the framework-local tables instead of the
# customer's agent is CORRECT: no agent configured for this tenant (dev /
# legacy) or the agent is temporarily down. A rejected key is deliberately
# NOT in this set — see services/agent_client for why.
_LOCAL_FALLBACK_ERRORS = (TenantNotConfigured, AgentUnavailable)
_AGENT_AUTH_ERRORS = (AgentAuthError, AgentKeyUnavailable)

log = logging.getLogger("osint.search")
router = APIRouter(tags=["search"])


# A faceted search fans out into one run per facet. Every run hits every
# tool of every selected module, so the cost multiplies fast: 5 facets x 4
# tools is 24 external requests for one click, and sources like DuckDuckGo
# already rate-limit us at moderate volume. Keep the ceiling low and honest.
MAX_FACETS = 5


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    query_type: str = Field(min_length=1)
    case_id: uuid.UUID
    modules: list[str] = Field(default_factory=list)
    # Narrowing terms appended to `query`, e.g. ["Schweiz", "Zürich"] turns
    # "Hells Angels" into three runs: the bare term plus one per facet.
    # Only meaningful for free-text searches — a facet cannot narrow an
    # e-mail address, so non-keyword searches ignore them (see _expand).
    facets: list[str] = Field(default_factory=list, max_length=MAX_FACETS)
    # Optional narrowing to individual tools of the selected modules. EMPTY
    # MEANS ALL — the previous behaviour, and what every existing client
    # sends. It exists so the caller can say "these modules, but skip the
    # three-minute sweeps" without having to drop a whole module and lose its
    # fast tools with it. Names that no selected module offers are ignored
    # rather than rejected: a tenant's module pack can change between the
    # moment the form was rendered and the moment it was submitted.
    tools: list[str] = Field(default_factory=list, max_length=200)
    # Why this search is run: file number, order, legal basis. Mandatory when
    # the tenant switched `require_search_purpose` on. The text goes ONLY to
    # the customer's own activity log; the operator records that a purpose
    # was given, never what it said.
    purpose: str | None = Field(default=None, max_length=500)


# Query types whose value is FREE TEXT, so appending a narrowing term still
# yields a meaningful selector.
#
# `keyword` was the only one for a long time, which was too strict once the
# `corporate` module arrived: a company name plus a city is exactly the case
# that module was built for, and a company or person name narrows the same way a
# keyword does. Everything else stays excluded on purpose — appending "Zürich"
# to an e-mail address, a hash or a wallet produces a selector that matches
# nothing, and silently wrecking the search is worse than ignoring the facet.
_FACETABLE_QUERY_TYPES: frozenset[str] = frozenset({
    "keyword", "company_name", "person_name",
})


def _expand_queries(query: str, query_type: str, facets: list[str]) -> list[str]:
    """Base query first, then one narrowed variant per facet.

    Facets only apply to the free-text types listed in
    `_FACETABLE_QUERY_TYPES`; for every other type they are dropped rather
    than silently wrecking the selector.
    """
    base = query.strip()
    if query_type not in _FACETABLE_QUERY_TYPES:
        return [base]
    out = [base]
    for f in facets:
        f = (f or "").strip()
        if not f:
            continue
        variant = f"{base} {f}"
        if variant not in out:
            out.append(variant)
    return out[:MAX_FACETS + 1]


@router.get("/search/modules")
async def list_supported_modules(user: dict = Depends(get_current_user)):
    """Return cached manifests for every reachable module the caller's
    tenant is licensed for. The frontend uses this to render the
    search-form module list and to decide which modules support the
    chosen query_type — so a tenant only ever sees its licensed modules.
    `allowed is None` => the tenant is licensed for all modules."""
    allowed = await get_usable_modules(user["tenant"])
    manifests = get_manifests()
    # Strip internal `_url` before sending to the browser; filter to the
    # tenant's module pack.
    sanitized = {
        name: {k: v for k, v in m.items() if k != "_url"}
        for name, m in manifests.items()
        if allowed is None or name in allowed
    }
    modules = [m for m in supported_modules() if allowed is None or m in allowed]
    return {"modules": modules, "manifests": sanitized}


@router.get("/search/playbooks")
async def list_playbooks(
    query_type: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Investigation playbooks (module presets per offence type).

    Filtered to what this tenant can actually run, so the form never offers a
    preset that would 403 on submit. `applies` tells the UI whether the
    playbook fits the selector currently typed.
    """
    allowed = await get_usable_modules(user["tenant"])
    reachable = set(supported_modules())
    available = reachable if allowed is None else (reachable & set(allowed))
    return {"playbooks": for_query_type(query_type, available)}


@router.post("/search/modules/refresh")
async def refresh_module_manifests(user: dict = Depends(require_role("admin"))):
    """Re-poll every module's /manifest. Useful after deploying a new
    module without restarting the API.

    Admin-only: this mutates process-global state shared by every tenant,
    so it is an operator action, not something an investigator should be
    able to trigger.
    """
    fresh = await refresh_manifests()
    return {"modules": sorted(fresh.keys())}


# Running searches, by job id. A search is an in-process asyncio task, so
# this map is the ONLY handle on it — and it is per-process on purpose: an
# api restart kills the tasks anyway, and the row-level fallback in
# `cancel_search` covers a job whose owning process is gone.
#
# The dict also keeps the task referenced. asyncio holds only weak references
# to running tasks, so a task nobody keeps can be garbage-collected
# mid-flight; the done-callback removes the entry once it is over.
_RUNNING_SEARCHES: dict[uuid.UUID, asyncio.Task] = {}


def _track_search(job_id: uuid.UUID, task: asyncio.Task) -> None:
    _RUNNING_SEARCHES[job_id] = task
    task.add_done_callback(lambda _t, jid=job_id: _RUNNING_SEARCHES.pop(jid, None))


@router.post("/search", status_code=202)
async def start_search(
    payload: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _ensure_case_and_modules(
        payload.case_id, payload.query, payload.query_type, payload.modules, user, db)

    purpose = (payload.purpose or "").strip() or None
    tenant_settings = await get_tenant_settings(user["tenant"])
    purpose_required = bool(tenant_settings.get("require_search_purpose"))
    if purpose_required and not purpose:
        raise HTTPException(status_code=422, detail="purpose_required")

    queries = _expand_queries(payload.query, payload.query_type, payload.facets)
    job_id = uuid.uuid4()

    # The customer's own record of this search, written BEFORE anything runs.
    # When the tenant requires a purpose, a search that cannot be recorded
    # does not start: the record is the point of the requirement.
    try:
        await record_activity(
            user["tenant"], "search.run", user_name=user.get("username"),
            case_id=payload.case_id, ip=audit.client_ip(request), required=purpose_required,
            details={"job_id": str(job_id), "query": payload.query,
                     "query_type": payload.query_type, "purpose": purpose,
                     "modules": payload.modules, "tools": payload.tools or "all",
                     "facets": payload.facets, "runs": len(queries)})
    except ActivityLogUnavailable as e:
        raise HTTPException(status_code=503, detail="activity_log_unavailable") from e

    job = SearchJob(
        id=job_id,
        tenant=user["tenant"],
        case_id=payload.case_id,
        created_by=user["username"],
        query=payload.query,
        query_type=payload.query_type,
        modules_used=payload.modules,
        status="running",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Started as a tracked asyncio task rather than a BackgroundTask so it can
    # be STOPPED. `background.add_task` hands back no handle at all, which is
    # why a search used to be unstoppable: an investigator who typed the wrong
    # selector, or hit a source that sits at its timeout for five minutes, had
    # no way out but to wait. See `_RUNNING_SEARCHES` and `cancel_search`.
    _track_search(job.id, asyncio.create_task(_run_search(
        job_id=job.id, case_id=payload.case_id, tenant=user["tenant"],
        query=payload.query, query_type=payload.query_type, modules=payload.modules,
        queries=queries, tools=payload.tools,
    )))
    await audit.log_action(user["tenant"], "search.run", user=user,
                           target_type="case", target_id=payload.case_id,
                           details={"query": payload.query, "query_type": payload.query_type,
                                    "modules": payload.modules,
                                    # Which tools ran is part of what was done:
                                    # a narrowed search that found nothing is
                                    # not the same statement as a full one.
                                    "tools": payload.tools or "all",
                                    "facets": payload.facets, "runs": len(queries),
                                    # That a purpose was stated, not what it
                                    # said — the text is the customer's.
                                    "purpose_given": bool(purpose)},
                           ip=audit.client_ip(request))
    return {"job_id": str(job.id), "status": "running"}


@router.get("/search/{job_id}")
async def get_search_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    job = await db.scalar(
        select(SearchJob).where(SearchJob.id == job_id, SearchJob.tenant == user["tenant"])
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.case_id:
        # A job of a restricted case is as invisible as the case: its query
        # is the selector. Same 404 as an unknown job.
        try:
            await assert_case_visible(db, user, job.case_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Job not found")

    # Counts reflect what THIS job actually produced (persisted at
    # completion in _run_search). Used to be a live count from the
    # local Entity table — which broke as soon as the data agent
    # came online, because the rows lived there instead.
    return {
        "job_id": str(job.id),
        "case_id": str(job.case_id),
        "status": job.status,
        "query": job.query,
        "query_type": job.query_type,
        "modules_used": job.modules_used,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message,
        "case_entity_count": job.entities_count or 0,
        "case_edge_count": job.edges_count or 0,
        # Per-tool live state (filled incrementally by the orchestrator
        # via the on_progress callback wired in _run_search).
        "tool_progress": job.tool_progress or [],
    }


@router.post("/search/{job_id}/cancel")
async def cancel_search(
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Stop a running search.

    **What is kept:** everything already found. Findings are flushed per tool
    as they arrive, so the entities and edges from the
    tools that finished are already in the case and stay there — the job ends
    as `cancelled`, which is a different statement from `failed` and must
    stay distinguishable in the case file.

    **What is stopped:** the tools still in flight. Cancelling the task
    propagates into the orchestrator's `gather`, which closes the open HTTP
    calls to the modules. The module process itself may still finish the work
    it started — we simply stop waiting for it.

    A job whose owning task is gone (api restarted since it began) is still
    marked here rather than left to the reaper's ~20-minute timeout, so the
    button does something sensible in that case too.
    """
    job = await db.scalar(
        select(SearchJob).where(SearchJob.id == job_id, SearchJob.tenant == user["tenant"])
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.case_id:
        # A job of a restricted case is as invisible as the case: its query
        # is the selector. Same 404 as an unknown job.
        try:
            await assert_case_visible(db, user, job.case_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "running":
        # Not an error: the investigator clicked as the last tool landed.
        return {"job_id": str(job.id), "status": job.status, "cancelled": False}

    task = _RUNNING_SEARCHES.get(job_id)
    if task is not None and not task.done():
        # The task's own CancelledError handler writes the row and keeps the
        # counts, so this must not race it with a second write.
        task.cancel()
    else:
        await db.execute(
            update(SearchJob).where(SearchJob.id == job_id).values(
                status="cancelled", completed_at=datetime.utcnow(),
                error_message="cancelled by user (no running task on this "
                              "process — the api was restarted since the "
                              "search began)",
            )
        )
        await db.commit()

    await audit.log_action(user["tenant"], "search.cancel", user=user,
                           target_type="case", target_id=job.case_id,
                           details={"job_id": str(job.id), "query": job.query,
                                    "orphaned": task is None},
                           ip=audit.client_ip(request))
    return {"job_id": str(job.id), "status": "cancelled", "cancelled": True}


@router.get("/cases/{case_id}/latest-search")
async def latest_search_for_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Newest search job for a case (or null). Lets an embedded search
    form RESUME a still-running job after a browser refresh or tab switch
    — the background task keeps running server-side regardless, this just
    re-attaches the UI to it. Returns the same shape as GET /search/{id}."""
    await assert_case_visible(db, user, case_id)
    job = await db.scalar(
        select(SearchJob)
        .where(SearchJob.case_id == case_id, SearchJob.tenant == user["tenant"])
        .order_by(SearchJob.started_at.desc())
        .limit(1)
    )
    if not job:
        return {"job": None}
    return {"job": {
        "job_id": str(job.id),
        "case_id": str(job.case_id),
        "status": job.status,
        "query": job.query,
        "query_type": job.query_type,
        "modules_used": job.modules_used,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message,
        "case_entity_count": job.entities_count or 0,
        "case_edge_count": job.edges_count or 0,
        "tool_progress": job.tool_progress or [],
    }}


@router.get("/cases/{case_id}/delta")
async def case_delta(
    case_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """What the most recent search added to this case.

    Deterministic ids make a re-scan idempotent, which is the right behaviour
    but leaves the investigator unable to see what actually changed. On a
    running case that is the question: "since the last run — three new
    subdomains, one new leak-site entry".

    The boundary is the job's `started_at` and the discriminator is the
    agent's `found_at` (write time), so a row that already existed and was
    merely re-confirmed does NOT appear here. That is deliberate: the gap-fill
    ingest touches provenance on existing rows every run, and reporting those
    as "new" would make every re-scan look like a discovery.

    **Removals are not detected.** Nothing in the pipeline records that a
    source stopped returning something — a tool that simply failed would be
    indistinguishable from a takedown, and reporting the second when it was
    the first would be worse than silence. `removed` is therefore always
    absent, not an empty list, so a caller cannot mistake "we do not know" for
    "nothing disappeared".
    """
    case = await get_visible_case(db, user, case_id)

    stmt = select(SearchJob).where(
        SearchJob.case_id == case_id, SearchJob.tenant == user["tenant"]
    )
    if job_id:
        stmt = stmt.where(SearchJob.id == job_id)
    job = await db.scalar(stmt.order_by(SearchJob.started_at.desc()).limit(1))
    if not job:
        return {"job": None, "since": None, "entities": [], "edges": [],
                "note": "no search has been run on this case yet"}

    previous = await db.scalar(
        select(SearchJob)
        .where(SearchJob.case_id == case_id, SearchJob.tenant == user["tenant"],
               SearchJob.started_at < job.started_at)
        .order_by(SearchJob.started_at.desc()).limit(1)
    )

    from app.services import alerting

    boundary = job.started_at
    # ONE implementation of "what this run added", shared with the alert
    # writer (services/alerting.py). Two would be two answers, and the one
    # on screen would drift from the one that sent the mail.
    entities, edges = await alerting.compute_additions(
        user["tenant"], case_id, boundary, db)

    return {
        "job": {
            "job_id": str(job.id), "query": job.query, "query_type": job.query_type,
            "modules_used": job.modules_used, "status": job.status,
            "started_at": job.started_at, "completed_at": job.completed_at,
        },
        "previous_job": (
            {"job_id": str(previous.id), "query": previous.query,
             "started_at": previous.started_at}
            if previous else None
        ),
        "since": boundary,
        "entities": entities,
        "edges": edges,
        "counts": {"entities": len(entities), "edges": len(edges)},
        "note": ("Additions only. Whether a source stopped returning something "
                 "is not tracked — a failed tool and a takedown are not "
                 "distinguishable here."),
    }


async def _ensure_case_and_modules(
    case_id: uuid.UUID, query: str, query_type: str, modules: list[str],
    user: dict, db: AsyncSession,
) -> Case:
    """Shared validation for search + preview: case ownership, known
    modules, per-tenant licensing, and a supportable query_type. Raises
    HTTPException on any failure; returns the owned Case otherwise."""
    case = await get_visible_case(db, user, case_id)
    if not query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    bad = [m for m in modules if m not in supported_modules()]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown modules: {bad}. Supported: {supported_modules()}",
        )
    allowed = await get_usable_modules(user["tenant"])
    if allowed is not None:
        not_usable = [m for m in modules if m not in allowed]
        if not_usable:
            # Two different reasons, two different people to ask: the operator
            # (licence) or the authority's own admin (switched off).
            licensed = await get_enabled_modules(user["tenant"])
            switched_off = [m for m in not_usable if licensed is None or m in licensed]
            if switched_off:
                raise HTTPException(
                    status_code=403,
                    detail=f"Modules switched off by your authority's admin: {switched_off}",
                )
            raise HTTPException(
                status_code=403,
                detail=f"Modules not licensed for this tenant: {not_usable}",
            )
    known = known_query_types()
    if known and query_type not in known:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported query_type '{query_type}'. Supported: {sorted(known)}",
        )
    return case


def _serialize_entity(e: Entity) -> dict[str, Any]:
    """Preview candidate as the pivot drawer sees it.

    The evaluation fields are NOT decoration. `build_graph` computes them for
    a preview too (it is handed `reliability=tool_reliability()`), and they
    used to be dropped right here — so the pivot drawer, the one place where
    an investigator triages fastest, rendered a registry record (A) and a
    scraper hit (D) as two identical rows, and a finding four tools agreed on
    looked like a single hit. Everything below is additive; a consumer that
    ignores the new keys behaves exactly as before.
    """
    return {
        "id": str(e.id), "entity_type": e.entity_type, "label": e.label,
        "data": e.data or {}, "source": e.source,
        "confidence": float(e.confidence or 0),
        "admiralty": e.admiralty,
        "corroborated_by": list(e.corroborated_by or []),
        "url": e.url,
        "observed_at": _iso(e.observed_at),
    }


def _serialize_edge(e: Edge) -> dict[str, Any]:
    return {
        "id": str(e.id), "from_entity": str(e.from_entity),
        "to_entity": str(e.to_entity), "relation_type": e.relation_type,
        "confidence": float(e.confidence or 0),
        # Which tool asserted the relation — same reason as above: an edge a
        # registry stated is not an edge a scraper guessed.
        "source": e.source,
    }


@router.post("/search/preview")
async def preview_search(
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Run the requested modules on `query` and return the resulting
    candidate entities + edges **without persisting anything**. Powers
    the interactive "Erweiterte Suche" (advanced/pivot search): the
    analyst previews hits, cherry-picks the relevant ones, and commits
    only those via POST /cases/{id}/entities/commit.

    Entity ids are the same deterministic uuid5 the normal search would
    assign, so the frontend can flag which candidates already exist in
    the case, and a later commit dedups against them."""
    await _ensure_case_and_modules(
        payload.case_id, payload.query, payload.query_type, payload.modules, user, db)

    job_id = f"preview-{uuid.uuid4()}"
    results = await run_modules(
        payload.query, payload.query_type, payload.modules, job_id,
        tools=payload.tools)
    entities, edges = build_graph(
        results, payload.case_id, user["tenant"], job_id,
        root_query=payload.query, root_query_type=payload.query_type,
        reliability=tool_reliability(),
    )
    errors: list[str] = []
    notes: list[str] = []
    for r in results:
        errors.extend(r.get("errors", []) or [])
        notes.extend(r.get("notes", []) or [])

    # Rank the candidates with the SAME function the case graph and the report
    # use (`agent_proxy._with_relevance` does this for /cases/{id}/graph).
    # Without it the drawer fell back to whatever order the modules happened to
    # answer in, which puts the loudest source first — the exact problem the
    # ranking was written for. Two rankings in one product would be two
    # rankings, so the browser must not compute its own.
    serialized_entities = [_serialize_entity(e) for e in entities]
    serialized_edges = [_serialize_edge(e) for e in edges]
    return {
        "query": payload.query,
        "query_type": payload.query_type,
        "entities": rank_entities(serialized_entities, serialized_edges),
        "edges": serialized_edges,
        "errors": errors,
        "notes": notes,
    }


@router.get("/cases/{case_id}/worklist")
async def case_worklist(
    case_id: uuid.UUID,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Findings in this case that could be searched and never have been.

    "Did I miss something?" is the question nobody could answer: whether a
    node was FOUND is visible everywhere, whether it was ever ASKED ABOUT is
    recorded nowhere the investigator can see. A domain that turned up in a
    certificate and was never scanned looks exactly like one that was scanned
    and yielded nothing.

    Computed, never stored — a join over the case's entities and its
    `search_jobs`, both of which already exist. No new collection.
    """
    case = await get_visible_case(db, user, case_id)

    from app.services.report.generator import fetch_agent_data
    from app.services import worklist as wl

    data = await fetch_agent_data(user["tenant"], str(case_id), db)
    entities = data.get("entities") or []
    edges = data.get("edges") or []
    # Same ranking as the findings list and the report — a third ordering
    # would be a third opinion about what matters.
    ranked = rank_entities(entities, edges)

    rows = (await db.execute(
        select(SearchJob.query, SearchJob.query_type)
        .where(SearchJob.case_id == case_id, SearchJob.tenant == user["tenant"])
    )).all()

    # Which query types anything can actually run, from the tenant's modules.
    allowed = await get_usable_modules(user["tenant"])
    by_qt: dict[str, list[str]] = {}
    for name, manifest in get_manifests().items():
        if allowed is not None and name not in allowed:
            continue
        for tool_desc in manifest.get("tools", []) or []:
            for qt in tool_desc.get("query_types") or []:
                by_qt.setdefault(qt, []).append(tool_desc.get("tool"))

    # Built unbounded, then sliced — so `total` is the real number of open
    # selectors and `candidates` is only how many are being shown.
    #
    # Before this, `candidates` WAS the sliced length, i.e. the cap. Most
    # cases then reported exactly 50: the limit, not a fact about the case. Anything reading that number — the panel headline,
    # the "next step" bar — would have stated a truncation as a finding, which
    # is the same failure as a silent cap anywhere else in this system.
    all_items = wl.build(ranked, [(q, qt) for q, qt in rows], by_qt,
                         limit=1_000_000)
    items = all_items[:limit]
    return {
        "case_id": str(case_id),
        "searched": len(rows),
        "candidates": len(items),
        "total": len(all_items),
        "truncated": len(all_items) > len(items),
        "items": items,
        "note": ("Selectors present in this case that no search has used yet. "
                 "Being unsearched is not evidence of anything — it only means "
                 "nobody has asked."),
    }


def _nd(obj: dict[str, Any]) -> str:
    """One NDJSON line."""
    return json.dumps(obj, default=str) + "\n"


@router.post("/search/preview/stream")
async def preview_search_stream(
    payload: SearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """The same run as `/search/preview`, but the answer arrives WHILE it
    happens: a tool table up front, live per-tool status, ranked candidates
    after every lull, and a final message.

    **Why a stream and not a job id.** The obvious shape would be
    POST-returns-id + poll, like `/ai-link`. That needs the candidates parked
    somewhere both uvicorn workers can read — i.e. Redis. But the stack's
    Redis runs with `--appendonly yes` and writes `dump.rdb`, so parking preview
    candidates there would put investigation findings on the OPERATOR's disk
    and into the operator's backups. That is precisely what the first rule of
    the architecture forbids, and a preview is not worth breaking it for.
    Streaming keeps every finding in the worker's memory for the life of one
    request — strictly less operator-side residue than the previous
    synchronous endpoint had, since that one at least held the same data for
    the same time but gave nothing back until the end.

    **Cancelling** is the client closing the connection: the run task is
    cancelled with it, so an analyst who typed the wrong selector stops paying
    for it immediately instead of waiting out a five-minute sweep.

    `X-Accel-Buffering: no` stops nginx from buffering the body, and the
    one-second heartbeat keeps `proxy_read_timeout` from ever firing — so this
    needs no nginx change of its own.
    """
    await _ensure_case_and_modules(
        payload.case_id, payload.query, payload.query_type, payload.modules, user, db)
    tenant = user["tenant"]

    async def generate():
        job_id = f"preview-{uuid.uuid4()}"
        results: list[dict[str, Any]] = []
        queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(**kw: Any) -> None:
            await queue.put({
                "type": "progress",
                "module": kw.get("module"), "tool": kw.get("tool"),
                "status": kw.get("status"),
                "findings": kw.get("findings", 0),
                "duration": round(float(kw.get("duration") or 0), 1),
                "errors": kw.get("errors") or [], "notes": kw.get("notes") or [],
            })

        async def on_tool(module: str, tool: str, res: dict[str, Any]) -> None:
            results.append(res)
            await queue.put({"type": "tick"})

        def snapshot(final: bool) -> dict[str, Any]:
            entities, edges = build_graph(
                list(results), payload.case_id, tenant, job_id,
                root_query=payload.query, root_query_type=payload.query_type,
                reliability=tool_reliability(),
            )
            ser_e = [_serialize_entity(e) for e in entities]
            ser_x = [_serialize_edge(e) for e in edges]
            return {
                "type": "done" if final else "partial",
                "entities": rank_entities(ser_e, ser_x),
                "edges": ser_x,
            }

        runner = asyncio.create_task(run_modules(
            payload.query, payload.query_type, payload.modules, job_id,
            on_progress=on_progress, on_tool_complete=on_tool,
            tools=payload.tools,
        ))

        yield _nd({"type": "start", "query": payload.query,
                   "query_type": payload.query_type})
        dirty = False
        started = time.monotonic()
        try:
            while True:
                # No `request.is_disconnected()` poll here on purpose: measured
                # on Starlette 0.37.2, it never fires inside a StreamingResponse
                # — neither through nginx nor against the app directly. It does
                # not need to. `StreamingResponse.__call__` runs
                # `listen_for_disconnect(receive)` alongside the generator and
                # cancels the task group when the client goes away, so the
                # cancellation arrives at the `yield` below as a CancelledError
                # and is handled there. A disconnect check that demonstrably never
                # triggers is worse than none: it reads like the safeguard.
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    msg = None

                if msg is None:
                    # A lull. Rebuild once if anything came in, else keep the
                    # connection warm so no proxy times the request out.
                    if dirty:
                        dirty = False
                        yield _nd(snapshot(False))
                    else:
                        yield _nd({"type": "heartbeat"})
                elif msg["type"] == "tick":
                    # Coalesced by construction: rebuilding costs a full graph
                    # pass, so it waits until the burst of finishing tools has
                    # drained rather than running once per tool.
                    dirty = True
                else:
                    yield _nd(msg)

                if dirty and queue.empty():
                    dirty = False
                    yield _nd(snapshot(False))
                if runner.done() and queue.empty():
                    break

            final_results = await runner
            # run_modules short-circuits without firing the per-tool hook when
            # no tool matched at all; take its list in that case so the error
            # row still reaches the analyst.
            if len(results) < len(final_results):
                results[:] = final_results

            errors: list[str] = []
            notes: list[str] = []
            for r in results:
                errors.extend(r.get("errors") or [])
                notes.extend(r.get("notes") or [])
            out = snapshot(True)
            out["errors"] = errors
            out["notes"] = notes
            yield _nd(out)
        except asyncio.CancelledError:
            # The analyst closed the drawer or retyped the selector. Logged,
            # not silent: "cancelled" and "died" look identical from outside,
            # and stopping a five-minute sweep early is the point of this
            # endpoint — an operator should be able to see it happening.
            log.info("preview stream cancelled by client after %.1fs "
                     "(%d tool result(s) in)",
                     time.monotonic() - started, len(results))
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("preview stream failed")
            yield _nd({"type": "error", "detail": f"{type(e).__name__}: {e}"})
        finally:
            # The single place that guarantees the fan-out stops. Reached on
            # cancellation, on error and on the normal path alike, so a client
            # that vanishes never leaves 15 module calls running for nothing.
            if not runner.done():
                runner.cancel()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


class CommitEntity(BaseModel):
    id: uuid.UUID
    entity_type: str
    label: str
    data: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    confidence: float | None = None
    # Provenance, handed back from the preview response. Without these a
    # finding taken over through the pivot reached the customer WITHOUT a
    # citation and without a rating, while the identical finding from a normal
    # search arrived complete — the same "provenance dies at a boundary" defect
    # that had already been fixed for the search path, on the other branch.
    # Optional throughout, so an older client that omits them still commits.
    url: str | None = None
    observed_at: datetime | None = None
    admiralty: str | None = Field(default=None, max_length=2)
    corroborated_by: list[str] = Field(default_factory=list, max_length=50)


class CommitEdge(BaseModel):
    # Optional. The pivot preview hands out ids built the same way the search
    # path builds them, and sending those back keeps one logical edge at one
    # identity. A manually drawn link has no preview behind it and omits the
    # id — the server then derives it, so drawing the same link twice
    # collapses instead of adding a second identical edge.
    id: uuid.UUID | None = None
    from_entity: uuid.UUID
    to_entity: uuid.UUID
    relation_type: str
    confidence: float | None = None
    source: str | None = None


class CommitRequest(BaseModel):
    entities: list[CommitEntity] = Field(default_factory=list)
    edges: list[CommitEdge] = Field(default_factory=list)


@router.post("/cases/{case_id}/entities/commit")
async def commit_entities(
    case_id: uuid.UUID,
    payload: CommitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Persist a chosen subset of preview candidates into the case.
    Same ingest path as a normal search (push to the customer agent,
    local fallback), so deterministic ids dedup against existing rows.
    Edges whose endpoints aren't present (here or already in the case)
    are dropped by the agent ingest — safe for partial selections."""
    case = await get_visible_case(db, user, case_id)
    # Edges alone are a valid commit: a link the investigator draws by hand
    # runs between two entities the case ALREADY holds, so it carries no
    # entities at all. Requiring them here rejected every manual link with
    # "no entities to commit".
    if not payload.entities and not payload.edges:
        raise HTTPException(status_code=400, detail="nothing to commit")

    tenant = user["tenant"]
    # Ids are recomputed from the (type, label) the client committed rather
    # than taken from the request. The preview handed out deterministic ids,
    # so an honest client sends back exactly what we recompute here — but a
    # forged id could otherwise collide with an unrelated node, and the
    # ingest's ON CONFLICT DO NOTHING would silently drop the write.
    from app.services.graph_builder import canonical_entity as _canon_entity

    entities = []
    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for e in payload.entities:
        norm_type, clean_label, ent_id = _canon_entity(case_id, e.entity_type, e.label)
        id_map[e.id] = ent_id
        entities.append(Entity(
            id=ent_id, case_id=case_id, tenant=tenant,
            entity_type=norm_type, label=clean_label, data=e.data or {},
            source=e.source or "pivot", confidence=e.confidence or 0.8,
            url=e.url,
            # Naive UTC — the column is naive, and a tz-aware value makes
            # asyncpg reject the write.
            observed_at=_naive_utc(e.observed_at),
            admiralty=e.admiralty,
            corroborated_by=list(e.corroborated_by or []) or None,
        ))
    from app.services.graph_builder import canonical_edge as _canon_edge

    edges = []
    for x in payload.edges:
        frm = id_map.get(x.from_entity, x.from_entity)
        to = id_map.get(x.to_entity, x.to_entity)
        edges.append(Edge(
            # Derived, never taken from the client — the same rule the entity
            # loop above follows and for the same reason. It used to be
            # `x.id or _canon_edge(...)`, which was not exploitable (the
            # case_id comes from the path and the agent ingests ON CONFLICT
            # DO NOTHING, so a collision drops the NEW row rather than
            # overwriting an old one) but it left two rules for two id kinds
            # in one function, with the reasoning written down for only one
            # of them. Deriving both means a re-committed edge collapses onto
            # the same row instead of depending on what the browser sent.
            id=_canon_edge(case_id, str(frm), str(to), x.relation_type),
            case_id=case_id, tenant=tenant,
            from_entity=frm, to_entity=to,
            relation_type=x.relation_type, confidence=x.confidence or 0.8,
            # The asserting tool when the preview named one; "pivot" only when
            # it did not. An edge a registry stated must not be indistinguish-
            # able from one a scraper guessed — and a link an investigator
            # drew by hand ("manual") must not read as either.
            source=x.source or "pivot", data={},
        ))

    job_id = f"commit-{uuid.uuid4()}"
    entities_count, edges_count = len(entities), len(edges)
    try:
        resp = await push_to_agent(
            tenant, "/api/ingest",
            _agent_payload(case_id, job_id, entities, edges, case=case))
        if isinstance(resp, dict):
            entities_count = resp.get("entities_count", resp.get("entities", entities_count))
            edges_count = resp.get("edges_count", resp.get("edges", edges_count))
    except _LOCAL_FALLBACK_ERRORS as e:
        log.info("commit: no agent (%s) — persisting locally", e)
        await _persist_local(entities, edges)
    except _AGENT_AUTH_ERRORS as e:
        log.error("commit: agent auth failure for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))

    await audit.log_action(tenant, "entities.commit", user=user,
                           target_type="case", target_id=case_id,
                           details={"entities": entities_count, "edges": edges_count},
                           ip=audit.client_ip(request))
    return {"committed_entities": entities_count, "committed_edges": edges_count}


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt else None


def _entity_sig(e: Entity) -> tuple:
    """Everything about an entity that can still change during a search.

    Deliberately NOT label/entity_type/data: those are identity, the agent's
    ingest does not overwrite them, and including them would only cause
    pointless re-sends.
    """
    return (
        tuple(e.corroborated_by or ()),
        e.admiralty,
        e.url,
        _iso(e.observed_at),
        float(e.confidence or 0),
    )


def _edge_sig(x: Edge) -> tuple:
    return (tuple(x.corroborated_by or ()), x.source, float(x.confidence or 0))


class _CoalescedRunner:
    """Run an async callable at most once at a time; overlapping triggers
    collapse into exactly one follow-up run.

    Why this exists: the incremental flush is triggered per finished tool, and
    up to 70 tools can finish while one flush is still talking to the customer
    agent. Running them all would serialize 70 graph rebuilds and 70 round
    trips; dropping the overlapping ones would leave the last tool's findings
    unpushed until the final flush. Coalescing keeps the freshness without the
    cost: the number of flushes follows how fast the agent answers, and the
    state pushed is always the newest one.
    """

    def __init__(self, fn: "Callable[[], Awaitable[None]]") -> None:
        self._fn = fn
        self._dirty = False
        self._active = False
        self._lock = asyncio.Lock()
        self.runs = 0  # for tests and logging

    async def trigger(self) -> None:
        async with self._lock:
            if self._active:
                self._dirty = True
                return
            self._active = True
        try:
            while True:
                self.runs += 1
                await self._fn()
                async with self._lock:
                    if not self._dirty:
                        self._active = False
                        return
                    self._dirty = False
        except BaseException:
            # Never leave the flag set: one failed push must not stop every
            # later tool from ever flushing again.
            async with self._lock:
                self._active = False
            raise


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Drop the timezone after converting to UTC.

    The framework's timestamp columns are naive; writing a tz-aware value
    makes asyncpg raise a DataError and the job hangs on "running". A client
    is free to send an offset, so normalise here rather than trusting it.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _merge_arrays(stored, incoming):
    """SQL expression: union of two text[] columns, deduped and sorted.

    Corroboration is the one field that must ACCUMULATE across searches
    rather than gap-fill. A tool confirming an existing node three months
    later is precisely the signal worth keeping, and neither `DO NOTHING`
    (loses the new tool) nor plain overwrite (loses the old ones) preserves
    it. Sorted so a re-push of unchanged data produces an identical row.
    """
    from sqlalchemy import distinct, func, literal_column
    from sqlalchemy import select as sa_select

    empty = literal_column("'{}'::text[]")
    combined = func.coalesce(stored, empty).op("||")(func.coalesce(incoming, empty))
    element = func.unnest(combined).column_valued("tool")
    return sa_select(
        func.array_agg(aggregate_order_by(distinct(element), element))
    ).scalar_subquery()


def _agent_payload(
    case_id: uuid.UUID,
    job_id: str,
    entities: list[Entity],
    edges: list[Edge],
    case: Case | None = None,
) -> dict[str, Any]:
    """The framework→agent wire format.

    This used to be narrower than BOTH data models: `url`, `observed_at`,
    `notes` and — for edges — `source` and `data` never made the crossing,
    so the customer's canonical store held less than either side could
    represent. Everything the agent can persist is sent here now.

    `case` carries the metadata the customer needs to make sense of their
    own data. Without it every case on the agent was titled `job <uuid>`.
    """
    payload: dict[str, Any] = {
        "case_id": str(case_id),
        "job_id": job_id,
        "entities": [
            {"id": str(e.id), "case_id": str(e.case_id), "entity_type": e.entity_type,
             "label": e.label, "data": e.data, "source": e.source,
             "confidence": float(e.confidence or 0),
             "url": e.url,
             "observed_at": _iso(e.observed_at),
             "notes": e.notes,
             "last_verified": _iso(e.last_verified),
             "corroborated_by": e.corroborated_by or [],
             "admiralty": e.admiralty}
            for e in entities
        ],
        "edges": [
            {"id": str(e.id), "case_id": str(e.case_id),
             "from_entity": str(e.from_entity), "to_entity": str(e.to_entity),
             "relation_type": e.relation_type,
             "confidence": float(e.confidence or 0),
             "source": e.source,
             "data": e.data or {},
             "corroborated_by": e.corroborated_by or []}
            for e in edges
        ],
    }
    if case is not None:
        payload["case"] = _case_metadata(case)
    return payload


def _case_metadata(case: Case) -> dict[str, Any]:
    """The subset of case metadata the customer's store mirrors.

    Deliberately not the whole row: `description`, `assigned_to` and the
    audit-ish fields stay framework-side for now. Number, title and status
    are what make a case identifiable without the operator — and `phase`
    joins them for the same reason: a customer left holding these cases
    should be able to see which were mid-collection and which were being
    written up, not just that they exist.
    """
    return {
        "case_number": case.case_number,
        "title": case.title,
        "status": case.status,
        "phase": getattr(case, "phase", None) or "new",
    }


async def _persist_local(entities: list[Entity], edges: list[Edge]) -> dict:
    """Local-DB fallback when no data agent is reachable.

    Idempotent (ON CONFLICT DO NOTHING on the id PK) and dangling-edge
    safe (skips edges whose endpoints are neither in this batch nor
    already stored), mirroring the customer agent's ingest. This lets the
    incremental per-module flush call it repeatedly without duplicate-key
    or foreign-key failures.

    Returns what it actually did — `{"entities", "edges", "skipped_edges"}`.
    It used to return None, which meant a caller could not tell a successful
    write from one where every edge was dropped as dangling, and at least one
    caller reported the size of its own request as the result.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from sqlalchemy import case, func, literal_column

    async with AsyncSessionLocal() as session:
        for e in entities:
            stmt = pg_insert(Entity).values(
                id=e.id, case_id=e.case_id, tenant=e.tenant,
                entity_type=e.entity_type, label=e.label, data=e.data or {},
                source=e.source, confidence=e.confidence,
                url=e.url, observed_at=e.observed_at, notes=e.notes,
                corroborated_by=e.corroborated_by, admiralty=e.admiralty,
            )
            # Mirrors the agent ingest: fill a missing citation, never
            # overwrite identity fields or investigator state. See
            # data-agent/app/routers/ingest.py for the full reasoning.
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "url": func.coalesce(Entity.url, stmt.excluded.url),
                        "observed_at": func.coalesce(
                            Entity.observed_at, stmt.excluded.observed_at),
                        # Corroboration ACCUMULATES across searches — a tool
                        # that confirms an existing node months later is
                        # exactly the signal worth keeping. Admiralty is
                        # recomputed from it, so the newer rating wins.
                        "corroborated_by": _merge_arrays(
                            Entity.corroborated_by, stmt.excluded.corroborated_by),
                        "admiralty": func.coalesce(
                            stmt.excluded.admiralty, Entity.admiralty),
                    # `data` is otherwise never touched on conflict — the
                    # placeholder-freeze logic depends on that. The one
                    # exception is the `root` marker: it was introduced after
                    # these rows were written, and without merging it a
                    # re-scan could never repair an existing case, so its
                    # exports would keep losing every edge that starts at the
                    # search term. Only that single key is merged in.
                    "data": case(
                        (stmt.excluded.data.has_key("root"),
                         Entity.data.op("||")(literal_column(
                             '\'{"root": true}\'::jsonb'))),
                        else_=Entity.data,
                    ),
                    },
                )
            )
        await session.flush()

        case_ids = {e.case_id for e in entities} | {x.case_id for x in edges}
        valid: set[uuid.UUID] = {e.id for e in entities}
        for cid in case_ids:
            existing = (await session.execute(
                select(Entity.id).where(Entity.case_id == cid)
            )).scalars().all()
            valid.update(existing)

        skipped_dangling = 0
        for x in edges:
            if x.from_entity not in valid or x.to_entity not in valid:
                # Dangling — skip so it can't roll back the batch. The COUNT
                # is returned now instead of being swallowed: for a caller
                # that sends only edges (AI apply), every endpoint lives on
                # the agent and none of them are here, so this branch drops
                # the whole batch. Silently returning None from that made
                # `{"applied": 1}` a true statement about the request and a
                # false one about the world.
                skipped_dangling += 1
                continue
            estmt = pg_insert(Edge).values(
                id=x.id, case_id=x.case_id, tenant=x.tenant,
                from_entity=x.from_entity, to_entity=x.to_entity,
                relation_type=x.relation_type, confidence=x.confidence,
                source=x.source, data=x.data or {},
                corroborated_by=x.corroborated_by,
            )
            await session.execute(
                estmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "source": func.coalesce(Edge.source, estmt.excluded.source),
                        "corroborated_by": _merge_arrays(
                            Edge.corroborated_by, estmt.excluded.corroborated_by),
                    },
                )
            )
        await session.commit()
    return {"entities": len(entities),
            "edges": len(edges) - skipped_dangling,
            "skipped_edges": skipped_dangling}


async def _run_search(
    job_id: uuid.UUID, case_id: uuid.UUID, tenant: str,
    query: str, query_type: str, modules: list[str],
    queries: list[str] | None = None,
    tools: list[str] | None = None,
) -> None:
    # `queries` is the faceted fan-out: the base query plus one narrowed
    # variant per facet. They run SEQUENTIALLY on purpose — firing 5 variants
    # x 4 tools in parallel is a reliable way to get rate-limited out of the
    # sources (DuckDuckGo already blocks us at moderate volume).
    runs = queries or [query]
    log.info("starting search job=%s case=%s modules=%s runs=%d",
             job_id, case_id, modules, len(runs))
    push_outcome = "skipped"

    # Load the case once so every push carries its metadata. The background
    # task has no request-scoped session, hence the fresh one here. A missing
    # case is not fatal — the ingest still creates the FK stub — so this
    # never aborts a search.
    async with AsyncSessionLocal() as session:
        case = await session.scalar(select(Case).where(Case.id == case_id))
    if case is None:
        log.warning("job=%s: case %s not found — pushing without metadata",
                    job_id, case_id)
    current_query = query   # which variant on_progress entries belong to

    # Live tool-progress state. Each on_progress invocation merges into
    # the dict (keyed by (query,module,tool)) and flushes a serialized list
    # to the SearchJob row, so the frontend's polling loop can render
    # a per-tool live status table without WebSockets.
    # The query is part of the key: without it a faceted run would overwrite
    # the previous variant's row and the progress bar would stall at 1/N.
    progress: dict[tuple[str, str, str], dict[str, Any]] = {}
    progress_lock = asyncio.Lock()

    async def update_progress(**kw: Any) -> None:
        key = (current_query, kw["module"], kw["tool"])
        async with progress_lock:
            progress[key] = {
                "module": kw["module"],
                "tool": kw["tool"],
                "status": kw["status"],
                "findings": kw.get("findings", 0),
                "edges": kw.get("edges", 0),
                "errors": kw.get("errors", []),
                "notes": kw.get("notes", []),
                "duration_seconds": kw.get("duration", 0.0),
                # Only set when more than one variant ran, so a plain search
                # keeps exactly the shape the frontend has always seen.
                **({"query": current_query} if len(runs) > 1 else {}),
            }
            snapshot = list(progress.values())
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SearchJob).where(SearchJob.id == job_id)
                # last_progress_at is the reaper's heartbeat: as long as tools
                # keep reporting, the job is alive. Naive UTC on purpose — the
                # column is naive, and a tz-aware value makes asyncpg reject
                # the write and the job hang on "running" forever.
                .values(tool_progress=snapshot, last_progress_at=datetime.utcnow())
            )
            await session.commit()

    # Incremental persistence. As each MODULE finishes, we rebuild the
    # full graph from everything gathered so far and push only the NEW
    # (not-yet-sent) real entities + resolvable edges, so the case graph
    # fills in progressively instead of appearing all at once at the end.
    #   * transient virtual endpoints (created by build_graph for an edge
    #     whose target no module has produced YET) are held back until the
    #     final flush, EXCEPT the root-query node (which never becomes a
    #     real finding and anchors most edges) — this avoids ON CONFLICT
    #     DO NOTHING freezing a placeholder in place of the real node.
    #   * edges whose endpoints aren't sent yet are skipped and retried on
    #     a later flush (agent + local both drop dangling edges), so a
    #     cross-module edge lands once its endpoint materialises.
    #   * a row is re-sent when what we know about it CHANGED. Tracking only
    #     the ids that had been sent meant the first tool to report an entity
    #     froze it: a second tool confirming the same finding later produced a
    #     `corroborated_by` the agent never saw, because the id was already in
    #     the sent set. That silently destroyed the strongest signal the system
    #     produces — and it is why the flush had to wait for a whole module,
    #     which in turn is why a fast tool's findings waited for the module's
    #     slowest one. Re-sending is safe: the agent's ingest gap-fills with
    #     COALESCE, merges `corroborated_by`, and leaves identity fields and
    #     investigator state alone.
    all_results: list[dict[str, Any]] = []
    results_lock = asyncio.Lock()
    persist_lock = asyncio.Lock()
    # id -> signature of what was last pushed for that row.
    sent_entities: dict[uuid.UUID, tuple] = {}
    sent_edges: dict[uuid.UUID, tuple] = {}
    counts = {"entities": 0, "edges": 0}

    async def _flush(final: bool) -> None:
        nonlocal push_outcome
        async with persist_lock:
            async with results_lock:
                snapshot = list(all_results)
            entities, edges = build_graph(
                snapshot, case_id, tenant, str(job_id),
                root_query=query, root_query_type=query_type,
                reliability=tool_reliability(),
            )
            # Which entities are eligible to send this round. Virtual
            # placeholders are held back until the final flush: they share the
            # deterministic id of the real node they stand in for, and the
            # agent ingests ON CONFLICT DO NOTHING — so sending a placeholder
            # early permanently freezes a confidence-0.5 shell in place of the
            # real finding that arrives later.
            # The root node is NOT exempt from that hold-back. It used to be,
            # to surface the search term immediately, but that is exactly how
            # a multi-module search lost its payload: a fast module triggered
            # a flush, the placeholder root went out, and the slower module's
            # real finding for the same selector was then dropped by the
            # conflict clause. When a tool does return the searched selector,
            # that finding is real, not virtual, and still ships immediately.
            def _eligible(e: Entity) -> bool:
                return final or not (e.data or {}).get("virtual")
            eligible = [e for e in entities if _eligible(e)]
            eligible_ids = {e.id for e in eligible}
            sendable_ids = eligible_ids | set(sent_entities)

            # New OR changed. `!=` against the stored signature covers both:
            # an id we have never seen has no entry, and one whose
            # corroboration/rating/citation grew has a different one.
            new_entities = [
                e for e in eligible if sent_entities.get(e.id) != _entity_sig(e)
            ]
            new_edges = [
                x for x in edges
                if sent_edges.get(x.id) != _edge_sig(x)
                and x.from_entity in sendable_ids and x.to_entity in sendable_ids
            ]
            if not new_entities and not new_edges and not final:
                return

            try:
                await push_to_agent(
                    tenant, "/api/ingest",
                    _agent_payload(case_id, str(job_id), new_entities, new_edges,
                                   case=case))
                push_outcome = "pushed"
            except _LOCAL_FALLBACK_ERRORS as e:
                log.info("incremental push skipped (%s) — persisting locally", e)
                await _persist_local(new_entities, new_edges)
                push_outcome = "local-fallback"
            # An auth failure is NOT caught here on purpose: it propagates out
            # of _run_search, which marks the job failed with the message. The
            # alternative — writing the findings into the framework's own DB —
            # would move the tenant's investigation data out of their store
            # because of a key mismatch, which is precisely what must not
            # happen silently.

            for e in new_entities:
                sent_entities[e.id] = _entity_sig(e)
            for x in new_edges:
                sent_edges[x.id] = _edge_sig(x)
            # Distinct rows, not pushes — a re-sent row must not inflate the
            # count the investigator reads as "how much did this search find".
            counts["entities"] = len(sent_entities)
            counts["edges"] = len(sent_edges)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(SearchJob).where(SearchJob.id == job_id).values(
                        entities_count=counts["entities"], edges_count=counts["edges"])
                )
                await session.commit()

    # Per-tool flushing, COALESCED.
    #
    # Per module, a fast tool's findings waited for its module's slowest one:
    # in `alias`, sherlock/whatsmyname/user_scanner/linkook are all done long
    # before handle_sweep (~600 probes, ~100 s), and the case graph showed
    # nothing until then. Per tool without coalescing would be the opposite
    # mistake — up to 70 full graph rebuilds and 70 agent round trips
    # serialized behind persist_lock, which on a remote customer agent costs
    # more time than it saves.
    #
    # So: a tool that finishes while a flush is in flight only marks the state
    # dirty, and exactly one more flush runs when the current one returns. The
    # number of flushes follows how fast the agent answers instead of how many
    # tools there are, and the newest state always gets pushed.
    flusher = _CoalescedRunner(lambda: _flush(final=False))

    async def on_tool_complete(module: str, tool: str, result: dict[str, Any]) -> None:
        async with results_lock:
            all_results.append(result)
        await flusher.trigger()

    try:
        results: list[dict[str, Any]] = []
        for variant in runs:
            current_query = variant
            variant_results = await run_modules(
                variant, query_type, modules, str(job_id),
                on_progress=update_progress,
                on_tool_complete=on_tool_complete,
                tools=tools,
            )
            results.extend(variant_results)

        # Tie each narrowed variant back to the base term, so the graph shows
        # WHICH facet produced a hit instead of a flat pile under one node.
        # The runners already emit `keyword:<variant>` endpoints, so those
        # nodes exist; this only adds the base -> variant edges.
        if len(runs) > 1:
            async with results_lock:
                all_results.append({
                    "tool": "<facets>",
                    "findings": [],
                    "edges": [{
                        "from_entity": f"{query_type}:{query}",
                        "to_entity": f"{query_type}:{v}",
                        "relation": "narrowed_by",
                        "confidence": 1.0,
                    } for v in runs[1:]],
                    "errors": [],
                    "notes": [],
                })

        # Final flush: emit any held-back virtual endpoints + edges that
        # only became resolvable once every module was in.
        async with results_lock:
            # run_modules' per-module hook already appended everything, but
            # guard against a module that produced no completion event.
            # (With facets, all_results also holds the synthetic <facets>
            # entry, so compare against the module results only.)
            module_only = [r for r in all_results if r.get("tool") != "<facets>"]
            if len(module_only) < len(results):
                facet_entries = [r for r in all_results if r.get("tool") == "<facets>"]
                all_results.clear()
                all_results.extend(results)
                all_results.extend(facet_entries)
        await _flush(final=True)

        module_errors: list[str] = []
        for r in results:
            module_errors.extend(r.get("errors", []) or [])

        # Job status
        if not sent_entities and module_errors:
            final_status = "failed"
        elif module_errors:
            final_status = "partial"
        else:
            final_status = "completed"

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SearchJob).where(SearchJob.id == job_id).values(
                    status=final_status,
                    completed_at=datetime.utcnow(),
                    error_message="; ".join(module_errors[:5]) or None,
                    entities_count=counts["entities"],
                    edges_count=counts["edges"],
                )
            )
            await session.commit()
        log.info("job=%s done: status=%s entities=%d edges=%d push=%s",
                 job_id, final_status, counts["entities"], counts["edges"], push_outcome)
    except asyncio.CancelledError:
        # The investigator pressed stop (see `cancel_search`). This is NOT a
        # failure and must not be recorded as one: a case file has to be able
        # to tell "we looked and the tools broke" from "we stopped looking".
        #
        # `cancelled` is terminal, so the frontend's poll stops here rather
        # than hanging on `running` until the reaper times the job out ~20
        # minutes later.
        #
        # The counts are whatever the per-tool flushes already persisted —
        # those findings are in the case and stay there. The await below is
        # safe inside the handler: the task is already cancelling, and a new
        # session's short UPDATE is not itself a cancellation point that can
        # be interrupted again.
        log.info("job=%s cancelled by user after %d entities / %d edges",
                 job_id, counts["entities"], counts["edges"])
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SearchJob).where(SearchJob.id == job_id).values(
                    status="cancelled",
                    completed_at=datetime.utcnow(),
                    entities_count=counts["entities"],
                    edges_count=counts["edges"],
                    error_message="cancelled by user",
                )
            )
            await session.commit()
        # Re-raised on purpose: swallowing a CancelledError leaves the task
        # looking like it completed normally and breaks any caller that is
        # waiting for the cancellation to land.
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("job=%s failed", job_id)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SearchJob).where(SearchJob.id == job_id).values(
                    status="failed", error_message=str(e)[:500],
                    completed_at=datetime.utcnow(),
                )
            )
            await session.commit()
