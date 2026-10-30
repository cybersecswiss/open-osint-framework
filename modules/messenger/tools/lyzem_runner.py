"""
Global Telegram discovery via Lyzem (keyless).

Telegram exposes no keyless global search, so ``telegram_search`` could
only deep-link out. This tool actually scrapes Lyzem (lyzem.com), a
server-rendered public Telegram index, and returns the discovered
channels as real ``telegram_channel`` findings — lifting the biggest
limitation of the existing search, which was pinned to the curated
crime-channel list (``telegram_username_hunt``).

Design: one node per channel (deduped by canonical ``@handle`` so it
merges with the other Telegram tools), with matching message snippets
carried as ``data.samples`` for context. No separate message nodes — the
keyword→channel fan-out stays clean and avoids shadow edges.
"""
from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from schemas import EdgeResult, Finding
from tools.telegram_common import normalize_handle

LYZEM_URL = "https://lyzem.com/search"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
              "Gecko/20100101 Firefox/115.0")
# Lyzem's own channel — never report it as a hit.
SELF_HANDLE = "lyzemcom"
MAX_CHANNELS = 40
SAMPLES_PER_CHANNEL = 3

log = logging.getLogger("module-messenger.lyzem")


def _extract(html: str) -> dict[str, dict]:
    """Parse a Lyzem results page → {handle: {title, samples[]}}."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, dict] = {}
    for block in soup.select(".search-result"):
        a = block.find("a", href=lambda h: h and "t.me/" in h)
        if not a:
            continue
        handle = normalize_handle(a.get("href", ""))
        if not handle or handle == SELF_HANDLE:
            continue
        title_el = block.select_one(".search-result-title")
        title = (title_el.get_text(" ", strip=True) if title_el else "")[:120]
        snippet = block.get_text(" ", strip=True)[:200]
        rec = out.setdefault(handle, {"title": "", "samples": []})
        if title and not rec["title"]:
            rec["title"] = title
        if snippet and snippet not in rec["samples"] \
                and len(rec["samples"]) < SAMPLES_PER_CHANNEL:
            rec["samples"].append(snippet)
    return out


async def run_telegram_global_search(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    keyword = (query or "").strip()
    if not keyword:
        return [], [], ["Telegram global search: empty keyword"]

    channels: dict[str, dict] = {}
    errors: list[str] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    async with httpx.AsyncClient(timeout=30, headers=headers,
                                 follow_redirects=True) as client:
        # `channels` gives the discovery list, `messages` adds context
        # snippets (and often surfaces channels not in the channel index).
        for typ in ("channels", "messages"):
            try:
                r = await client.get(LYZEM_URL, params={"q": keyword, "type": typ})
                r.raise_for_status()
                for handle, rec in _extract(r.text).items():
                    ex = channels.get(handle)
                    if ex is None:
                        channels[handle] = rec
                    else:
                        if not ex["title"] and rec["title"]:
                            ex["title"] = rec["title"]
                        for s in rec["samples"]:
                            if s not in ex["samples"] \
                                    and len(ex["samples"]) < SAMPLES_PER_CHANNEL:
                                ex["samples"].append(s)
            except Exception as e:  # noqa: BLE001
                errors.append(f"Lyzem {typ}: {type(e).__name__}: {e}")
                log.warning("lyzem %s fetch failed for %r: %s", typ, keyword, e)

    if not channels:
        return [], [], errors or ["Telegram global search: no results"]

    kw = keyword.lower()
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    for handle, rec in list(channels.items())[:MAX_CHANNELS]:
        findings.append(Finding(
            entity_type="telegram_channel", platform="telegram",
            label=f"@{handle}", url=f"https://t.me/{handle}", confidence=0.5,
            data={"handle": handle, "title": rec["title"], "keyword": keyword,
                  "samples": rec["samples"], "source": "lyzem",
                  "url": f"https://t.me/{handle}"},
        ))
        edges.append(EdgeResult(
            from_entity=f"keyword:{kw}",
            to_entity=f"telegram_channel:@{handle}",
            relation="mentions", confidence=0.5,
        ))
    # Real hits found → transient per-endpoint noise is non-fatal.
    return findings, edges, []
