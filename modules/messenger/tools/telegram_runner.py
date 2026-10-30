"""
Telegram OSINT tools (search-oriented, not monitoring).

Three tools, each with a keyless default and an optional Telethon
enhancement (see telegram_common / telegram_telethon):

* ``telegram_channel``        — collect a channel's posts + metadata
* ``telegram_search``         — discover channels by keyword
* ``telegram_message_search`` — find messages matching a keyword in a
                                 channel

Keyless works with zero credentials (public web preview). When a
Telethon StringSession is configured the same tools transparently upgrade
to full history, views/forwards, translation and media download. If the
authenticated path fails at runtime we fall back to keyless and note it,
so a search never dies just because a session expired.
"""
from __future__ import annotations

import asyncio
import logging

from schemas import EdgeResult, Finding
from tools.telegram_common import (
    fetch_preview,
    load_config,
    load_crime_channels,
    normalize_handle,
    parse_inline_options,
    sanitize_username,
    split_channel_keyword,
)

log = logging.getLogger("module-messenger.telegram")

# Public Telegram search engines the analyst can click through when the
# keyless path can't do real discovery (Telegram exposes no keyless
# channel search). Same "deep-link finding" idiom the module already
# uses for tgstat analytics.
SEARCH_ENGINES = [
    ("tgstat", "https://tgstat.com/search?q={q}"),
    ("telemetr", "https://telemetr.io/en/channels?query={q}"),
    ("lyzem", "https://lyzem.com/search?q={q}&type=channels"),
    ("telegago", "https://cse.google.com/cse?cx=006368593537057042503:efxu7xprihg&q={q}"),
]


def _tgstat_deeplink(handle: str) -> tuple[Finding, EdgeResult]:
    """The membership/analytics deep-link kept from the original tool —
    Telegram hides public-channel member lists on the clearnet."""
    f = Finding(
        entity_type="search_link", platform="tgstat",
        label=f"tgstat:{handle}", url=f"https://tgstat.com/channel/@{handle}",
        confidence=0.5,
        data={"channel": handle,
              "note": "tgstat.com aggregates subscriber/member analytics for "
                      "public Telegram channels — open in browser to inspect "
                      "membership trends and top contributors.",
              "source": "tgstat"})
    # Endpoint label must match the channel finding's label (@handle) so
    # the edge attaches to the real node instead of spawning a virtual
    # duplicate in the graph builder.
    e = EdgeResult(from_entity=f"telegram_channel:@{handle}",
                   to_entity=f"search_link:tgstat:{handle}",
                   relation="analytics_at", confidence=0.5)
    return f, e


async def run_telegram_channel(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    cfg = load_config(options)
    cleaned, inline = parse_inline_options(query)
    options = {**(options or {}), **inline}
    handle = normalize_handle(cleaned)
    if not handle:
        return [], [], [f"Telegram: invalid channel handle '{query}' "
                        "(expected @name or t.me/name)"]
    limit = int(options.get("limit") or cfg.default_limit)
    days = options.get("days")

    # --- authenticated path (full history / metadata / media) ---
    if cfg.telethon_enabled:
        try:
            from tools.telegram_telethon import collect_channel
            findings, edges, errors = await collect_channel(
                cfg, handle, limit=limit, days=days, job_id=job_id)
            f, e = _tgstat_deeplink(handle)
            findings.append(f)
            edges.append(e)
            return findings, edges, errors
        except Exception as ex:  # noqa: BLE001 — degrade to keyless
            log.warning("telethon channel collect failed, falling back keyless: %s", ex)

    # --- keyless path (public web preview) ---
    meta, errors = await fetch_preview(handle, min(limit, 100))
    if not meta or "title" not in meta:
        return [], [], errors or [f"Telegram channel @{handle} unavailable"]

    findings = [Finding(
        entity_type="telegram_channel", platform="telegram",
        label=f"@{handle}", url=f"https://t.me/{handle}", confidence=0.9,
        data={
            "handle": handle, "title": meta.get("title", handle),
            "description": meta.get("description", ""),
            "subscribers": meta.get("subscribers", ""),
            "photos": meta.get("photos", ""), "videos": meta.get("videos", ""),
            "messages_preview": meta.get("messages", []),
            "message_count": len(meta.get("messages", [])),
            "source": "t.me/s",
            "note": "keyless preview — configure TELEGRAM_SESSION for full "
                    "history, views/forwards, translation and media.",
        })]
    edges: list[EdgeResult] = []
    f, e = _tgstat_deeplink(handle)
    findings.append(f)
    edges.append(e)

    # emails mentioned in the channel bio → edges
    from tools.telegram_common import EMAIL_RE
    for m in EMAIL_RE.finditer(meta.get("description", "")):
        edges.append(EdgeResult(
            from_entity=f"telegram_channel:@{handle}",
            to_entity=f"email:{m.group(0).lower()}",
            relation="mentions", confidence=0.7))
    return findings, edges, errors


async def run_telegram_search(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    cfg = load_config(options)
    keyword, inline = parse_inline_options(query)
    keyword = keyword.strip()
    if not keyword:
        return [], [], ["Telegram search: empty keyword"]
    limit = int({**(options or {}), **inline}.get("limit") or 50)

    # --- authenticated path (real global discovery) ---
    if cfg.telethon_enabled:
        try:
            from tools.telegram_telethon import discover_channels
            findings, edges, errors = await discover_channels(cfg, keyword, limit=limit)
            if findings:
                return findings, edges, errors
        except Exception as ex:  # noqa: BLE001
            log.warning("telethon discovery failed, falling back to deep-links: %s", ex)

    # --- keyless path (deep-links to public TG search engines) ---
    findings: list[Finding] = []
    q_enc = keyword.replace(" ", "+")
    for name, tmpl in SEARCH_ENGINES:
        findings.append(Finding(
            entity_type="search_link", platform=name,
            label=f"{name}:{keyword}", url=tmpl.format(q=q_enc), confidence=0.4,
            data={"engine": name, "keyword": keyword,
                  "note": "Keyless channel discovery isn't offered by Telegram; "
                          "open this public search engine to find channels, or "
                          "configure TELEGRAM_SESSION for in-app discovery.",
                  "source": "deeplink"}))
    edges = [EdgeResult(from_entity=f"keyword:{keyword.lower()}",
                        to_entity=f"search_link:{name}:{keyword}",
                        relation="search_via", confidence=0.4)
             for name, _ in SEARCH_ENGINES]
    return findings, edges, []


def _hunt_findings(username: str, per_channel: list[dict], source: str
                   ) -> tuple[list[Finding], list[EdgeResult]]:
    """Turn per-channel hits into a channel finding + a
    ``username → channel`` 'mentioned_in' edge each, so the graph shows
    which crime channels reference the subject."""
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    uk = username.lower()
    for entry in per_channel:
        ch = entry["channel"]
        hits = entry["hits"]
        if not hits:
            continue
        findings.append(Finding(
            entity_type="telegram_message", platform="telegram",
            label=f"@{ch} ∋ {username}", url=f"https://t.me/{ch}",
            confidence=0.8,
            data={"channel": ch, "username": username, "hit_count": len(hits),
                  "messages": hits[:50], "source": source}))
        # Edge endpoint uses the lowercased username to match the search
        # root node (build_graph lowercases the root query key).
        edges.append(EdgeResult(
            from_entity=f"username:{uk}",
            to_entity=f"telegram_message:@{ch} ∋ {username}",
            relation="mentioned_in", confidence=0.8))
    return findings, edges


async def run_telegram_username_hunt(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    """Sweep a curated list of known crime/cybercrime Telegram channels
    for mentions of a username/alias. Hooks the ``username`` query_type
    so an alias search automatically fans out into Telegram."""
    cfg = load_config(options)
    username = sanitize_username(query)
    if not username:
        return [], [], ["Telegram hunt: username too short (min 3 chars)"]
    channels = load_crime_channels(cfg)
    if not channels:
        return [], [], ["Telegram hunt: no crime channels configured "
                        "(edit modules/messenger/config/crime_channels.txt or set "
                        "TELEGRAM_CRIME_CHANNELS)"]

    # --- authenticated path (server-side full-history sweep) ---
    if cfg.telethon_enabled:
        try:
            from tools.telegram_telethon import hunt_username
            per_channel, _errs = await hunt_username(
                cfg, username, channels, per_channel_limit=cfg.hunt_per_channel_limit)
            findings, edges = _hunt_findings(username, per_channel, "telethon_hunt")
            # Per-channel unreachable/private is expected churn, not a tool
            # error; zero mentions is a valid negative result → success.
            return findings, edges, []
        except Exception as ex:  # noqa: BLE001
            log.warning("telethon hunt failed, falling back keyless: %s", ex)

    # --- keyless path (preview-window scan, bounded concurrency) ---
    sem = asyncio.Semaphore(max(1, cfg.hunt_concurrency))
    uk = username.lower()

    async def _scan(handle: str) -> dict | None:
        async with sem:
            meta, _errs = await fetch_preview(handle, 20)  # one preview page, fast
        if not meta or "title" not in meta:
            return None
        hits = [m for m in meta.get("messages", []) if uk in m.get("text", "").lower()]
        return {"channel": handle, "hits": hits} if hits else None

    scanned = await asyncio.gather(*[_scan(h) for h in channels])
    per_channel = [r for r in scanned if r]
    findings, edges = _hunt_findings(username, per_channel, "t.me/s_hunt")
    # Zero mentions is a valid negative result, NOT an error — a hunt that
    # swept the channels but matched nothing returns success with no
    # findings (like every other module on a no-hit search), so the UI
    # shows a clean "0 findings" row instead of a red error row. Coverage
    # is conveyed by the tool-progress row itself (success, 0 findings).
    return findings, edges, []


async def run_telegram_message_search(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    cfg = load_config(options)
    cleaned, inline = parse_inline_options(query)
    handle, keyword = split_channel_keyword(cleaned)
    options = {**(options or {}), **inline}
    if not handle or not keyword:
        return [], [], ["Telegram message search: expected '@channel :: keyword' "
                        "(a channel and a search term)"]
    limit = int(options.get("limit") or cfg.default_limit)

    # --- authenticated path (server-side full-history search) ---
    if cfg.telethon_enabled:
        try:
            from tools.telegram_telethon import search_messages
            findings, edges, errors = await search_messages(
                cfg, handle, keyword, limit=limit)
            return findings, edges, errors
        except Exception as ex:  # noqa: BLE001
            log.warning("telethon message search failed, falling back keyless: %s", ex)

    # --- keyless path (filter the public preview) ---
    meta, errors = await fetch_preview(handle, 100)
    if not meta or "title" not in meta:
        return [], [], errors or [f"Telegram channel @{handle} unavailable"]
    kw = keyword.lower()
    hits = [m for m in meta.get("messages", []) if kw in (m.get("text", "").lower())]
    findings = [Finding(
        entity_type="telegram_message", platform="telegram",
        label=f"@{handle} ~ {keyword}", url=f"https://t.me/{handle}",
        confidence=0.75 if hits else 0.4,
        data={"handle": handle, "keyword": keyword, "hit_count": len(hits),
              "messages": hits, "scanned": len(meta.get("messages", [])),
              "source": "t.me/s",
              "note": "keyless search covers only the public preview window; "
                      "configure TELEGRAM_SESSION to search full history."})]
    edges = [EdgeResult(
        from_entity=f"telegram_message:@{handle} ~ {keyword}",
        to_entity=f"telegram_channel:@{handle}", relation="found_in",
        confidence=0.6)]
    return findings, edges, errors
