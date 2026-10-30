"""Daily situation report — the one screen that comes to the analyst.

Everything in here already existed and nobody had to look at it. The news
harvester caches 17 000 articles, `cve_lookup` knows the CISA KEV catalogue,
ransomware.live tracks leak-site victims — but each of those answers a
question only once it is asked. A running investigation team does not ask;
it opens the app in the morning.

Three sources, chosen because each answers a different question:

* **News** — what was reported. Ordered by SOURCE KIND, not by time: in the
  last week the cache held 46 authority items against 10 907 media items, so
  sorting by recency would bury every official statement under press
  churn. Authority and police first, media last.
* **CISA KEV** — which vulnerabilities are being exploited *right now*. The
  catalogue is the closest thing to an official "act on this today" list.
* **Ransomware victims** — who was published on a leak site, with the
  DACH-region ones pulled to the front, because that is the caseload.

Operator-global PUBLIC data throughout. No case content, no tenant data —
so this lives framework-side like the news cache, and the sovereignty
boundary is untouched.

Computed on request with a short cache rather than stored: a digest is a
view of sources that are themselves already cached, and a stored copy would
be stale the moment the harvester ticks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("osint.digest")

KEV_URL = ("https://www.cisa.gov/sites/default/files/feeds/"
           "known_exploited_vulnerabilities.json")
RANSOM_PRO = "https://api-pro.ransomware.live/victims/recent"

# Source kinds in the order an investigator should read them. An official
# release and a newspaper article are both leads, but not the same weight —
# the same distinction module-news already makes with its confidences.
KIND_ORDER = ["authority", "police", "cyber", "tech", "media", "other"]

# The caseload. A victim in this set leads the ransomware section regardless
# of how recent it is.
HOME_COUNTRIES = {"CH", "LI", "DE", "AT"}

_TTL = 900.0
_cache: dict[str, tuple[float, dict]] = {}

# Degradation notices travel as a CODE plus an optional technical detail, not
# as an English sentence. They used to be prose, which meant the one part of
# the panel that explains why a section is missing was English-only in a
# product delivered in four languages to Swiss authorities. The frontend maps
# the code to `digest.note_<code>`; `message` stays for any non-UI consumer.
_NOTE_TEXT = {
    "kev_unavailable": "CISA KEV unavailable",
    "ransomware_no_key": ("ransomware.live: no key configured — this section "
                          "needs the free PRO key."),
    "ransomware_bad_response": "ransomware.live: unexpected non-JSON response.",
    "ransomware_unavailable": "ransomware.live unavailable",
}


def _note(code: str, detail: str = "") -> dict[str, str]:
    base = _NOTE_TEXT.get(code, code)
    return {"code": code, "detail": detail,
            "message": f"{base}: {detail}" if detail else base}


async def _news(
    db: AsyncSession, hours: int, per_kind: int,
) -> tuple[dict[str, list[dict]], int]:
    """The head of each source kind, plus how many articles there REALLY are.

    Two things were wrong here and both are about honesty of numbers.

    **The count.** `news_total` used to be the sum of the already-capped
    buckets, so the panel announced "34 reports from the last 24 hours" when
    the cache held 2 892 — and 40 against 25 738 over a week. For a situation
    report that is the wrong kind of error: volume is the point, and a figure
    that reads roughly the same on a quiet day and a loud one carries no
    information at all. The count is now its own `COUNT(*)`.

    **The cap.** The old query selected every row in the window and threw
    away all but eight per kind in Python — tens of thousands of rows fetched
    to keep 40, every quarter of an hour per cache key, on a table that grows
    by hundreds of MB a month. `ROW_NUMBER()` does the same selection in the database
    and returns exactly what is displayed.
    """
    rows = (await db.execute(text("""
        SELECT title, url, summary, published, source_name, kind FROM (
            SELECT title, url, summary, published, source_name,
                   lower(coalesce(source_kind, 'other')) AS kind,
                   row_number() OVER (
                       PARTITION BY lower(coalesce(source_kind, 'other'))
                       ORDER BY published DESC
                   ) AS rn
            FROM news_articles
            WHERE published > now() - (:h || ' hours')::interval
        ) ranked
        WHERE rn <= :n
        ORDER BY published DESC
    """), {"h": str(hours), "n": per_kind})).all()

    total = (await db.execute(text("""
        SELECT count(*) FROM news_articles
        WHERE published > now() - (:h || ' hours')::interval
    """), {"h": str(hours)})).scalar_one()

    out: dict[str, list[dict]] = {}
    for title, url, summary, published, source, kind in rows:
        out.setdefault(kind, []).append({
            "title": title, "url": url,
            "summary": (summary or "")[:280],
            "published": published.isoformat() if published else None,
            "source": source, "kind": kind,
        })
    return {k: out[k] for k in KIND_ORDER if out.get(k)}, int(total or 0)


async def _kev(days: int) -> tuple[list[dict], str | None]:
    """Vulnerabilities CISA added to the exploited catalogue recently."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            r = await c.get(KEV_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001
        return [], _note("kev_unavailable", type(e).__name__)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    items = [
        {
            "cve": v.get("cveID"),
            "vendor": v.get("vendorProject"),
            "product": v.get("product"),
            "name": v.get("vulnerabilityName"),
            "added": v.get("dateAdded"),
            "due": v.get("dueDate"),
            "ransomware": v.get("knownRansomwareCampaignUse"),
            "url": f"https://nvd.nist.gov/vuln/detail/{v.get('cveID')}",
        }
        for v in (data.get("vulnerabilities") or [])
        if str(v.get("dateAdded") or "") >= cutoff
    ]
    items.sort(key=lambda x: str(x["added"]), reverse=True)
    return items, None


async def _victims(api_key: str, limit: int) -> tuple[list[dict], str | None]:
    if not api_key:
        return [], _note("ransomware_no_key")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(RANSOM_PRO, headers={
                "X-API-KEY": api_key, "Accept": "application/json"})
        if "json" not in r.headers.get("content-type", ""):
            return [], _note("ransomware_bad_response")
        raw = (r.json() or {}).get("victims") or []
    except Exception as e:  # noqa: BLE001
        return [], _note("ransomware_unavailable", type(e).__name__)

    items = [{
        "victim": v.get("victim") or v.get("post_title") or v.get("website"),
        "group": v.get("group") or v.get("group_name"),
        "country": (v.get("country") or "").upper(),
        "activity": v.get("activity"),
        "discovered": v.get("discovered"),
        "website": v.get("website"),
        "url": v.get("post_url") or v.get("url"),
    } for v in raw]
    # Home region first — everything else keeps its recency order.
    items.sort(key=lambda x: (x["country"] not in HOME_COUNTRIES,))
    return items[:limit], None


async def build(
    db: AsyncSession, *, hours: int = 24, kev_days: int = 14,
    per_kind: int = 8, victims: int = 15, api_key: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Assemble the report. Any failing source degrades to a stated note —
    a digest that silently drops a section would read as "nothing happened"."""
    ck = f"{hours}:{kev_days}:{per_kind}:{victims}:{bool(api_key)}"
    now = time.time()
    if not force and ck in _cache and now - _cache[ck][0] < _TTL:
        return _cache[ck][1]

    (news, news_total), (kev, kev_err), (vics, vic_err) = await asyncio.gather(
        _news(db, hours, per_kind), _kev(kev_days), _victims(api_key, victims))

    notes = [n for n in (kev_err, vic_err) if n]
    out = {
        "generated_at": datetime.now(timezone.utc).replace(
            microsecond=0).isoformat(),
        "window_hours": hours,
        "news": news,
        # The real number in the window, not the number displayed — see _news.
        "news_total": news_total,
        "news_shown": sum(len(v) for v in news.values()),
        "kev": kev,
        "kev_days": kev_days,
        "victims": vics,
        "victims_home": [v for v in vics if v["country"] in HOME_COUNTRIES],
        "notes": notes,
        # Said out loud rather than implied: this is public reporting, not a
        # statement about any case in this system. The UI renders its own
        # translated string (`digest.scope`) — this English one remains for
        # API consumers and as the fallback if a bundle fails to load.
        "scope": ("Public sources only — press, CISA KEV and ransomware "
                  "leak-site postings. Nothing here is derived from case "
                  "data."),
    }
    _cache[ck] = (now, out)
    return out
