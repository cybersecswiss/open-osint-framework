"""
TGStat channel analytics (keyless scrape).

Enriches a Telegram channel with reach/size signal that Telethon doesn't
give: the subscriber count and channel title from TGStat's public page.
Emits a telegram_channel node with the SAME canonical @handle label as
the other Telegram tools, so it merges into (and enriches) that node.

Note: TGStat's most valuable "similar/related channels" graph is loaded
via their JS/official API and isn't in the static page — that needs the
TGStat API (a later, key-gated upgrade). This runner sticks to what the
public page reliably renders.
"""
from __future__ import annotations

import html
import logging
import re

import httpx

from schemas import EdgeResult, Finding
from tools.telegram_common import normalize_handle

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
              "Gecko/20100101 Firefox/115.0")
# The subscriber figure sits in an <h2> immediately before a "subscribers"
# label on the channel page.
_SUBS_RE = re.compile(
    r"<h2[^>]*>\s*([\d][\d\s.,]*)\s*</h2>\s*<div[^>]*>\s*subscribers",
    re.I)
_TITLE_RE = re.compile(r'og:title"\s+content="([^"]+)"', re.I)

log = logging.getLogger("module-messenger.tgstat")


def _to_int(raw: str) -> int | None:
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


async def run_tgstat(
    query: str, options: dict | None = None, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    handle = normalize_handle(query)
    if not handle:
        return [], [], [f"TGStat: '{query}' is not a valid channel handle"]

    url = f"https://tgstat.com/channel/@{handle}"
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers,
                                     follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 404:
                return [], [], [f"TGStat: channel @{handle} not indexed"]
            if r.status_code != 200:
                return [], [], [f"TGStat HTTP {r.status_code}"]
            html_text = r.text
    except httpx.TimeoutException:
        return [], [], ["TGStat timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"TGStat error: {e}"]

    subs_m = _SUBS_RE.search(html_text)
    subscribers = _to_int(subs_m.group(1)) if subs_m else None
    title = None
    title_m = _TITLE_RE.search(html_text)
    if title_m:
        raw = html.unescape(title_m.group(1))
        # og:title is: Telegram channel "NAME" — @handle — TGStat
        quoted = re.search(r'"([^"]+)"', raw)
        title = quoted.group(1) if quoted else raw.split("—")[0].strip()

    if subscribers is None and not title:
        return [], [], ["TGStat: no data parsed for @" + handle]

    finding = Finding(
        entity_type="telegram_channel", platform="telegram",
        label=f"@{handle}", url=f"https://t.me/{handle}", confidence=0.55,
        data={"handle": handle, "title": title, "subscribers": subscribers,
              "tgstat_url": url, "url": f"https://t.me/{handle}",
              "source": "tgstat"},
    )
    return [finding], [], []
