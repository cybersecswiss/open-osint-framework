"""
Full-text search across authority, police, media and cyber news feeds.

Why the search happens HERE and not at the source: the obvious candidate,
admin.ch's ``newsd`` feed endpoint, advertises a ``keyword=`` parameter —
but it is inert. Measured: the same feed returns 20 items with
an empty keyword and 0 items for every search term tried. So feeds are
fetched whole and filtered locally. That is workable because the feeds are
archives, not tickers: one federal feed yields ~124 releases going back to
2021 (``end_index`` controls the window).

Feeds come from three places, in order of precedence:
  1. ``options.feeds`` — the list the operator maintains in the Owner
     console, handed down by the backend per search.
  2. ``NEWS_FEEDS_JSON`` — an env override, for a deployment that wants a
     fixed list without the console.
  3. ``feeds.json`` next to this module — the verified default.

Every finding carries the feed's ``kind`` (authority / police / media /
cyber). An analyst must be able to tell a federal press release from a
newspaper article at a glance; both are legitimate, they carry very
different evidentiary weight.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
import warnings
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from safe_fetch import BlockedURL, assert_public_url
from schemas import NOTE_PREFIX, EdgeResult, Finding

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
              "Gecko/20100101 Firefox/115.0")

FEED_TIMEOUT = int(os.getenv("NEWS_FEED_TIMEOUT", "25") or 25)
# Feeds are fetched concurrently, but politely — these are public bodies.
CONCURRENCY = int(os.getenv("NEWS_CONCURRENCY", "8") or 8)
MAX_RESULTS = int(os.getenv("NEWS_MAX_RESULTS", "60") or 60)
# Ignore anything older than this unless the caller asks otherwise.
DEFAULT_MAX_AGE_DAYS = int(os.getenv("NEWS_MAX_AGE_DAYS", "1825") or 1825)

_DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "feeds.json"

# Feed bodies are cached process-wide. Without this, every search re-fetched
# every feed — 19 of them against newsd.admin.ch alone — which is enough to
# get rate-limited into ReadErrors by the very authority the module depends
# on. RSS changes on the order of hours, not seconds.
FEED_CACHE_TTL = int(os.getenv("NEWS_FEED_CACHE_TTL", "900") or 900)
_feed_cache: dict[str, tuple[float, list[dict]]] = {}

# Per-feed health, so the operator can SEE that a source stopped answering
# instead of finding it in a search note. Keyed by URL; the backend merges
# this with its own persisted copy, which is what survives a restart.
#   last_ok      unix ts of the last successful fetch
#   last_error   unix ts of the last failure
#   error        reason of the last failure
#   fails        consecutive failures (reset on success)
_feed_health: dict[str, dict] = {}


def feed_health() -> dict[str, dict]:
    return _feed_health


def _mark_ok(url: str, entries: int) -> None:
    h = _feed_health.setdefault(url, {})
    h.update({"last_ok": time.time(), "entries": entries, "fails": 0, "error": None})


def _mark_fail(url: str, reason: str) -> None:
    h = _feed_health.setdefault(url, {})
    h["last_error"] = time.time()
    h["error"] = reason
    h["fails"] = int(h.get("fails") or 0) + 1

# Politeness cap PER HOST. The global semaphore alone still allowed 8
# simultaneous requests to one server; public bodies answer far fewer.
PER_HOST = int(os.getenv("NEWS_PER_HOST_CONCURRENCY", "2") or 2)
_host_locks: dict[str, asyncio.Semaphore] = {}


def _host_sem(url: str) -> asyncio.Semaphore:
    host = urllib.parse.urlparse(url).netloc.lower()
    if host not in _host_locks:
        _host_locks[host] = asyncio.Semaphore(PER_HOST)
    return _host_locks[host]

log = logging.getLogger("module-news.search")


def _default_feeds() -> list[dict]:
    env = os.getenv("NEWS_FEEDS_JSON", "").strip()
    if env:
        try:
            data = json.loads(env)
            return data.get("feeds", data) if isinstance(data, dict) else data
        except Exception as e:  # noqa: BLE001
            log.warning("NEWS_FEEDS_JSON unparsable, falling back: %s", e)
    try:
        return json.loads(_DEFAULTS_PATH.read_text()).get("feeds", [])
    except Exception as e:  # noqa: BLE001
        log.error("feeds.json unreadable: %s", e)
        return []


def _resolve_feeds(options: dict | None) -> list[dict]:
    """Operator-configured list wins; otherwise the built-in default."""
    if options:
        configured = options.get("feeds")
        if isinstance(configured, list) and configured:
            return [f for f in configured if f.get("url") and f.get("enabled", True)]
    return _default_feeds()


def _text(node) -> str:
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _strip_html(s: str) -> str:
    """Feed summaries routinely carry markup and CDATA leftovers."""
    if not s:
        return ""
    s = re.sub(r"<!\[CDATA\[|\]\]>", " ", s)
    s = BeautifulSoup(s, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", s).strip()


def _to_naive_utc(d: datetime | None) -> datetime | None:
    """Normalise to naive UTC — **converting** the offset, not discarding it.

    ⚠️ The obvious `.replace(tzinfo=None)` is wrong here: it strips the zone
    marker and keeps the wall-clock reading. A Swiss feed saying
    `Mon, 03 Aug 2026 15:35:30 +0200` would be stored as 15:35 when the
    real UTC time is 13:35 — two hours in the future (the signature of a lost
    summer offset: future dates, none more than 24 h ahead).

    Consequences of getting this wrong:

    * such articles sort to the top of every `ORDER BY published DESC`, so
      the "newest" in the situation report is systematically wrong;
    * the feeds affected are the ones with a POSITIVE offset, i.e. the
      German-language and Swiss authority sources — precisely the ones the
      digest is meant to lead with;
    * and `run_news_search` puts this value on the finding as `found_at`, so
      it travels through `observed_at` into the entities stored on the
      tenant's data agent, which the architecture calls the evidentiary field.

    Naive UTC is the target because the timestamp columns on both sides are
    `timestamp without time zone`; handing an aware datetime to asyncpg
    raises. A value with no zone marker at all is taken as UTC, which is what
    the rest of the framework assumes.
    """
    if d is None:
        return None
    if d.tzinfo is None:
        return d
    return d.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_date(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:                                    # RFC-822 (RSS)
        return _to_naive_utc(parsedate_to_datetime(raw))
    except Exception:  # noqa: BLE001
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return _to_naive_utc(datetime.strptime(raw[:len(raw)], fmt))
        except Exception:  # noqa: BLE001
            continue
    # Atom often has a trailing offset like +02:00 that %z rejects pre-3.7
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", raw)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}",
                                     "%Y-%m-%d %H:%M:%S")
        except Exception:  # noqa: BLE001
            return None
    return None


def _soup(xml: str) -> BeautifulSoup:
    """Parse as XML, not HTML.

    html.parser treats <link> as a void element, so an RSS
    ``<link>https://…</link>`` loses its text entirely — measured: 13 of 17
    hits came back with no URL. lxml-xml keeps element text AND preserves
    tag case (pubDate, dc:date), which the lookups below rely on.
    """
    try:
        return BeautifulSoup(xml, "xml")
    except Exception:  # noqa: BLE001 — never lose a feed over a parser issue
        log.warning("XML parser unavailable, falling back to html.parser")
        return BeautifulSoup(xml, "html.parser")


def _find(node, *names):
    """First matching child, tolerant of tag case across parsers."""
    for n in names:
        hit = node.find(n)
        if hit:
            return hit
        hit = node.find(n.lower())
        if hit:
            return hit
    return None


def _entries(xml: str) -> list[dict]:
    """Normalise RSS <item> and Atom <entry> into one shape."""
    soup = _soup(xml)
    out: list[dict] = []
    for node in soup.find_all(["item", "entry"]):
        title = _strip_html(_text(_find(node, "title")))
        if not title:
            continue
        link = ""
        lt = _find(node, "link")
        if lt:
            link = (lt.get("href") or _text(lt) or "").strip()
        if not link:
            g = _find(node, "guid")
            link = _text(g) if g and _text(g).startswith("http") else ""
        summary = _strip_html(_text(
            _find(node, "description", "summary", "content")))
        date_raw = _text(_find(node, "pubDate", "published", "updated", "date"))
        out.append({"title": title, "url": link,
                    # Full text kept: the match context is cut from it below.
                    # Only what reaches the graph is truncated.
                    "summary": summary,
                    "published": _parse_date(date_raw), "published_raw": date_raw})
    return out


async def _fetch_feed(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                      feed: dict) -> tuple[dict, list[dict], str | None]:
    url = feed["url"]
    now = time.time()
    hit = _feed_cache.get(url)
    if hit and now - hit[0] < FEED_CACHE_TTL:
        return feed, hit[1], None

    async with sem, _host_sem(url):
        try:
            # The feed list is operator-supplied, and this container sits on
            # the internal network next to license:9000, keycloak:8080 and
            # updater:9999 — the one holding the Docker socket. The Owner
            # console's "Test" button already guards its fetch, with a comment
            # calling an unguarded one "a neat little internal-network
            # prober"; the path that actually runs, every ten minutes and
            # unattended, must be guarded just the same. Whatever came back would have been parsed
            # as RSS and written into `news_articles`, which every tenant can
            # full-text search.
            #
            # Only the operator can set a feed URL (the endpoint hangs off the
            # platform_admin router) and this module publishes no port, so
            # this is defence in depth rather than a user-reachable path.
            # Closing it anyway: the project made this decision one function
            # over, and a guard that exists but is never imported is worse
            # than no guard, because it reads like one.
            await assert_public_url(url)
            r = await client.get(url, timeout=FEED_TIMEOUT)
            if r.status_code != 200:
                _mark_fail(url, f"HTTP {r.status_code}")
                # Serve stale rather than reporting a gap: an expired cache
                # entry is far better evidence than "source unavailable".
                if hit:
                    return feed, hit[1], None
                return feed, [], f"HTTP {r.status_code}"
            entries = _entries(r.text)
            _feed_cache[url] = (now, entries)
            _mark_ok(url, len(entries))
            return feed, entries, None
        except BlockedURL as e:
            # Never serve a stale cache for this one: a URL that stopped
            # being public is a configuration problem the operator must see.
            _mark_fail(url, "blocked")
            return feed, [], f"URL does not point at a public host: {e}"
        except Exception as e:  # noqa: BLE001
            _mark_fail(url, type(e).__name__)
            if hit:
                return feed, hit[1], None
            return feed, [], f"{type(e).__name__}"


def _context(entry: dict, terms: list[str], width: int = 320) -> str:
    """The passage where the search term actually appears.

    An analyst scanning 30 hits needs to see WHY each matched, not the
    article's opening sentence — which is what a plain summary shows and
    which often has nothing to do with the query. Falls back to the start
    of the summary when the term only occurs in the title.
    """
    text = entry.get("summary") or ""
    if not text:
        return ""
    low = text.lower()
    pos = -1
    for t in terms:
        p = low.find(t)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos == -1:                       # matched on the title only
        return text[:width].strip()
    start = max(0, pos - width // 3)
    end = min(len(text), start + width)
    # Don't cut mid-word at the edges.
    if start > 0:
        sp = text.find(" ", start)
        start = sp + 1 if 0 <= sp < start + 25 else start
    if end < len(text):
        sp = text.rfind(" ", start, end)
        end = sp if sp > start else end
    out = text[start:end].strip()
    return ("… " if start > 0 else "") + out + (" …" if end < len(text) else "")


_QUOTE_NORM = str.maketrans({"„": '"', "“": '"', "”": '"', "»": '"', "«": '"'})


def parse_terms(q: str) -> list[str]:
    """Split a query into match terms honouring "quoted phrases": a quoted
    phrase is ONE contiguous-substring term, unquoted words are individual
    AND terms. Straight and fancy quotes are handled; stray quotes no
    longer land inside a term and break the match."""
    s = (q or "").strip().lower().translate(_QUOTE_NORM)
    phrases = re.findall(r'"([^"]+)"', s)
    rest = re.sub(r'"[^"]*"', " ", s)
    terms = [p.strip() for p in phrases if p.strip()]
    terms += [w for w in rest.split() if w]
    return terms


def _matches(entry: dict, terms: list[str]) -> bool:
    """All whitespace-separated terms must appear in title or summary.

    Deliberately an AND over terms and a plain substring test: an analyst
    typing "Hells Angels Zürich" means all three, and a substring match is
    what makes German compounds work ("Drogenhandel" inside
    "Drogenhandelsnetz").
    """
    hay = f"{entry['title']} {entry['summary']}".lower()
    return all(t in hay for t in terms)


async def harvest(feeds: list[dict]) -> dict:
    """Fetch a set of feeds whole and return their parsed entries.

    This is the background-harvester counterpart to run_news_search: the
    backend polls feeds on a schedule and persists the result in the
    framework DB, so an analyst search reads the DB instead of hammering
    the source. Parsing lives HERE (not in the backend) so the RSS/Atom
    quirks — the <link> void-element bug, CDATA, the many date formats,
    per-host politeness, stale-serve on failure — stay single-sourced.

    Returns one record per feed with its entries; `published` is an ISO
    string (naive UTC) or null so the payload is JSON-serialisable.
    """
    feeds = [f for f in (feeds or []) if f.get("url")]
    if not feeds:
        return {"feeds": []}

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT,
                 "Accept": "application/rss+xml,application/atom+xml,"
                           "application/xml,text/xml,*/*"},
    ) as client:
        results = await asyncio.gather(
            *(_fetch_feed(client, sem, f) for f in feeds))

    out = []
    for feed, entries, err in results:
        out.append({
            "feed_id": feed.get("id"),
            "url": feed.get("url"),
            "name": feed.get("name"),
            "kind": feed.get("kind"),
            "lang": feed.get("lang"),
            "ok": err is None,
            "error": err,
            "entries": [
                {"title": e["title"], "url": e["url"],
                 "summary": e["summary"],
                 "published": e["published"].isoformat() if e["published"] else None,
                 "published_raw": e.get("published_raw")}
                for e in entries
            ],
        })
    return {"feeds": out}


async def run_news_search(query: str, options: dict | None = None,
                          ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    q = (query or "").strip()
    if not q:
        return [], [], ["news_search: empty query"]
    terms = parse_terms(q)

    feeds = _resolve_feeds(options)
    if not feeds:
        return [], [], ["news_search: no feeds configured — add feeds in the "
                        "Owner console (Settings → RSS-Feeds)."]

    max_age = int((options or {}).get("max_age_days") or DEFAULT_MAX_AGE_DAYS)
    # Operator-configured cap wins over the env default.
    max_results = int((options or {}).get("max_results") or MAX_RESULTS)
    cutoff = datetime.utcnow() - timedelta(days=max_age)

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT,
                 "Accept": "application/rss+xml,application/atom+xml,"
                           "application/xml,text/xml,*/*"},
    ) as client:
        results = await asyncio.gather(
            *(_fetch_feed(client, sem, f) for f in feeds))

    hits: list[tuple[dict, dict]] = []
    scanned = 0
    dead: list[str] = []
    for feed, entries, err in results:
        if err:
            dead.append(f"{feed.get('name', feed.get('id', '?'))} ({err})")
            continue
        scanned += len(entries)
        for e in entries:
            if e["published"] and e["published"] < cutoff:
                continue
            if _matches(e, terms):
                hits.append((feed, e))

    # A dead feed is not "no results" — say which ones failed, or an analyst
    # reads an incomplete sweep as an absence of coverage.
    if dead:
        notes.append(NOTE_PREFIX + f"{len(dead)} of {len(feeds)} feeds "
                                   f"unreachable: {', '.join(dead[:5])}"
                                   + (" …" if len(dead) > 5 else ""))
    if not hits:
        notes.append(NOTE_PREFIX + f"No match for '{q}' in {scanned} entries "
                                   f"across {len(feeds) - len(dead)} feeds.")
        return [], [], errors + notes

    # Newest first — recency is what an analyst wants from a news sweep.
    hits.sort(key=lambda t: t[1]["published"] or datetime.min, reverse=True)
    if len(hits) > max_results:
        notes.append(NOTE_PREFIX + f"{len(hits)} matches, showing the "
                                   f"{max_results} most recent.")
        hits = hits[:max_results]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    seen: set[str] = set()
    for feed, e in hits:
        label = e["title"][:200]
        if label in seen:          # same story syndicated across feeds
            continue
        seen.add(label)
        published = e["published"].strftime("%Y-%m-%d") if e["published"] else ""
        findings.append(Finding(
            entity_type="news_article",
            platform=feed.get("name", feed.get("id", "feed")),
            label=label,
            url=e["url"] or None,
            # The article's publication date, not the moment we searched.
            # For a news item that IS the fact being reported.
            found_at=e["published"] or None,
            # Official bodies outrank media for evidentiary purposes; the
            # confidence reflects the SOURCE, not the truth of the content.
            confidence=0.8 if feed.get("kind") in ("authority", "police") else 0.6,
            data={"title": e["title"], "summary": e["summary"][:600],
                  # Passage containing the search term, for the reading view.
                  "match_context": _context(e, terms),
                  "matched_terms": [t for t in terms
                                    if t in f"{e['title']} {e['summary']}".lower()],
                  "url": e["url"], "published": published,
                  "source_name": feed.get("name"), "source_kind": feed.get("kind"),
                  "source_lang": feed.get("lang"), "query": q,
                  "source": "news_search"},
        ))
        # Endpoint must equal the finding key "{entity_type}:{label}".
        edges.append(EdgeResult(
            from_entity=f"keyword:{query}",
            to_entity=f"news_article:{label}",
            relation="mentioned_in_news",
            confidence=0.7,
        ))

    notes.append(NOTE_PREFIX + f"Searched {scanned} entries across "
                               f"{len(feeds) - len(dead)} feeds.")
    return findings, edges, errors + notes
