"""
Operator-managed RSS/news feed list.

Stored in the license-server's `platform-settings` under a single JSON key,
exactly like the OSINT API keys — operator-global, editable from the Owner
console, effective immediately without a container restart.

The list is handed to module-news per search (`options.feeds`), so the
module never talks to the license-server itself. When nothing is stored,
the module falls back to its own verified `feeds.json`, so a fresh install
searches something sensible on day one.

Feeds are NOT secret: they are public URLs, stored in clear. The Fernet
layer used for API keys would only obscure them from the operator who
maintains them.
"""
from __future__ import annotations

import json
import logging
import time
import uuid

import httpx

from app.config import settings

log = logging.getLogger("osint.news_feeds")

STORE_KEY = "NEWS_FEEDS_JSON"
SETTINGS_KEY = "NEWS_SETTINGS_JSON"
HEALTH_KEY = "NEWS_HEALTH_JSON"
HARVEST_KEY = "NEWS_HARVEST_JSON"

# Placeholder an operator can put in a feed URL instead of hard-coding a
# number. admin.ch's feeds take `end_index=<n>`; writing `end_index={{max}}`
# lets one setting drive every such feed, so raising coverage is one edit
# instead of 20.
MAX_PLACEHOLDER = "{{max}}"

DEFAULT_SETTINGS = {
    # Entries requested per feed (substituted for {{max}}).
    "max_entries_per_feed": 200,
    # Hits returned to the analyst per search.
    "max_results": 60,
    # Ignore entries older than this (days). 0 = no age limit.
    "max_age_days": 1825,
}

# Background-harvester schedule, operator-tunable in the Owner console.
# The harvester (app.services.news_store) polls each feed on the interval
# for its kind: authority/police/cyber use the "authority" interval, the
# rest use the "other" one. `enabled=False` pauses harvesting entirely
# (the manual "run now" button still forces a fetch).
DEFAULT_HARVEST = {
    "enabled": True,
    "authority_interval_min": 60,
    "other_interval_min": 30,
}
_TTL = 30.0
_cache: dict[str, tuple[float, list[dict]]] = {}

# Source categories. They reach the graph and the analyst UI, so an
# investigator can weigh a federal press release differently from a tech
# blog. Adding one here also makes it selectable in the Owner console.
VALID_KINDS = ("authority", "police", "media", "tech", "cyber", "other")


def _settings_url() -> str:
    return f"{settings.license_server_url}/api/v1/platform-settings"


def _headers() -> dict[str, str]:
    return {"X-Internal-Key": settings.internal_secret}


def normalize(feed: dict) -> dict:
    """Coerce one operator-supplied entry into the stored shape.

    Ids are generated when missing so the console can address a row, and
    kept once assigned so edits don't orphan a row's identity.
    """
    url = str(feed.get("url") or "").strip()
    kind = str(feed.get("kind") or "other").strip().lower()
    if kind not in VALID_KINDS:
        kind = "other"
    return {
        "id": str(feed.get("id") or uuid.uuid4().hex[:12]),
        "name": (str(feed.get("name") or "").strip() or url)[:120],
        "url": url,
        "kind": kind,
        "lang": (str(feed.get("lang") or "").strip().lower() or "de")[:5],
        "enabled": bool(feed.get("enabled", True)),
    }


async def get_feeds(force: bool = False) -> list[dict]:
    """Operator-configured feeds, or [] when none are stored.

    Degrades to an empty list on any failure: module-news then uses its
    built-in defaults rather than the search dying because the
    license-server hiccuped.
    """
    now = time.time()
    if not force and "feeds" in _cache and now - _cache["feeds"][0] < _TTL:
        return _cache["feeds"][1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(STORE_KEY)
        feeds = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
        if not isinstance(feeds, list):
            feeds = []
        feeds = [normalize(f) for f in feeds if isinstance(f, dict) and f.get("url")]
    except Exception as e:  # noqa: BLE001
        log.warning("news feed list unavailable (%s) — module defaults apply", e)
        feeds = []
    _cache["feeds"] = (now, feeds)
    return feeds


def _clamp(v, lo, hi, fallback):
    try:
        n = int(v)
    except Exception:  # noqa: BLE001
        return fallback
    return max(lo, min(hi, n))


async def get_settings(force: bool = False) -> dict:
    """Operator-tunable search limits. Falls back to DEFAULT_SETTINGS."""
    now = time.time()
    if not force and "settings" in _cache and now - _cache["settings"][0] < _TTL:
        return _cache["settings"][1]
    out = dict(DEFAULT_SETTINGS)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(SETTINGS_KEY)
        stored = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
        if isinstance(stored, dict):
            out.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    except Exception as e:  # noqa: BLE001
        log.warning("news settings unavailable (%s) — defaults apply", e)
    # Clamp: a feed asked for 100000 entries would hang every search.
    out["max_entries_per_feed"] = _clamp(out["max_entries_per_feed"], 10, 1000, 200)
    out["max_results"] = _clamp(out["max_results"], 5, 500, 60)
    out["max_age_days"] = _clamp(out["max_age_days"], 0, 10000, 1825)
    _cache["settings"] = (now, out)
    return out


async def save_settings(values: dict) -> dict:
    clean = {k: values[k] for k in DEFAULT_SETTINGS if k in values}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(_settings_url(), headers=_headers(),
                             json={"values": {SETTINGS_KEY: json.dumps(clean)}})
        r.raise_for_status()
    _cache.pop("settings", None)
    return await get_settings(force=True)


async def get_harvest_settings(force: bool = False) -> dict:
    """Background-harvester schedule. Falls back to DEFAULT_HARVEST."""
    now = time.time()
    if not force and "harvest" in _cache and now - _cache["harvest"][0] < _TTL:
        return _cache["harvest"][1]
    out = dict(DEFAULT_HARVEST)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(HARVEST_KEY)
        stored = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
        if isinstance(stored, dict):
            out.update({k: v for k, v in stored.items() if k in DEFAULT_HARVEST})
    except Exception as e:  # noqa: BLE001
        log.warning("harvest settings unavailable (%s) — defaults apply", e)
    out["enabled"] = bool(out.get("enabled", True))
    # Clamp intervals to a sane range (5 min … 24 h): a 1-minute interval
    # would hammer the feeds, a 0 would divide-by-zero the due check.
    out["authority_interval_min"] = _clamp(out["authority_interval_min"], 5, 1440, 60)
    out["other_interval_min"] = _clamp(out["other_interval_min"], 5, 1440, 30)
    _cache["harvest"] = (now, out)
    return out


async def save_harvest_settings(values: dict) -> dict:
    clean: dict = {}
    if "enabled" in values:
        clean["enabled"] = bool(values["enabled"])
    for k in ("authority_interval_min", "other_interval_min"):
        if k in values:
            clean[k] = values[k]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(_settings_url(), headers=_headers(),
                             json={"values": {HARVEST_KEY: json.dumps(clean)}})
        r.raise_for_status()
    _cache.pop("harvest", None)
    return await get_harvest_settings(force=True)


async def get_health() -> dict[str, dict]:
    """Per-feed fetch health, merged from two sources.

    The module holds live state but loses it on restart; the persisted copy
    keeps `failing_since` across restarts. Without that, restarting a
    container would reset every failure clock and a source that has been
    dead for a week would look like it just broke.
    """
    stored: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(HEALTH_KEY)
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
        if isinstance(parsed, dict):
            stored = parsed
    except Exception as e:  # noqa: BLE001
        log.warning("stored feed health unavailable: %s", e)

    live: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{settings.module_news_url}/feed-health")
            r.raise_for_status()
            live = (r.json() or {}).get("health") or {}
    except Exception as e:  # noqa: BLE001
        log.warning("module feed health unavailable: %s", e)

    merged: dict[str, dict] = {}
    now = time.time()
    for url in set(stored) | set(live):
        s_ = stored.get(url) or {}
        l_ = live.get(url) or {}
        last_ok = max(float(s_.get("last_ok") or 0), float(l_.get("last_ok") or 0))
        last_error = max(float(s_.get("last_error") or 0), float(l_.get("last_error") or 0))
        fails = int(l_.get("fails") or s_.get("fails") or 0)
        # failing_since: keep the persisted start of the current outage; a
        # success clears it, so the clock only runs for an ongoing problem.
        failing_since = s_.get("failing_since")
        if fails and last_error > last_ok:
            if not failing_since:
                failing_since = last_error or now
        else:
            failing_since = None
        merged[url] = {
            "last_ok": last_ok or None,
            "last_error": last_error or None,
            "error": l_.get("error") or (s_.get("error") if last_error > last_ok else None),
            "fails": fails,
            "entries": l_.get("entries") or s_.get("entries"),
            "failing_since": failing_since,
        }

    if merged != stored:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.put(_settings_url(), headers=_headers(),
                                 json={"values": {HEALTH_KEY: json.dumps(merged)}})
        except Exception as e:  # noqa: BLE001
            log.warning("could not persist feed health: %s", e)
    return merged


def apply_placeholders(feeds: list[dict], settings_values: dict) -> list[dict]:
    """Substitute {{max}} in feed URLs with the configured entry count.

    Done here, right before the module call, so the stored URL keeps the
    placeholder and one setting change re-tunes every feed at once.
    """
    n = str(settings_values.get("max_entries_per_feed",
                                DEFAULT_SETTINGS["max_entries_per_feed"]))
    out = []
    for f in feeds:
        g = dict(f)
        if MAX_PLACEHOLDER in g.get("url", ""):
            g["url"] = g["url"].replace(MAX_PLACEHOLDER, n)
        out.append(g)
    return out


async def save_feeds(feeds: list[dict]) -> list[dict]:
    """Replace the stored list. Returns the normalized list that was saved."""
    clean = [normalize(f) for f in feeds if isinstance(f, dict) and str(f.get("url") or "").strip()]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(_settings_url(), headers=_headers(),
                             json={"values": {STORE_KEY: json.dumps(clean)}})
        r.raise_for_status()
    _cache.pop("feeds", None)
    return clean


async def probe_feed(url: str) -> dict:
    """Fetch a feed once and report whether it yields entries.

    The console offers this as a Test button: an operator adding a cantonal
    police feed gets an immediate answer instead of discovering weeks later
    that a search silently covered one source less. Deliberately reports
    the entry count — a 200 that parses to zero items is the common failure
    (an HTML page served where a feed was expected).
    """
    ua = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0")
    try:
        # Operator-supplied URL — same guard as everywhere else. The Test
        # button reports its outcome, so an unguarded fetch here would be a
        # neat little internal-network prober.
        from app.services.safe_fetch import BlockedURL, assert_public_url
        try:
            await assert_public_url(url)
        except BlockedURL:
            return {"ok": False, "detail": "URL does not point at a public host."}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": ua}) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code,
                    "detail": f"HTTP {r.status_code}"}
        body = r.text
        count = body.count("<item") + body.count("<entry")
        if count == 0:
            return {"ok": False, "status": 200, "entries": 0,
                    "detail": "Reachable, but contains no RSS/Atom entries — "
                              "is this a feed URL or an HTML page?"}
        title = ""
        m = body.find("<title")
        if m != -1:
            seg = body[m:m + 300]
            s, e = seg.find(">"), seg.find("</title")
            if s != -1 and e != -1:
                title = seg[s + 1:e].replace("<![CDATA[", "").replace("]]>", "").strip()[:120]
        return {"ok": True, "status": 200, "entries": count, "title": title,
                "detail": f"{count} entries"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:120]}"}
