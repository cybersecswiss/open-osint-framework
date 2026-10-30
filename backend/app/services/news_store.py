"""
Persistent news cache — harvest + search.

Two jobs:
  * harvest_once() — the scheduled poller. Pulls the operator feed list,
    works out which feeds are DUE (authority/police/cyber hourly, the
    rest every 30 min), asks module-news to fetch+parse them, and upserts
    the entries into `news_articles` de-duplicated. Called from the
    lifespan loop in app.services.scheduler.
  * search() — the analyst read path. Substring-AND over the cached rows,
    identical semantics to the old live search (so German compounds still
    match) but off a trigram index and without ever touching a source.

Why a cache at all: the live path re-fetched every feed on every search
and got the framework rate-limited by admin.ch. The feed list stays
operator-global public data → framework DB, never the tenant agent.

All datetimes written here are NAIVE UTC (framework-DB convention).
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.news import NewsArticle, NewsFeedPollState
from app.services import news_feeds

log = logging.getLogger("osint.news_store")

# Feed kinds polled on the "authority" interval; everything else uses the
# "other" interval. The two intervals themselves are operator-tunable in
# the Owner console (news_feeds.get_harvest_settings); these are only the
# fallback if the setting can't be read.
AUTHORITY_KINDS = {"authority", "police", "cyber"}
_FALLBACK_AUTHORITY_MIN = 60
_FALLBACK_OTHER_MIN = 30

# Namespace for deterministic article ids — frozen, like graph_builder's.
_NS = uuid.UUID("2d1f7a6c-4b83-5e21-9c07-1a3e5d7b9f02")

# How many feeds to hand module-news per /harvest call. Bounds the
# response size on the first full sweep (~57 feeds) without serialising
# every feed into its own round-trip.
_CHUNK = 15
_HARVEST_TIMEOUT = 120


def _interval_for(kind: str | None, hcfg: dict) -> int:
    if (kind or "") in AUTHORITY_KINDS:
        return int(hcfg.get("authority_interval_min", _FALLBACK_AUTHORITY_MIN)) * 60
    return int(hcfg.get("other_interval_min", _FALLBACK_OTHER_MIN)) * 60


def _dedup_key(url: str | None, source_name: str | None, title: str) -> str:
    """Stable identity of an article. Hash so it always fits and is
    fixed-length. URL (minus fragment) when present — that is what makes
    the same story re-listed by an archive feed collapse — else the
    source+title, which is the best we can do for feeds without links."""
    if url and url.strip():
        base = url.strip().split("#", 1)[0]
    else:
        base = f"{source_name or ''}|{title}"
    return hashlib.sha256(base.encode("utf-8", "ignore")).hexdigest()


def _article_id(dedup_key: str) -> uuid.UUID:
    return uuid.uuid5(_NS, dedup_key)


def _parse_iso(s: str | None) -> datetime | None:
    """ISO string -> naive UTC, **converting** the offset rather than dropping it.

    The intent stated in the old comment was right — "so the column stays
    naive UTC" — but `.replace(tzinfo=None)` removes the marker and keeps the
    wall-clock reading, which is naive LOCAL-OF-THE-SOURCE, not naive UTC. A
    value arriving as `2026-08-03T15:35:30+02:00` was stored as 15:35 instead
    of 13:35, i.e. two hours in the future.

    The primary damage was one layer down, in module-news' own date parser
    (see `_to_naive_utc` there); this one passed the already-broken value
    through and would have broken a correct one. Both are fixed, because a
    guard that only works when the caller is already right is not a guard.
    """
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None
    if d.tzinfo is None:
        return d
    return d.astimezone(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Harvest
# --------------------------------------------------------------------------

async def harvest_once(db: AsyncSession, force: bool = False) -> dict:
    """Poll every DUE feed once and persist new articles. Idempotent.

    `force=True` (the Owner-console "run now" button) ignores both the
    disabled switch and the per-feed due-timers and fetches every enabled
    feed immediately.
    """
    hcfg = await news_feeds.get_harvest_settings()
    if not force and not hcfg.get("enabled", True):
        return {"due": 0, "fetched": 0, "inserted": 0, "failed": 0,
                "skipped": "disabled"}

    feeds = await news_feeds.get_feeds()
    cfg = await news_feeds.get_settings()
    feeds = news_feeds.apply_placeholders(feeds, cfg)
    feeds = [f for f in feeds if f.get("url") and f.get("enabled", True)]
    if not feeds:
        return {"due": 0, "fetched": 0, "inserted": 0, "failed": 0}

    now = datetime.utcnow()

    # Which feeds are due? Load their poll state in one query.
    urls = [f["url"] for f in feeds]
    rows = (await db.execute(
        select(NewsFeedPollState).where(NewsFeedPollState.feed_url.in_(urls))
    )).scalars().all()
    state = {r.feed_url: r for r in rows}

    due = []
    for f in feeds:
        if force:
            due.append(f)
            continue
        st = state.get(f["url"])
        interval = _interval_for(f.get("kind"), hcfg)
        if st is None or st.last_poll_ok is None:
            due.append(f)
        elif (now - st.last_poll_ok).total_seconds() >= interval:
            due.append(f)
    if not due:
        return {"due": 0, "fetched": 0, "inserted": 0, "failed": 0}

    inserted = 0
    failed = 0
    fetched = 0
    async with httpx.AsyncClient(timeout=_HARVEST_TIMEOUT) as client:
        for i in range(0, len(due), _CHUNK):
            chunk = due[i:i + _CHUNK]
            try:
                r = await client.post(f"{settings.module_news_url}/harvest",
                                      json={"feeds": chunk})
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPError as e:
                log.warning("harvest: module-news unreachable for chunk: %s", e)
                for f in chunk:
                    await _record_poll(db, f, now, ok=False, error=str(e)[:280],
                                       entries=0)
                    failed += 1
                continue

            for rec in data.get("feeds") or []:
                fetched += 1
                if not rec.get("ok"):
                    await _record_poll(db, _feed_of(rec), now, ok=False,
                                       error=(rec.get("error") or "unknown")[:280],
                                       entries=0)
                    failed += 1
                    continue
                entries = rec.get("entries") or []
                n = await _upsert_entries(db, rec, entries)
                inserted += n
                await _record_poll(db, _feed_of(rec), now, ok=True, error=None,
                                   entries=len(entries))

    await db.commit()
    log.info("harvest: %d due, %d fetched, %d new articles, %d failed",
             len(due), fetched, inserted, failed)
    return {"due": len(due), "fetched": fetched, "inserted": inserted,
            "failed": failed}


def _feed_of(rec: dict) -> dict:
    return {"url": rec.get("url"), "id": rec.get("feed_id"),
            "kind": rec.get("kind")}


async def _upsert_entries(db: AsyncSession, rec: dict, entries: list[dict]) -> int:
    """Insert new rows for one feed; ON CONFLICT DO NOTHING on dedup_key.
    Returns rows actually inserted (new articles)."""
    seen: set[str] = set()
    values = []
    for e in entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        url = e.get("url") or None
        key = _dedup_key(url, rec.get("name"), title)
        if key in seen:            # duplicate inside this same batch
            continue
        seen.add(key)
        summary = e.get("summary") or ""
        values.append({
            "id": _article_id(key),
            "dedup_key": key,
            "title": title[:2000],
            "url": url,
            "summary": summary,
            "search_text": f"{title} {summary}".lower(),
            "published": _parse_iso(e.get("published")),
            "fetched_at": datetime.utcnow(),
            "feed_id": rec.get("feed_id"),
            "source_name": rec.get("name"),
            "source_kind": rec.get("kind"),
            "source_lang": rec.get("lang"),
        })
    if not values:
        return 0
    stmt = (pg_insert(NewsArticle)
            .values(values)
            .on_conflict_do_nothing(index_elements=["dedup_key"]))
    result = await db.execute(stmt)
    # rowcount reflects rows the DB actually inserted (conflicts excluded).
    return result.rowcount or 0


async def _record_poll(db: AsyncSession, feed: dict, now: datetime,
                       ok: bool, error: str | None, entries: int) -> None:
    """Upsert the per-feed poll state so the next tick knows it's fresh
    and the console can show when a source last answered."""
    base = {
        "feed_url": feed["url"],
        "feed_id": feed.get("id"),
        "source_kind": feed.get("kind"),
        "last_poll_attempt": now,
        "last_poll_ok": now if ok else None,
        "last_error": None if ok else error,
        "last_entry_count": entries,
        "consecutive_fails": 0 if ok else 1,
    }
    if ok:
        update = {"feed_id": base["feed_id"], "source_kind": base["source_kind"],
                  "last_poll_attempt": now, "last_poll_ok": now,
                  "last_error": None, "last_entry_count": entries,
                  "consecutive_fails": 0}
    else:
        # keep last_poll_ok as-is, bump the failure counter
        update = {"feed_id": base["feed_id"], "source_kind": base["source_kind"],
                  "last_poll_attempt": now, "last_error": error,
                  "consecutive_fails": NewsFeedPollState.consecutive_fails + 1}
    stmt = (pg_insert(NewsFeedPollState)
            .values(base)
            .on_conflict_do_update(index_elements=["feed_url"], set_=update))
    await db.execute(stmt)


# --------------------------------------------------------------------------
# Search (analyst read path)
# --------------------------------------------------------------------------

_LIKE_ESCAPE = str.maketrans({"\\": r"\\", "%": r"\%", "_": r"\_"})


def _like(term: str) -> str:
    return "%" + term.translate(_LIKE_ESCAPE) + "%"


# Fancy quote variants → straight double quote, so a phrase pasted from a
# browser (« », „ ", " ") is honoured too.
_QUOTE_NORM = str.maketrans({"„": '"', "“": '"', "”": '"', "»": '"', "«": '"',
                             "‟": '"', "”": '"'})


def parse_terms(q: str) -> list[str]:
    """Split a query into match terms, honouring "quoted phrases".

    A quoted phrase becomes ONE term matched as a contiguous substring;
    unquoted words become individual AND terms. So both `Hells Angels`
    (two words, both must appear) and `"Hells Angels"` (the exact phrase)
    work — and stray quote characters no longer end up inside a term and
    break the match (the bug where a quoted search found nothing)."""
    s = (q or "").strip().lower().translate(_QUOTE_NORM)
    phrases = re.findall(r'"([^"]+)"', s)
    rest = re.sub(r'"[^"]*"', " ", s)
    terms = [p.strip() for p in phrases if p.strip()]
    terms += [w for w in rest.split() if w]
    return terms


async def count_articles(db: AsyncSession) -> int:
    return int((await db.execute(
        select(func.count()).select_from(NewsArticle))).scalar() or 0)


def _epoch(dt: datetime | None) -> float | None:
    """Naive-UTC datetime → unix seconds, so the console can render
    'X min ago' with the same helper the feed-health column uses."""
    if dt is None:
        return None
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc).timestamp()


async def storage_stats(db: AsyncSession) -> dict:
    """How much disk the news cache occupies, and where it is heading.

    The cache is the only table in this system that grows **without any
    retention rule**: cases are purged by the daily scheduler, audit entries
    are bounded by activity, but every article ever harvested stays. That is
    a defensible default for a situational-awareness archive — an article
    deleted after 90 days is one an analyst can no longer cite — but it must
    be VISIBLE, because the alternative is discovering it when the disk on a
    customer-facing box fills up.

    Sizes come from Postgres itself (`pg_total_relation_size`) rather than a
    row-count estimate: the trigram index that makes the analyst search fast
    is currently LARGER than the data it indexes, and a figure that counted
    only the heap would understate the real footprint by more than half.

    The projection is deliberately based on the last 30 days rather than the
    lifetime average — feeds get added, and the average over a period when
    half of them did not exist yet describes a system that is gone.
    """
    def _q(sql: str):
        from sqlalchemy import text
        return db.execute(text(sql))

    tables = ("news_articles", "news_feed_poll_state")
    per_table = []
    total_bytes = 0
    for name in tables:
        row = (await _q(
            f"select pg_total_relation_size('{name}'), "
            f"pg_relation_size('{name}'), pg_indexes_size('{name}')"
        )).first()
        total, heap, idx = (int(x or 0) for x in row)
        total_bytes += total
        per_table.append({"table": name, "bytes": total,
                          "heap_bytes": heap, "index_bytes": idx})

    rows = await count_articles(db)
    now = datetime.utcnow()
    since_30 = now - timedelta(days=30)
    since_7 = now - timedelta(days=7)
    added_30 = int((await db.execute(
        select(func.count()).select_from(NewsArticle)
        .where(NewsArticle.fetched_at >= since_30))).scalar() or 0)
    added_7 = int((await db.execute(
        select(func.count()).select_from(NewsArticle)
        .where(NewsArticle.fetched_at >= since_7))).scalar() or 0)
    oldest = (await db.execute(select(func.min(NewsArticle.fetched_at)))).scalar()

    bytes_per_article = round(total_bytes / rows) if rows else 0

    # Project from the window that was ACTUALLY observed, not from a nominal
    # 30 days. A cache that is, say, 12 days old has every one of its
    # articles inside "the last 30 days" — and `added_30 * bytes_per_article`
    # would report well under half the real monthly intake. A projection that is 2.5x low is worse than
    # none, because it is precise enough to be believed.
    #
    # `days_observed` is therefore the age of the cache, capped at 30. Only
    # projected once a full day has been seen: extrapolating from a few
    # hours multiplies the noise by 30.
    age_days = ((now - oldest).total_seconds() / 86400.0) if oldest else 0.0
    days_observed = min(age_days, 30.0)
    if added_30 and days_observed >= 1.0:
        per_month = round(added_30 / days_observed * 30 * bytes_per_article)
    else:
        per_month = None

    return {
        "bytes": total_bytes,
        "rows": rows,
        "bytes_per_article": bytes_per_article,
        "per_table": sorted(per_table, key=lambda t: t["bytes"], reverse=True),
        "added_7d": added_7,
        "added_30d": added_30,
        "projected_bytes_per_month": per_month,
        # How long the projection actually watched. Shown, so a figure from
        # 2 days of data is not read with the same confidence as one from 30.
        "observed_days": round(days_observed, 1),
        "oldest_fetch": _epoch(oldest),
        # There is none. Stated explicitly so the console can say so rather
        # than leave the operator to infer it from a number that only grows.
        "retention_days": None,
    }


async def harvester_status(db: AsyncSession) -> dict:
    """Everything the Owner console shows: schedule, article stats and
    per-feed poll state. Read-only; operator-global public data only."""
    hcfg = await news_feeds.get_harvest_settings()
    feeds = await news_feeds.get_feeds()
    scfg = await news_feeds.get_settings()
    feeds = news_feeds.apply_placeholders(feeds, scfg)
    enabled = [f for f in feeds if f.get("url") and f.get("enabled", True)]

    # Article stats.
    total = await count_articles(db)
    per_kind_rows = (await db.execute(
        select(NewsArticle.source_kind, func.count())
        .group_by(NewsArticle.source_kind))).all()
    per_kind = sorted(
        [{"kind": k or "other", "count": int(c)} for k, c in per_kind_rows],
        key=lambda r: r["count"], reverse=True)
    newest_pub = (await db.execute(
        select(func.max(NewsArticle.published)))).scalar()
    last_fetch = (await db.execute(
        select(func.max(NewsArticle.fetched_at)))).scalar()

    # Poll state + due computation (same logic as harvest_once, read-only).
    urls = [f["url"] for f in enabled]
    rows = (await db.execute(
        select(NewsFeedPollState).where(NewsFeedPollState.feed_url.in_(urls))
    )).scalars().all() if urls else []
    state = {r.feed_url: r for r in rows}
    now = datetime.utcnow()
    due = 0
    feed_rows = []
    for f in enabled:
        st = state.get(f["url"])
        interval = _interval_for(f.get("kind"), hcfg)
        is_due = (st is None or st.last_poll_ok is None
                  or (now - st.last_poll_ok).total_seconds() >= interval)
        if is_due:
            due += 1
        feed_rows.append({
            "feed_id": f.get("id"),
            "name": f.get("name"),
            "kind": f.get("kind"),
            "interval_min": interval // 60,
            "last_poll_ok": _epoch(st.last_poll_ok) if st else None,
            "last_entry_count": st.last_entry_count if st else None,
            "consecutive_fails": st.consecutive_fails if st else 0,
            "last_error": st.last_error if st else None,
            "due": is_due,
        })

    return {
        "settings": hcfg,
        "stats": {
            "total_articles": total,
            "per_kind": per_kind,
            "feeds_enabled": len(enabled),
            "feeds_due": due,
            "newest_published": newest_pub.strftime("%Y-%m-%d") if newest_pub else None,
            "last_harvest": _epoch(last_fetch),
        },
        "storage": await storage_stats(db),
        "feeds": feed_rows,
    }


def _context(summary: str, terms: list[str], width: int = 320) -> str:
    """Passage where a search term appears — ported from the module so the
    reading view is unchanged. Falls back to the summary head."""
    text = summary or ""
    if not text:
        return ""
    low = text.lower()
    pos = -1
    for t in terms:
        p = low.find(t)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos == -1:
        return text[:width].strip()
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    if start > 0:
        sp = text.find(" ", start)
        start = sp + 1 if 0 <= sp < start + 25 else start
    if end < len(text):
        sp = text.rfind(" ", start, end)
        end = sp if sp > start else end
    out = text[start:end].strip()
    return ("… " if start > 0 else "") + out + (" …" if end < len(text) else "")


async def search(db: AsyncSession, query: str, facets: list[str] | None,
                 max_age_days: int | None, limit: int) -> dict:
    """Substring-AND over the cached articles. Same shape the frontend got
    from the old live endpoint."""
    q = (query or "").strip()
    terms = parse_terms(q)
    if not terms:
        return {"query": query, "queries": [], "count": 0, "articles": [],
                "notes": [], "errors": ["empty query"]}

    # Variant strings, same idea as the live path: base + one per facet.
    queries = [q]
    for f in (facets or [])[:5]:
        f = (f or "").strip()
        if f and f"{q} {f}" not in queries:
            queries.append(f"{q} {f}")

    stmt = select(NewsArticle)
    for t in terms:
        stmt = stmt.where(NewsArticle.search_text.like(_like(t), escape="\\"))
    if max_age_days:
        cutoff = datetime.utcnow() - timedelta(days=int(max_age_days))
        stmt = stmt.where(
            (NewsArticle.published.is_(None)) | (NewsArticle.published >= cutoff))
    stmt = stmt.order_by(NewsArticle.published.desc().nullslast()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()

    articles = []
    for a in rows:
        hay = a.search_text
        matched_variants = [
            vq for vq in queries
            if all(t in hay for t in parse_terms(vq))
        ]
        matched_terms = [t for t in terms if t in hay]
        articles.append({
            "title": a.title,
            "url": a.url,
            "summary": (a.summary or "")[:600],
            "match_context": _context(a.summary or "", terms),
            "matched_terms": matched_terms,
            "published": a.published.strftime("%Y-%m-%d") if a.published else "",
            "source_name": a.source_name,
            "source_kind": a.source_kind,
            "source_lang": a.source_lang,
            "matched": matched_variants or [q],
        })

    return {"query": query, "queries": queries, "count": len(articles),
            "articles": articles, "notes": [], "errors": []}
