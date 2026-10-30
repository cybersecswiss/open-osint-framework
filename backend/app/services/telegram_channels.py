"""Operator-managed Telegram channel list for the username sweep.

Stored in the license-server's `platform-settings` under a single JSON key,
exactly like the RSS feeds and the API keys — operator-global, editable from
the Owner console, effective immediately without a container restart. The
list is handed to module-messenger per search (`options.channels`), so the
module never talks to the license-server itself.

**Why `enabled` is a separate flag, and why imports default to OFF.**
Every username search sweeps the ACTIVE list, so the list size is a direct
cost on every such search — the module caps it at
`TELEGRAM_HUNT_MAX_CHANNELS` (40 by default) precisely for that reason.
deepdarkCTI alone yields ~961 handles. Importing them all as active would
turn a 60-second search into a hopeless one and, worse, silently truncate to
whatever 40 happened to sort first. So the store holds the whole pool as a
reference and `enabled` marks the subset that is actually swept. That is the
same split the bundled `crime_channels.txt` / `crime_channels.reference.txt`
files already expressed — just manageable now.

Channels are NOT secret: they are public handles, stored in clear.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.safe_fetch import BlockedURL, assert_public_url

log = logging.getLogger("osint.telegram_channels")

STORE_KEY = "TELEGRAM_CHANNELS_JSON"

_TTL = 30.0
_cache: dict[str, tuple[float, list[dict]]] = {}

# Public, community-maintained CTI. The repo is the source the bundled list
# was originally extracted from, so an operator refreshing from here gets the
# same provenance rather than a second, differently-curated universe.
DDCTI_RAW = "https://raw.githubusercontent.com/fastfire/deepdarkCTI/main/{}"
DDCTI_FILES: dict[str, str] = {
    "telegram_threat_actors.md": "threat_actor",
    "telegram_infostealer.md": "infostealer",
    "ransomware_gang.md": "ransomware",
    "forum.md": "forum",
    "markets.md": "market",
    "maas.md": "maas",
    "exploits.md": "exploits",
    "commercial_services.md": "service",
}

# t.me paths that are not channel handles.
_NOT_HANDLES = {
    "joinchat", "s", "c", "share", "addstickers", "proxy", "iv", "socks",
    "addtheme", "setlanguage", "confirmphone", "login",
}

_HANDLE_RE = re.compile(r"[A-Za-z0-9_]{3,32}")


def normalize_handle(value: str) -> str:
    """`https://t.me/Foo`, `@foo`, `foo` → `foo` (lower-cased).

    Lower-cased on purpose: Telegram handles are case-insensitive, and
    storing two casings of one channel would sweep it twice and show the
    operator a channel count that is wrong.
    """
    v = str(value or "").strip()
    if not v:
        return ""
    v = re.sub(r"^https?://", "", v, flags=re.I)
    v = re.sub(r"^(www\.)?t(elegram)?\.me/", "", v, flags=re.I)
    v = v.split("?", 1)[0].split("/", 1)[0].lstrip("@").strip()
    if not v or v.lower() in _NOT_HANDLES:
        return ""
    m = _HANDLE_RE.fullmatch(v)
    return v.lower() if m else ""


# Liveness, as far as an unauthenticated fetch of t.me/<handle> can tell.
#
#   alive          — the public channel page renders (title + subscriber line)
#   no_public_page — it does not. Measured against known-good and known-bad
#                    handles, this is the same signature a deleted channel and
#                    an INVITE-ONLY one produce. It is therefore a candidate
#                    for cleanup, never a verdict: deleting on this signal
#                    alone would throw away exactly the private crime channels
#                    that are worth watching.
#   error          — the check itself failed (network, rate limit). Never
#                    treated as evidence about the channel.
STATUS_ALIVE = "alive"
STATUS_NO_PAGE = "no_public_page"
STATUS_ERROR = "error"


def normalize(chan: dict) -> dict:
    handle = normalize_handle(chan.get("handle") or chan.get("url") or "")
    return {
        "id": str(chan.get("id") or uuid.uuid4()),
        "handle": handle,
        "category": (str(chan.get("category") or "other").strip().lower())[:32],
        "note": (str(chan.get("note") or "").strip())[:200],
        "source": (str(chan.get("source") or "manual").strip())[:40],
        "enabled": bool(chan.get("enabled", False)),
        # Liveness, filled by check_liveness(). "" = never checked, which is
        # deliberately different from "checked and fine".
        "status": (str(chan.get("status") or "").strip())[:20],
        "checked_at": (str(chan.get("checked_at") or "").strip())[:32],
        "title": (str(chan.get("title") or "").strip())[:120],
        "subscribers": (str(chan.get("subscribers") or "").strip())[:40],
        # Parsed audience size, for sorting and for picking what to sweep.
        # Kept apart from the raw string because t.me writes several shapes
        # ("4 467 subscribers", "8 152 members, 278 online") and stripping all
        # non-digits from the second one yields 8152278 — a channel 1000x
        # bigger than it is, which would drive the wrong curation decisions.
        "reach": int(chan.get("reach") or 0),
    }


def _settings_url() -> str:
    return f"{settings.license_server_url}/api/v1/platform-settings"


def _headers() -> dict[str, str]:
    # `internal_secret`, not `internal_key`: the former is a property that
    # falls back to the global secret when no dedicated internal key is set.
    # Using the raw field would send an empty header on any install that has
    # not split its secrets yet — a silent 401 on every save.
    return {"X-Internal-Key": settings.internal_secret}


async def get_channels(force: bool = False) -> list[dict]:
    """Everything the operator stores, enabled or not.

    Degrades to an empty list on any failure: module-messenger then uses its
    bundled file rather than the search dying because the license-server
    hiccuped.
    """
    now = time.time()
    if not force and "ch" in _cache and now - _cache["ch"][0] < _TTL:
        return _cache["ch"][1]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(STORE_KEY)
        items = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
        if not isinstance(items, list):
            items = []
        items = [normalize(c) for c in items if isinstance(c, dict)]
        items = [c for c in items if c["handle"]]
    except Exception as e:  # noqa: BLE001
        log.warning("telegram channel list unavailable (%s) — module file applies", e)
        items = []
    _cache["ch"] = (now, items)
    return items


async def get_active_handles(force: bool = False) -> list[str]:
    """Just the handles that should actually be swept.

    Returned to the orchestrator, which passes them to the module. An empty
    result deliberately means "module, use your own file" — never "sweep
    nothing", because a license-server hiccup must not silently reduce a
    search's coverage to zero.
    """
    return [c["handle"] for c in await get_channels(force) if c["enabled"]]


async def save_channels(items: list[dict]) -> list[dict]:
    """Replace the stored list. Returns the normalized list that was saved."""
    clean: list[dict] = []
    seen: set[str] = set()
    for c in items:
        if not isinstance(c, dict):
            continue
        n = normalize(c)
        if not n["handle"] or n["handle"] in seen:
            continue
        seen.add(n["handle"])
        clean.append(n)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.put(_settings_url(), headers=_headers(),
                             json={"values": {STORE_KEY: json.dumps(clean)}})
        r.raise_for_status()
    _cache.pop("ch", None)
    return clean


def parse_bulk(text: str, category: str = "other",
               source: str = "manual", enabled: bool = False) -> list[dict]:
    """Turn pasted text into channel records.

    Accepts whatever an analyst actually has in the clipboard: one per line,
    comma separated, bare handles, `@handles`, or full `t.me` URLs, with `#`
    comments. Anything that is not a valid handle is dropped rather than
    stored as a channel that can never resolve.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        line = line.split("#", 1)[0]
        for token in re.split(r"[,;\s]+", line):
            h = normalize_handle(token)
            if h and h not in seen:
                seen.add(h)
                out.append(normalize({"handle": h, "category": category,
                                      "source": source, "enabled": enabled}))
    return out


async def fetch_deepdarkcti(files: list[str] | None = None) -> list[dict]:
    """Harvest channel handles from deepdarkCTI, tagged with its category.

    Files that 404 are skipped rather than failing the import: the upstream
    repo renames files from time to time, and one rename must not cost the
    operator the other eight sources.
    """
    wanted = {f: c for f, c in DDCTI_FILES.items()
              if not files or f in set(files)}
    out: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for fname, category in wanted.items():
            try:
                r = await client.get(DDCTI_RAW.format(fname))
                if r.status_code != 200:
                    log.info("deepdarkCTI %s: HTTP %s — skipped", fname, r.status_code)
                    continue
                for raw in re.findall(r"https?://t\.me/([A-Za-z0-9_/?=]+)", r.text):
                    h = normalize_handle(raw)
                    # First file wins the category: the threat-actor list is
                    # requested first and is the more specific statement.
                    if h and h not in out:
                        out[h] = normalize({"handle": h, "category": category,
                                            "source": "deepdarkcti",
                                            "enabled": False})
            except Exception as e:  # noqa: BLE001
                log.warning("deepdarkCTI %s failed: %s", fname, e)
    return list(out.values())


# ── operator-defined harvest sources ─────────────────────────────────

SOURCES_KEY = "TELEGRAM_SOURCES_JSON"

_GH_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)", re.I)


def normalize_source(src: dict) -> dict:
    url = str(src.get("url") or "").strip()
    kind = "github_repo" if _GH_REPO_RE.match(url) else "url"
    return {
        "id": str(src.get("id") or uuid.uuid4()),
        "url": url,
        "kind": kind,
        "category": (str(src.get("category") or "threat_actor").strip().lower())[:32],
        "enabled": bool(src.get("enabled", True)),
        "last_run": (str(src.get("last_run") or "").strip())[:32],
        "last_found": int(src.get("last_found") or 0),
        "last_added": int(src.get("last_added") or 0),
        "last_error": (str(src.get("last_error") or "").strip())[:200],
    }


async def get_sources(force: bool = False) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_settings_url(), headers=_headers())
            r.raise_for_status()
            raw = (r.json() or {}).get(SOURCES_KEY)
        items = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
        if not isinstance(items, list):
            items = []
        return [normalize_source(s) for s in items
                if isinstance(s, dict) and str(s.get("url") or "").strip()]
    except Exception as e:  # noqa: BLE001
        log.warning("telegram source list unavailable: %s", e)
        return []


async def save_sources(items: list[dict]) -> list[dict]:
    clean, seen = [], set()
    for s in items:
        if not isinstance(s, dict):
            continue
        n = normalize_source(s)
        if not n["url"] or n["url"].lower() in seen:
            continue
        seen.add(n["url"].lower())
        clean.append(n)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.put(_settings_url(), headers=_headers(),
                             json={"values": {SOURCES_KEY: json.dumps(clean)}})
        r.raise_for_status()
    return clean


async def _fetch_source_handles(src: dict, client: httpx.AsyncClient) -> set[str]:
    """Every t.me handle a single source yields.

    A GitHub repo URL is expanded to every markdown file it contains, because
    that is how these CTI lists are actually published — one file per
    category, renamed and added over time. Pinning individual file names is
    what made the first deepdarkCTI import return seven 404s.
    """
    out: set[str] = set()
    texts: list[str] = []
    # The URL is operator-supplied. Lower privilege than an analyst's, but the
    # same class of hole: without this an operator (or anyone who got hold of
    # a platform token) could point a "source" at an internal service and read
    # the outcome from the per-source error field.
    await assert_public_url(src["url"])
    m = _GH_REPO_RE.match(src["url"])
    if m:
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/")
        r.raise_for_status()
        names = [f["name"] for f in r.json()
                 if isinstance(f, dict) and str(f.get("name", "")).endswith(".md")]
        for name in names:
            rr = await client.get(
                f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{name}")
            if rr.status_code == 200:
                texts.append(rr.text)
    else:
        r = await client.get(src["url"])
        r.raise_for_status()
        texts.append(r.text)

    for text in texts:
        for raw in re.findall(r"https?://t\.me/([A-Za-z0-9_/?=]+)", text):
            h = normalize_handle(raw)
            if h:
                out.add(h)
    return out


async def harvest_sources(only_id: str | None = None) -> dict:
    """Scan every enabled source and fold new handles into the pool.

    New channels arrive DISABLED, for the same reason imports do: the pool is
    a reference, the enabled set is what every username search pays for.

    Per-source outcome (count, error, timestamp) is written back so a source
    that quietly stopped yielding anything is visible in the console instead
    of being discovered months later.
    """
    sources = await get_sources(force=True)
    existing = await get_channels(force=True)
    total_found = 0
    total_added = 0
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for src in sources:
            if not src["enabled"] or (only_id and src["id"] != only_id):
                continue
            try:
                handles = await _fetch_source_handles(src, client)
                incoming = [normalize({"handle": h, "category": src["category"],
                                       "source": _short_source(src["url"]),
                                       "enabled": False}) for h in handles]
                existing, added, _ = merge(existing, incoming)
                src.update(last_run=stamp, last_found=len(handles),
                           last_added=added, last_error="")
                total_found += len(handles)
                total_added += added
            except Exception as e:  # noqa: BLE001
                src.update(last_run=stamp, last_error=f"{type(e).__name__}: {e}"[:200])
                log.warning("telegram source %s failed: %s", src["url"], e)

    saved = await save_channels(existing)
    await save_sources(sources)
    return {"found": total_found, "added": total_added, "total": len(saved),
            "enabled": sum(1 for c in saved if c["enabled"]),
            "sources": len([s for s in sources if s["enabled"]])}


def _short_source(url: str) -> str:
    m = _GH_REPO_RE.match(url)
    if m:
        return f"gh:{m.group(2).removesuffix('.git')}"[:40]
    return url.rsplit("/", 1)[-1][:40] or "url"


# ── liveness ─────────────────────────────────────────────────────────

_UA = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
       "Gecko/20100101 Firefox/115.0")
_TITLE_RE = re.compile(r'tgme_page_title"[^>]*>\s*<span[^>]*>([^<]{0,80})')
_EXTRA_RE = re.compile(r'tgme_page_extra"[^>]*>([^<]{0,60})')
# Only the FIRST number, and only when it precedes members/subscribers.
_REACH_RE = re.compile(r"([\d\s\u202f\u00a0]+?)\s*(?:members|subscribers)", re.I)


def parse_reach(extra: str) -> int:
    m = _REACH_RE.search(extra or "")
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else 0


async def check_liveness(handles: list[str], concurrency: int = 8) -> dict[str, dict]:
    """Unauthenticated liveness probe against `t.me/<handle>`.

    Deliberately keyless. The authoritative check is resolving the handle
    through the collection account, but doing that for a thousand handles is
    how an account earns a flood-wait or worse — and the account here is a
    real one whose loss would cost every authenticated Telegram tool.

    Verified against known-good and known-bad handles: a live public channel
    renders `tgme_page_title` plus a subscriber line, a non-existent one
    renders neither. An INVITE-ONLY channel is indistinguishable from a
    deleted one here, which is why the result is `no_public_page` and not
    `dead`.
    """
    sem = asyncio.Semaphore(max(1, concurrency))
    out: dict[str, dict] = {}
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    async def one(client: httpx.AsyncClient, h: str) -> None:
        async with sem:
            try:
                r = await client.get(f"https://t.me/{h}")
                body = r.text if r.status_code == 200 else ""
                if 'tgme_page_title' in body:
                    tm, em = _TITLE_RE.search(body), _EXTRA_RE.search(body)
                    extra = em.group(1).strip() if em else ""
                    out[h] = {"status": STATUS_ALIVE, "checked_at": stamp,
                              "title": (tm.group(1).strip() if tm else ""),
                              "subscribers": extra,
                              "reach": parse_reach(extra)}
                else:
                    out[h] = {"status": STATUS_NO_PAGE, "checked_at": stamp,
                              "title": "", "subscribers": "", "reach": 0}
            except Exception as e:  # noqa: BLE001
                # An error says nothing about the channel — record it as such
                # so a network hiccup can never be mistaken for a dead channel.
                out[h] = {"status": STATUS_ERROR, "checked_at": stamp,
                          "title": "", "subscribers": f"{type(e).__name__}",
                          "reach": 0}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        await asyncio.gather(*[one(client, h) for h in handles])
    return out


async def apply_liveness(results: dict[str, dict]) -> list[dict]:
    """Write probe results onto the stored channels."""
    items = await get_channels(force=True)
    for c in items:
        r = results.get(c["handle"])
        if r:
            c.update(r)
    return await save_channels(items)


def merge(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int, int]:
    """Add what is new, keep what the operator decided.

    Returns (merged, added, kept). An imported handle that is already stored
    does NOT reset its `enabled` flag, its note or its category — a refresh
    from upstream must never silently un-sweep a channel the operator turned
    on, which would shrink coverage without a word.
    """
    by_handle = {c["handle"]: c for c in existing}
    added = 0
    for c in incoming:
        if c["handle"] in by_handle:
            continue
        by_handle[c["handle"]] = c
        added += 1
    return list(by_handle.values()), added, len(existing)
