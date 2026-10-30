"""AI case-linking — the licensable "AI function" (KI-Verknüpfung).

Button-triggered, NEVER automatic. Gated by the tenant's `ai_enabled`
license flag (opt-in). Fetches the case graph, strips raw credentials
(data-sparsity — the sovereign boundary), and hands the structure to the
editable n8n `ai-link` workflow (prompt → Gemini). Returns SUGGESTIONS
only; nothing is persisted — the analyst commits chosen items via the
normal /cases/{id}/entities/commit flow.

⚠️ With the Gemini provider, case data leaves the sovereign boundary — that
is why the feature is per-customer licensed + consented; a local model is
the sovereign alternative (Phase 3).
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import uuid
from typing import Any

import httpx
import redis.asyncio as redis_asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models.case import Case
from app.models.entity import Edge, Entity
from app.models.news import NewsArticle
from app.routers.agent_proxy import _local_graph, _try_remote_or_fallback
from app.routers.search import _agent_payload, _persist_local
from app.services import ai_settings, ai_usage, api_keys, audit, news_feeds, news_store
from app.services.agent_client import (
    AgentAuthError, AgentRejected, AgentUnavailable, push_to_agent)
from app.services.case_access import assert_case_visible
from app.services.graph_builder import _NS, _canon, _edge_id, _entity_id
from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

log = logging.getLogger("osint.ai")
router = APIRouter(tags=["ai"])

# Substrings of `data` keys whose raw values must NEVER be sent to the LLM
# (cleartext credentials, cookies, tokens, per-hit login lists, hashes …).
# Only graph structure + labels + benign metadata leave the boundary.
#
# `hash` was in this list from the start, and it never matched anything: the
# key the leakcheck runner actually writes is `sha256`. So every
# password_fingerprint finding handed Gemini the full unsalted digest
# alongside `length` — and an unsalted SHA-256 with a known length of 4 or 8
# characters is the password. The intent
# was right and the string was wrong, which is the kind of gap that survives
# review precisely because the code looks like it handles the case.
#
# Algorithm names are spelled out rather than matched on a bare "sha", which
# would also swallow innocent keys like `shared_with` or `shape`.
_SENSITIVE = ("password", "passwort", "plaintext", "cleartext", "secret",
              "cookie", "token", "credential", "logins", "hash", "banner",
              "sha1", "sha256", "sha384", "sha512", "md5", "ntlm",
              "bcrypt", "scrypt", "argon2", "pbkdf", "digest", "checksum",
              "apikey", "api_key", "private_key", "passphrase", "otp",
              "session_id", "auth")


def _is_sensitive(key) -> bool:
    k = str(key).lower()
    return any(s in k for s in _SENSITIVE)

# Bounds on the per-entity `data` we hand the LLM. Real findings (GHunt
# profiles, Shodan service/banner lists, Telegram history …) carry large
# nested blobs; sending them verbatim for 150 entities balloons the prompt
# so much that Gemini's generateContent can exceed the 300 s HTTP timeout
# → the "AI job failed: ReadTimeout" the analyst saw.
#
# The trim is IDENTIFIER-PRESERVING: it recurses into nested structures and
# KEEPS short scalar values (a buried e-mail / phone / handle / id is
# exactly the kind of cross-entity link the AI is meant to spot), while
# collapsing only genuine bulk — long banners/prose (truncated) and very
# large lists (summarised). A hard per-entity size budget is the final
# safety net so a pathological entity still can't blow up the prompt.
_MAX_STR = 200        # truncate individual long string values
_MAX_LIST = 8         # keep at most N list items, summarise the rest
_MAX_KEYS = 24        # keep at most N keys per dict level
_MAX_DEPTH = 3        # recurse this deep before summarising
_MAX_ENTITY_DATA = 1400   # per-entity serialized-data char budget (safety net)


def _trim_value(v, depth: int = 0):
    if isinstance(v, str):
        return v if len(v) <= _MAX_STR else v[:_MAX_STR] + "…"
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if depth >= _MAX_DEPTH:  # too deep to keep expanding → summarise
        if isinstance(v, list):
            return f"[{len(v)} items]"
        if isinstance(v, dict):
            return f"{{{len(v)} fields}}"
        return str(v)[:_MAX_STR]
    if isinstance(v, list):
        trimmed = [_trim_value(x, depth + 1) for x in v[:_MAX_LIST]]
        if len(v) > _MAX_LIST:
            trimmed.append(f"…(+{len(v) - _MAX_LIST} more)")
        return trimmed
    if isinstance(v, dict):
        out = {}
        for i, (k, val) in enumerate(v.items()):
            if i >= _MAX_KEYS:
                out["…"] = f"+{len(v) - _MAX_KEYS} more fields"
                break
            # The secret filter has to recurse for the same reason this
            # trimmer does. It used to run once, over the top level only,
            # while the trimmer went three levels deep *specifically to
            # preserve short scalar values* — so a nested {"account":
            # {"password": "hunter2"}} was carried out of the boundary by
            # the very code that was meant to be careful with it. No runner
            # writes that shape today; the next one would not have been told.
            if _is_sensitive(k):
                continue
            out[k] = _trim_value(val, depth + 1)
        return out
    return str(v)[:_MAX_STR]


def _budget_collapse(data: dict) -> dict:
    """Safety net: if an entity's trimmed data is still over budget, drop
    its nested (list/dict) fields — which carry the bulk — keeping the
    scalar fields (the likely identifiers). Bounds worst-case prompt size
    without losing the flat linking signals."""
    if len(_json.dumps(data, ensure_ascii=False)) <= _MAX_ENTITY_DATA:
        return data
    scalars = {k: v for k, v in data.items()
               if isinstance(v, (str, int, float, bool)) or v is None}
    scalars["_note"] = "nested fields omitted (size)"
    return scalars


def _sanitize(entities: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in entities or []:
        data = e.get("data") or {}
        clean = {k: v for k, v in data.items() if not _is_sensitive(k)}
        trimmed = _trim_value(clean)
        if isinstance(trimmed, dict):
            trimmed = _budget_collapse(trimmed)
        out.append({"id": e.get("id"), "entity_type": e.get("entity_type"),
                    "label": e.get("label"), "data": trimmed})
    return out


# Case checks go through services/case_access.assert_case_visible.


async def _ai_enabled(tenant: str) -> bool:
    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/ai-enabled"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
            r.raise_for_status()
            return bool((r.json() or {}).get("ai_enabled"))
    except Exception:  # noqa: BLE001 — unknown/unreachable → not licensed (deny)
        return False


# ── async job store (Redis) ─────────────────────────────────────────
# The AI call can exceed Cloudflare's 100s / nginx's 60s limit on a big
# case, so /ai-link is async: POST starts a background job + returns a job
# id; the frontend polls /ai-link/{job_id}. Job state lives in Redis so it
# is shared across the (2) uvicorn workers — an in-memory dict would only be
# visible to the worker that created it (POST worker A, GET worker B → 404).
_JOB_TTL = 900       # seconds — job result available for 15 min

_TASKS: set = set()  # holds background-job refs so they aren't GC'd
_redis = None


def _r():
    global _redis
    if _redis is None:
        _redis = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def _set_job(job_id: str, obj: dict) -> None:
    """Write job state, carrying the ownership fields forward.

    The runners overwrite the whole record when they finish (`{"status":
    "done", "suggestions": …}`). If `tenant`/`case_id` were only set at
    creation they would be gone by the time the result exists — and the
    ownership check would then reject the owner. Preserving them here rather
    than at each call site means a new runner cannot forget.
    """
    if "tenant" not in obj:
        prev = await _get_job(job_id) or {}
        for k in ("tenant", "case_id"):
            if k in prev:
                obj = {**obj, k: prev[k]}
    await _r().set(f"ai:job:{job_id}", _json.dumps(obj), ex=_JOB_TTL)


async def _get_job(job_id: str) -> dict | None:
    v = await _r().get(f"ai:job:{job_id}")
    return _json.loads(v) if v else None


async def _owned_job(job_id: str, tenant: str,
                     case_id: uuid.UUID | None = None) -> dict:
    """Fetch a job, or 404 — and treat "not yours" as "not found".

    The status endpoints used to look the job up by id alone. The id sits in
    the path of `GET /cases/{case_id}/ai-link/{job_id}`, and the case_id was
    read, routed on, and then never compared to anything: passing a wholly
    unrelated UUID returned the job with HTTP 200. The body carries case
    content — entity labels and the model's proposed links.

    A uuid4 is hard to guess, and that is worth something, but it is
    secrecy, not authorisation: job ids travel in browser history, proxy
    logs and pasted screenshots. So the owner is now recorded when the job
    starts and checked when it is read.

    The 404 (rather than 403) is deliberate: a distinguishable "exists but
    not yours" would confirm the id to whoever tried it.
    """
    job = await _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404,
                            detail="AI job not found (it may have expired).")
    if job.get("tenant") != tenant:
        raise HTTPException(status_code=404,
                            detail="AI job not found (it may have expired).")
    if case_id is not None and job.get("case_id") not in (None, str(case_id)):
        raise HTTPException(status_code=404,
                            detail="AI job not found (it may have expired).")
    return {k: v for k, v in job.items() if k not in ("tenant", "case_id")}


async def _run_ai_job(job_id: str, case_id: uuid.UUID, tenant: str,
                      user: dict) -> None:
    try:
        async with AsyncSessionLocal() as db:
            graph = await _try_remote_or_fallback(
                tenant, f"/api/cases/{case_id}/graph",
                lambda: _local_graph(db, tenant, case_id),
            )
        ents = graph.get("entities", []) or []
        # Prefer relevant entities, then cap — bounds prompt size + latency.
        # The cap is operator-tunable (Owner console → Settings → AI).
        cap = await ai_settings.get_max_entities()
        ents.sort(key=lambda e: 0 if e.get("is_relevant") else 1)
        kept = ents[:cap]
        entities = _sanitize(kept)
        # Only edges BETWEEN entities we actually sent.
        #
        # Entities were capped and edges were not, so on a large case the
        # vast majority of edges referenced a node the model had never
        # been shown. That is not
        # merely wasted prompt: the model was asked to reason about a graph
        # most of whose edges point at nothing, and every one of them is an
        # invitation to invent the missing endpoint.
        sent_ids = {str(e.get("id")) for e in kept}
        all_edges = graph.get("edges", []) or []
        edges = [x for x in all_edges
                 if str(x.get("from_entity")) in sent_ids
                 and str(x.get("to_entity")) in sent_ids]
        if not entities:
            await _set_job(job_id, {"status": "error", "detail": "This case has no findings to link yet."})
            return

        keys = await api_keys.load_keys()
        provider = (settings.ai_provider or "gemini").strip().lower()
        payload = {
            "case_id": str(case_id), "entities": entities, "edges": edges,
            "provider": provider,
            "gemini_key": keys.get("GEMINI_API_KEY", ""),
            "model": settings.ai_gemini_model,
            "local_base_url": settings.ai_local_base_url,
            "local_model": settings.ai_local_model,
        }
        webhook = "ai-link-local" if provider == "local" else "ai-link"
        url = f"{settings.n8n_url}/webhook/{webhook}"
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(url, json=payload)
        if r.status_code == 404:
            await _set_job(job_id, {"status": "error", "detail": f"AI workflow not active — import + activate '{webhook}' in n8n."})
            return
        if r.status_code >= 400:
            await _set_job(job_id, {"status": "error", "detail": f"AI workflow error (HTTP {r.status_code})."})
            return
        try:
            suggestions = r.json()
        except ValueError:
            await _set_job(job_id, {"status": "error", "detail": "AI workflow returned non-JSON."})
            return
        # The n8n workflow surfaces a provider (Gemini) error as HTTP 200
        # with an {"error": ...} body so it never 500s. Detect that and
        # report a proper, actionable error instead of a "done" job whose
        # suggestions are really an error blob.
        if isinstance(suggestions, dict) and suggestions.get("error"):
            perr = str(suggestions.get("error"))
            low = perr.lower()
            if "quota" in low or "rate" in low or "429" in low or "exceeded" in low:
                detail = ("Gemini quota/rate-limit reached (the free tier allows "
                          "only a few requests per minute/day). Enable billing on "
                          "the Gemini API key for reliable use, or wait for the "
                          "quota to reset, then run it again.")
            elif "api key" in low or "unregistered" in low or "permission" in low or "403" in low:
                detail = ("Gemini rejected the API key. Re-check GEMINI_API_KEY in "
                          "the Owner console → Settings → AI.")
            else:
                detail = f"AI provider error: {perr[:240]}"
            await _set_job(job_id, {"status": "error", "detail": detail})
            return

        # Account the token usage Gemini reported (exact, via the workflow's
        # `_usage` passthrough); fall back to a coarse chars/4 estimate if an
        # older workflow didn't include it. Strip `_usage` before returning.
        usage = suggestions.pop("_usage", {}) if isinstance(suggestions, dict) else {}
        pt = int(usage.get("prompt", 0) or 0)
        ot = int(usage.get("output", 0) or 0)
        tt = int(usage.get("total", 0) or 0)
        if not tt:  # estimate ~4 chars/token when metadata is absent
            pt = pt or len(_json.dumps(payload)) // 4
            ot = ot or len(r.text) // 4
            tt = pt + ot
        from datetime import datetime, timezone
        await ai_usage.record(pt, ot, tt, settings.ai_gemini_model,
                              datetime.now(timezone.utc).isoformat())

        note = (f"Analysed the {cap} most relevant of {len(ents)} findings."
                if len(ents) > cap else None)
        await _set_job(job_id, {"status": "done", "entities_sent": len(entities),
                                "edges_sent": len(edges),
                                "suggestions": suggestions, "note": note})
        # Record how much actually crossed the boundary. The audit entry is
        # written when the button is pressed, before any of this is known,
        # so the amount is appended here — for the one action in the product
        # that deliberately sends case content to a third party, "which
        # provider" without "how much" is half the entry.
        await audit.log_action(tenant, "ai.link.sent", user=user,
                               target_type="case", target_id=case_id,
                               details={"entities": len(entities),
                                        "edges": len(edges),
                                        "of_findings": len(ents),
                                        "provider": provider,
                                        "model": settings.ai_gemini_model})
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
        log.warning("ai job %s timed out: %s", job_id, e)
        await _set_job(job_id, {
            "status": "error",
            "detail": "The AI model took too long to respond. Lower the "
                      "entity cap (Owner console → Settings → AI) or try a "
                      "smaller/more-focused case, then run it again.",
        })
    except Exception as e:  # noqa: BLE001
        log.warning("ai job %s failed: %s", job_id, e)
        await _set_job(job_id, {"status": "error", "detail": f"AI job failed: {type(e).__name__}"})


@router.post("/cases/{case_id}/ai-link", status_code=202)
async def ai_link(
    case_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Start an async AI-linking job (avoids the proxy/Cloudflare timeout on
    large cases). Returns a job id; poll GET /cases/{id}/ai-link/{job_id}."""
    # Checked before anything leaves: this path hands the case graph to an
    # external model, so the case must be checked first.
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    if not await _ai_enabled(tenant):
        raise HTTPException(status_code=403,
                            detail="The AI function is not licensed for this authority.")
    await audit.log_action(tenant, "ai.link", user=user,
                           target_type="case", target_id=case_id,
                           details={"provider": settings.ai_provider, "model": settings.ai_gemini_model},
                           ip=audit.client_ip(request))
    job_id = f"ai-{uuid.uuid4()}"
    await _set_job(job_id, {"status": "running", "tenant": tenant,
                            "case_id": str(case_id)})
    task = asyncio.create_task(_run_ai_job(job_id, case_id, tenant, user))
    _TASKS.add(task)            # hold a ref so the task isn't GC'd mid-run
    task.add_done_callback(_TASKS.discard)
    return {"job_id": job_id, "status": "running"}


@router.get("/cases/{case_id}/ai-link/{job_id}")
async def ai_link_status(
    case_id: uuid.UUID, job_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, case_id)
    return await _owned_job(job_id, user["tenant"], case_id)


class ApplyEdge(BaseModel):
    from_id: uuid.UUID
    to_id: uuid.UUID
    relation: str
    confidence: float | None = None


class ApplyRequest(BaseModel):
    edges: list[ApplyEdge]


@router.post("/cases/{case_id}/ai-link/apply")
async def ai_link_apply(
    case_id: uuid.UUID,
    payload: ApplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Persist AI-suggested edges into the case graph. Endpoints must already
    be case entities (they came from the AI's input). Deterministic uuid5 ids
    → re-applying the same suggestion is idempotent (agent ingest is
    ON CONFLICT DO NOTHING)."""
    tenant = user["tenant"]
    if not await _ai_enabled(tenant):
        raise HTTPException(status_code=403,
                            detail="The AI function is not licensed for this authority.")
    if not payload.edges:
        raise HTTPException(status_code=400, detail="No edges to apply.")

    await assert_case_visible(db, user, case_id)

    edges = [
        Edge(
            id=uuid.uuid5(_NS, f"{case_id}:{e.from_id}->{e.to_id}:{e.relation}"),
            case_id=case_id, tenant=tenant,
            from_entity=e.from_id, to_entity=e.to_id,
            # [:50] matches the column and what news_ai_apply already did.
            # Without it a longer model-proposed relation reached the agent,
            # violated varchar(50), and the resulting HTTP 500 was read as
            # "agent down" — see below for the rest of that story.
            relation_type=(e.relation or "related_to")[:50],
            confidence=e.confidence or 0.7,
            source="ai", data={},
        )
        for e in payload.edges
    ]
    job_id = f"ai-apply-{uuid.uuid4()}"
    stored = len(edges)
    try:
        await push_to_agent(tenant, "/api/ingest", _agent_payload(case_id, job_id, [], edges))
    except AgentRejected as e:
        # The store was reached and said no. Falling back would be pointless
        # here in a way worth spelling out: this endpoint sends ONLY edges,
        # and their endpoints exist solely on the agent, so the local path
        # drops every one of them as dangling and returns quietly. That is
        # how an accepted AI suggestion came back as `{"applied": 1}` while
        # existing in neither store.
        log.error("ai-apply: store refused the write for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    except (TenantNotConfigured, AgentUnavailable) as e:  # noqa: BLE001
        log.info("ai-apply: no agent (%s) — persisting locally", e)
        result = await _persist_local([], edges)
        stored = result["edges"]
        if not stored:
            # Report the truth rather than the size of the request.
            raise HTTPException(
                status_code=502,
                detail=("The customer's store is unreachable and these links "
                        "cannot be held here: their endpoints live only in "
                        "that store. Nothing was saved — try again once the "
                        "agent is reachable."),
            )
    except (AgentAuthError, AgentKeyUnavailable) as e:
        # Key rejected: storing locally would move the tenant's data out of
        # their sovereign store. Fail loudly instead.
        log.error("ai-apply: agent auth failure for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    await audit.log_action(tenant, "ai.apply", user=user,
                           target_type="case", target_id=case_id,
                           details={"edges": stored}, ip=audit.client_ip(request))
    return {"applied": stored}


# ── News AI analysis ─────────────────────────────────────────────────
# Reads the harvested news cache for a keyword, hands the (PUBLIC) articles
# to the editable n8n `ai-news` workflow (Gemini), and returns a summary +
# extracted entities + connections + case suggestions. Same ai_enabled
# license gate. Only public news content leaves the boundary — never case
# findings — so this is more sovereign than /ai-link. Nothing is persisted
# until the analyst commits a chosen subset via /news/ai-apply.

_NEWS_AI_MAX_ARTICLES = 40   # cap prompt size + latency
_NEWS_AI_SUMMARY = 500       # per-article summary chars sent to the model


class NewsAiRequest(BaseModel):
    query: str
    facets: list[str] = Field(default_factory=list)
    max_age_days: int | None = None


def _news_provider_error(perr: str) -> str:
    low = perr.lower()
    if "quota" in low or "rate" in low or "429" in low or "exceeded" in low:
        return ("Gemini quota/rate-limit reached (the free tier allows only a few "
                "requests per minute/day). Enable billing on the key or wait, then retry.")
    if "api key" in low or "unregistered" in low or "permission" in low or "403" in low:
        return ("Gemini rejected the API key. Check GEMINI_API_KEY in the Owner "
                "console → Settings → AI.")
    return f"AI provider error: {perr[:240]}"


async def _run_news_ai_job(job_id: str, tenant: str, query: str,
                           facets: list[str], max_age_days: int | None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            cfg = await news_feeds.get_settings()
            res = await news_store.search(
                db, query, facets, max_age_days or cfg.get("max_age_days"),
                limit=_NEWS_AI_MAX_ARTICLES)
        articles = res.get("articles") or []
        if not articles:
            await _set_job(job_id, {"status": "error",
                "detail": "No news found for this keyword — nothing to analyse. "
                          "Try a broader term, or harvest the feeds first."})
            return
        prompt_articles = [{
            "title": a.get("title"),
            "summary": (a.get("summary") or "")[:_NEWS_AI_SUMMARY],
            "source_name": a.get("source_name"),
            "source_kind": a.get("source_kind"),
            "published": a.get("published"),
            "url": a.get("url"),
        } for a in articles[:_NEWS_AI_MAX_ARTICLES]]

        keys = await api_keys.load_keys()
        payload = {"query": query, "articles": prompt_articles,
                   "gemini_key": keys.get("GEMINI_API_KEY", ""),
                   "model": settings.ai_gemini_model}
        url = f"{settings.n8n_url}/webhook/ai-news"
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(url, json=payload)
        if r.status_code == 404:
            await _set_job(job_id, {"status": "error",
                "detail": "AI news workflow not active — import + activate 'ai-news' in n8n."})
            return
        if r.status_code >= 400:
            await _set_job(job_id, {"status": "error",
                "detail": f"AI workflow error (HTTP {r.status_code})."})
            return
        try:
            data = r.json()
        except ValueError:
            await _set_job(job_id, {"status": "error",
                                    "detail": "AI workflow returned non-JSON."})
            return
        if isinstance(data, dict) and data.get("error"):
            await _set_job(job_id, {"status": "error",
                                    "detail": _news_provider_error(str(data.get("error")))})
            return

        usage = data.pop("_usage", {}) if isinstance(data, dict) else {}
        pt = int(usage.get("prompt", 0) or 0)
        ot = int(usage.get("output", 0) or 0)
        tt = int(usage.get("total", 0) or 0)
        if not tt:
            pt = pt or len(_json.dumps(payload)) // 4
            ot = ot or len(r.text) // 4
            tt = pt + ot
        from datetime import datetime, timezone
        await ai_usage.record(pt, ot, tt, settings.ai_gemini_model,
                              datetime.now(timezone.utc).isoformat())

        d = data if isinstance(data, dict) else {}
        await _set_job(job_id, {
            "status": "done",
            "query": query,
            "articles_analyzed": len(prompt_articles),
            "summary": d.get("summary"),
            "entities": d.get("entities") or [],
            "connections": d.get("connections") or [],
            "case_suggestions": d.get("case_suggestions") or [],
        })
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout):
        await _set_job(job_id, {"status": "error",
            "detail": "The AI model took too long to respond. Try a more focused "
                      "keyword and run it again."})
    except Exception as e:  # noqa: BLE001
        log.warning("news-ai job %s failed: %s", job_id, e)
        await _set_job(job_id, {"status": "error",
                                "detail": f"AI job failed: {type(e).__name__}"})


@router.post("/news/ai-analyze", status_code=202)
async def news_ai_analyze(payload: NewsAiRequest, request: Request,
                          user: dict = Depends(get_current_user)):
    """Start a news-AI analysis over the cached feeds for a keyword.
    Returns a job id; poll GET /news/ai-analyze/{job_id}."""
    tenant = user["tenant"]
    if not await _ai_enabled(tenant):
        raise HTTPException(status_code=403,
            detail="The AI function is not licensed for this authority.")
    q = (payload.query or "").strip()
    if len(q) < 2:
        raise HTTPException(status_code=400, detail="Query too short.")
    await audit.log_action(tenant, "ai.news_analyze", user=user,
                           target_type="news", target_id=None,
                           details={"query": q}, ip=audit.client_ip(request))
    job_id = f"ainews-{uuid.uuid4()}"
    await _set_job(job_id, {"status": "running", "tenant": tenant})
    task = asyncio.create_task(
        _run_news_ai_job(job_id, tenant, q, payload.facets[:5], payload.max_age_days))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {"job_id": job_id, "status": "running"}


@router.get("/news/ai-analyze/{job_id}")
async def news_ai_status(job_id: str, user: dict = Depends(get_current_user)):
    return await _owned_job(job_id, user["tenant"])


class NewsAiEntity(BaseModel):
    entity_type: str
    label: str
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    source_url: str | None = None


class NewsAiConnection(BaseModel):
    from_label: str
    to_label: str
    relation: str
    confidence: float | None = None


class NewsAiApplyRequest(BaseModel):
    case_id: uuid.UUID
    entities: list[NewsAiEntity] = Field(default_factory=list)
    connections: list[NewsAiConnection] = Field(default_factory=list)
    keyword: str | None = None
    link_keyword: bool = True


@router.post("/news/ai-apply")
async def news_ai_apply(payload: NewsAiApplyRequest, request: Request,
                        db: AsyncSession = Depends(get_db),
                        user: dict = Depends(get_current_user)):
    """Commit selected AI-extracted news entities + connections into a case.
    Reuses the canonical uuid5 id derivation + agent ingest, so results dedup
    against existing case nodes exactly like a normal search commit."""
    tenant = user["tenant"]
    if not await _ai_enabled(tenant):
        raise HTTPException(status_code=403,
            detail="The AI function is not licensed for this authority.")
    if not payload.entities:
        raise HTTPException(status_code=400, detail="No entities selected.")
    case_id = payload.case_id
    await assert_case_visible(db, user, case_id)

    entities: list[Entity] = []
    by_label: dict[str, uuid.UUID] = {}   # lowercased label → entity id

    def _register(etype: str, label: str, data: dict, conf, source: str,
                  url: str | None = None, observed_at=None):
        norm_type, clean_label, _key = _canon(etype, label)
        if not clean_label:
            return None
        eid = _entity_id(case_id, norm_type, clean_label)
        entities.append(Entity(
            id=eid, case_id=case_id, tenant=tenant,
            entity_type=norm_type[:30], label=clean_label[:255],
            data=data or {}, source=source, confidence=conf or 0.6,
            url=url, observed_at=observed_at,
        ))
        by_label[clean_label.lower()] = eid
        return eid

    # Provenance for news-derived findings. The article URL used to land in
    # `data["url"]` only, so these entities never filled the `url` column the
    # report and the exports cite from — a finding whose source was known but
    # unciteable. Same defect class as D1, a different code path.
    #
    # `observed_at` is the article's publication date, not the moment the
    # analyst pressed apply. It is read from the news cache rather than
    # trusted from the client, in one query. Already naive UTC there, which
    # is what the timestamp columns require.
    published_by_url: dict[str, object] = {}
    src_urls = {(e.source_url or "").strip() for e in payload.entities}
    src_urls.discard("")
    if src_urls:
        rows = await db.execute(
            select(NewsArticle.url, NewsArticle.published).where(
                NewsArticle.url.in_(src_urls),
                NewsArticle.published.is_not(None)))
        published_by_url = {u: p for u, p in rows.all() if u}

    # Optional keyword anchor so the extracted entities connect to the term.
    kw = (payload.keyword or "").strip()
    kw_id = None
    if payload.link_keyword and kw:
        kw_id = _register("keyword", kw, {"source": "ai_news"}, 0.9, "ai_news")

    for e in payload.entities:
        d = dict(e.data or {})
        d["source"] = "ai_news"
        src = (e.source_url or "").strip() or None
        if src:
            d.setdefault("url", src)
        _register(e.entity_type, e.label, d, e.confidence, "ai_news",
                  url=src,
                  observed_at=published_by_url.get(src) if src else None)

    edges: list[Edge] = []
    seen_edges: set = set()

    def _add_edge(from_id, to_id, relation: str, conf):
        if not from_id or not to_id or from_id == to_id:
            return
        eid = _edge_id(case_id, from_id, to_id, relation)
        if eid in seen_edges:
            return
        seen_edges.add(eid)
        edges.append(Edge(id=eid, case_id=case_id, tenant=tenant,
                          from_entity=from_id, to_entity=to_id,
                          relation_type=relation[:50], confidence=conf or 0.6,
                          source="ai_news", data={}))

    # keyword → each entity
    if kw_id:
        for e in payload.entities:
            _, clean_label, _ = _canon(e.entity_type, e.label)
            _add_edge(kw_id, by_label.get(clean_label.lower()),
                      "mentioned_in_news", 0.7)

    # AI-proposed connections, resolved by label (the term may be an endpoint)
    kw_low = kw.lower()
    for c in payload.connections:
        fl = (c.from_label or "").strip().lower()
        tl = (c.to_label or "").strip().lower()
        fid = by_label.get(fl) or (kw_id if fl == kw_low else None)
        tid = by_label.get(tl) or (kw_id if tl == kw_low else None)
        _add_edge(fid, tid, c.relation or "related_to", c.confidence)

    job_id = f"ainews-apply-{uuid.uuid4()}"
    stored_edges = len(edges)
    try:
        await push_to_agent(tenant, "/api/ingest",
                            _agent_payload(case_id, job_id, entities, edges))
    except AgentRejected as e:
        log.error("news-ai-apply: store refused the write for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    except (TenantNotConfigured, AgentUnavailable) as e:  # noqa: BLE001
        log.info("news-ai-apply: no agent (%s) — persisting locally", e)
        result = await _persist_local(entities, edges)
        # Same rule as ai-apply: report what was stored, not what was asked
        # for. Here the entities travel with their edges, so the fallback can
        # usually resolve them — but "usually" is not a thing to return.
        stored_edges = result["edges"]
    except (AgentAuthError, AgentKeyUnavailable) as e:
        log.error("news-ai-apply: agent auth failure for %s: %s", tenant, e)
        raise HTTPException(status_code=502, detail=str(e))
    await audit.log_action(tenant, "ai.news_apply", user=user,
                           target_type="case", target_id=case_id,
                           details={"entities": len(entities), "edges": stored_edges},
                           ip=audit.client_ip(request))
    return {"added_entities": len(entities), "added_edges": stored_edges}
