"""
News / RSS browsing for analysts.

Separate from the case search on purpose. `/search` answers "put this
selector into a case graph"; this answers "let me look through the
sources first". An analyst reads headlines, follows a link, and only then
decides whether it belongs in a case — forcing a case assignment before
that turns exploration into bookkeeping.

Articles are served from a background-harvested cache in the framework
DB (see app.services.news_store), not fetched live per search — that is
what stops the authority feeds from rate-limiting us. The search itself
persists nothing per request; committing a hit to a case is the ordinary
orchestrated search, which the UI offers as a follow-up.

Read-only by design: the feed LIST is maintained by the operator in the
Owner console (`/platform/news-feeds`, platform_admin only). Analysts see
which sources exist so they can judge coverage — an absent hit means
"not in these feeds", and that is only interpretable if you know the
feeds.
"""
from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.services import api_keys, digest as digest_svc, news_feeds, news_store

log = logging.getLogger("osint.news")

router = APIRouter(tags=["news"])


class NewsSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    # Narrowing terms, same idea as the search facets: each is appended to
    # the query for an additional pass over the same feeds.
    facets: list[str] = Field(default_factory=list, max_length=5)
    max_age_days: int | None = None


@router.get("/digest")
async def daily_digest(
    hours: int = 24,
    kev_days: int = 14,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """The morning situation report.

    Public sources only — press, CISA KEV, ransomware leak-site postings.
    Nothing here touches case data, which is why it can live framework-side
    like the news cache without moving the sovereignty boundary.

    Ordered by SOURCE KIND rather than recency: the cache holds roughly 46
    authority items against 10 907 media items per week, so sorting by time
    would bury every official statement under press churn.
    """
    hours = max(1, min(int(hours), 168))
    kev_days = max(1, min(int(kev_days), 90))
    try:
        keys = await api_keys.load_keys()
    except Exception:  # noqa: BLE001
        keys = {}
    return await digest_svc.build(
        db, hours=hours, kev_days=kev_days,
        api_key=keys.get("RANSOMWARE_LIVE_API_KEY", ""))


@router.get("/news/sources")
async def list_sources(user: dict = Depends(get_current_user)):
    """Which feeds a news search covers. Read-only for analysts."""
    feeds = await news_feeds.get_feeds()
    return {
        # Never expose whether a feed is operator-configured or a module
        # default — from the analyst's side the only relevant question is
        # what gets searched.
        "sources": [
            {"name": f["name"], "kind": f["kind"], "lang": f["lang"],
             "url": f["url"], "enabled": f["enabled"]}
            for f in feeds if f.get("enabled", True)
        ],
        "configured": bool(feeds),
    }


@router.post("/news/search")
async def search_news(payload: NewsSearchRequest,
                      user: dict = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Full-text search over the harvested news cache. Articles, not nodes.

    Reads the framework DB (filled by the background harvester) so a search
    is instant and never live-hits an authority feed — which is what got us
    rate-limited before. Only when the cache is still empty (a fresh install
    before the first harvest tick) does it fall back to the live path, so
    day one still searches something.
    """
    cfg = await news_feeds.get_settings()
    max_age = payload.max_age_days or cfg.get("max_age_days")

    total = await news_store.count_articles(db)
    if total > 0:
        return await news_store.search(
            db, payload.query, payload.facets, max_age, limit=cfg["max_results"])

    log.info("news cache empty — falling back to live search until first harvest")
    return await _live_search(payload)


async def _live_search(payload: NewsSearchRequest):
    """Legacy live path: fetch feeds through module-news per request.
    Kept only as the cold-start fallback for an unharvested cache."""
    feeds = await news_feeds.get_feeds()
    cfg = await news_feeds.get_settings()
    feeds = news_feeds.apply_placeholders(feeds, cfg)
    queries = [payload.query.strip()]
    for f in payload.facets[:5]:
        f = (f or "").strip()
        if f and f"{payload.query.strip()} {f}" not in queries:
            queries.append(f"{payload.query.strip()} {f}")

    options: dict = {"credentials": {}}
    if feeds:
        options["feeds"] = feeds
    options["max_results"] = cfg["max_results"]
    if payload.max_age_days or cfg.get("max_age_days"):
        options["max_age_days"] = payload.max_age_days or cfg["max_age_days"]

    articles: dict[str, dict] = {}
    notes: list[str] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=180) as client:
        for q in queries:
            try:
                r = await client.post(
                    f"{settings.module_news_url}/run",
                    json={"job_id": f"news-{uuid.uuid4()}", "tool": "news_search",
                          "query": q, "query_type": "keyword", "options": options},
                )
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPError as e:
                log.warning("news module unreachable: %s", e)
                raise HTTPException(
                    status_code=502,
                    detail="News module unreachable — try again shortly.") from e

            for note in data.get("notes") or []:
                if note not in notes:
                    notes.append(note)
            for err in data.get("errors") or []:
                if err not in errors:
                    errors.append(err)

            for f in data.get("findings") or []:
                d = f.get("data") or {}
                # Same article can surface under several narrowing terms;
                # keep one entry and record which terms found it, so the
                # analyst can see WHY it matched.
                key = d.get("url") or f.get("label")
                if key in articles:
                    if q not in articles[key]["matched"]:
                        articles[key]["matched"].append(q)
                    continue
                articles[key] = {
                    "title": d.get("title") or f.get("label"),
                    "url": d.get("url"),
                    "summary": d.get("summary"),
                    # The passage the term appears in — what the analyst
                    # actually needs to judge a hit at a glance.
                    "match_context": d.get("match_context"),
                    "matched_terms": d.get("matched_terms") or [],
                    "published": d.get("published"),
                    "source_name": d.get("source_name"),
                    "source_kind": d.get("source_kind"),
                    "source_lang": d.get("source_lang"),
                    "matched": [q],
                }

    out = sorted(articles.values(),
                 key=lambda a: a.get("published") or "", reverse=True)
    return {"query": payload.query, "queries": queries, "count": len(out),
            "articles": out, "notes": notes, "errors": errors}
