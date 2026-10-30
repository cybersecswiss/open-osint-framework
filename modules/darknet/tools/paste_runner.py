"""
Paste-site search.

The classic psbdmp.ws / psbdmp.cc API is dead. We replace it with a
`site:` query against DuckDuckGo's HTML mirror, fanned out across the
major paste hosts. DuckDuckGo HTML is keyless and has predictable
selectors.

Two-stage filter to keep only real paste pages (DDG also returns
homepages, search-result pages, dead links, and old pastes that
mention the term in passing):

  1. URL-shape allowlist: each site has a regex describing what a
     real paste URL looks like (paste ID slug). Generic root URLs,
     /search, /trends, /faq etc. fail the regex and are dropped.

  2. Content verification: GET each surviving URL, confirm HTTP 200,
     confirm the queried string actually appears in the body
     (case-insensitive). Drops stale/loose-match pastes.

Cap at 50 verified hits per query.
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from schemas import EdgeResult, Finding, NOTE_PREFIX

DDG_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PER_SITE_DDG_TIMEOUT = 15
PER_PASTE_VERIFY_TIMEOUT = 8
MAX_PER_SITE = 15
MAX_TOTAL = 50
VERIFY_CONCURRENCY = 25

# Per-site URL pattern that identifies a *real* paste page.
# host-prefix dropped; we match against the path only.
PASTE_SITES: list[tuple[str, re.Pattern]] = [
    # pastebin.com/<8-char alnum>
    ("pastebin.com",  re.compile(r"^/[A-Za-z0-9]{8}/?$")),
    # ghostbin.co/paste/<id>
    ("ghostbin.co",   re.compile(r"^/paste/[A-Za-z0-9]+/?$")),
    # paste.ee/p/<alnum>
    ("paste.ee",      re.compile(r"^/p/[A-Za-z0-9]+/?$")),
    # controlc.com/<10+ alnum>
    ("controlc.com",  re.compile(r"^/[A-Za-z0-9]{6,}/?$")),
    # rentry.co/<slug>  (avoid /faq, /api, /signup)
    ("rentry.co",     re.compile(r"^/(?!faq$|api|signup|login|terms|privacy)[A-Za-z0-9_-]+/?$")),
    # gist.github.com/<user>/<32hex>
    ("gist.github.com", re.compile(r"^/[A-Za-z0-9_-]+/[a-f0-9]{20,}/?$")),
    # justpaste.it/<id>
    ("justpaste.it",  re.compile(r"^/(?!app|tag|popular|new|terms)[A-Za-z0-9_-]+/?$")),
]

log = logging.getLogger("module-darknet.paste")


class _SourceUnavailable(Exception):
    """The search source refused to answer — distinct from "no results"."""


async def _ddg_site_search(client: httpx.AsyncClient,
                           site: str, pattern: re.Pattern,
                           query: str) -> list[Finding]:
    q = f"site:{site} {query}"
    data = {"q": q, "kl": "wt-wt"}
    try:
        r = await client.post(DDG_URL, data=data,
                              timeout=PER_SITE_DDG_TIMEOUT)
    except httpx.HTTPError as e:
        raise _SourceUnavailable(f"{site}: DuckDuckGo unreachable ({e})") from e
    # DDG answers its anti-bot page with HTTP 202 and an "anomaly" notice
    # instead of an error status. Returning [] there is indistinguishable
    # from "no results", which in an investigation reads as "nothing exists"
    # when the truth is "the source refused to answer" — so say so.
    if r.status_code == 202 or "anomaly" in r.text[:4000].lower():
        raise _SourceUnavailable(
            f"{site}: DuckDuckGo rate-limited this instance (anti-bot page). "
            "Results are INCOMPLETE — retry later.")
    if r.status_code != 200:
        raise _SourceUnavailable(f"{site}: DuckDuckGo HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[Finding] = []
    for res in soup.select("div.result")[:MAX_PER_SITE]:
        a = res.select_one("a.result__a")
        snippet_el = res.select_one(".result__snippet")
        if not a:
            continue
        href = a.get("href") or ""
        # DDG HTML wraps the real URL in /l/?uddg=<encoded>; unwrap it.
        if href.startswith("//duckduckgo.com/l/?") or href.startswith("/l/?"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(
                href if href.startswith("http") else f"https:{href}"
            ).query)
            if qs.get("uddg"):
                href = urllib.parse.unquote(qs["uddg"][0])
        if not href.startswith("http"):
            continue
        parsed = urllib.parse.urlparse(href)
        if site not in parsed.netloc.lower():
            continue
        # URL-shape filter — drop site homepages, search pages, etc.
        if not pattern.match(parsed.path):
            continue
        title = a.get_text(" ", strip=True)[:200]
        snippet = (snippet_el.get_text(" ", strip=True)[:300]
                   if snippet_el else "")
        out.append(Finding(
            entity_type="paste",
            platform=site,
            label=f"{site}:{title[:60] or parsed.path[1:24]}",
            url=href,
            confidence=0.6,  # bumped to 0.85 after body verification
            data={"url": href, "title": title, "snippet": snippet,
                  "site": site, "query": query, "source": "duckduckgo"},
        ))
    return out


async def _verify_paste(client: httpx.AsyncClient,
                        sem: asyncio.Semaphore,
                        f: Finding, query: str) -> Finding | None:
    """Confirm the paste page exists and actually mentions the query."""
    if not f.url:
        return None
    q_low = query.lower()
    async with sem:
        try:
            r = await client.get(f.url, timeout=PER_PASTE_VERIFY_TIMEOUT,
                                 follow_redirects=True)
        except (httpx.TimeoutException, httpx.RequestError):
            return None
    if r.status_code != 200:
        return None
    body = r.text.lower()
    # Many paste sites wrap the actual paste in a <textarea> or <pre>.
    # We just substring-check the whole body — if the search term
    # isn't anywhere on the page, it's a false positive.
    if q_low not in body:
        return None
    new_data = dict(f.data or {})
    new_data["verified_match_in_body"] = True
    return f.copy(update={"confidence": 0.85, "data": new_data})


async def run_paste_search(query: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
    }
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        async with httpx.AsyncClient(headers=headers,
                                     follow_redirects=True) as client:
            # 1. DDG fan-out
            results = await asyncio.gather(
                *[_ddg_site_search(client, site, pat, query)
                  for site, pat in PASTE_SITES],
                return_exceptions=True,
            )
            raw: list[Finding] = []
            blocked: list[str] = []
            for res in results:
                if isinstance(res, list):
                    raw.extend(res)
                elif isinstance(res, _SourceUnavailable):
                    blocked.append(str(res))
                elif isinstance(res, Exception):
                    errors.append(f"DDG site-search error: {res}")
            # An unavailable source is not an empty result. Report it as a
            # real error when EVERY site was blocked (the run found nothing
            # and cannot claim to have looked), otherwise as a note.
            if blocked:
                if not raw and len(blocked) == len(PASTE_SITES):
                    errors.append(
                        f"paste_search: all {len(blocked)} paste sites could "
                        "not be searched — " + blocked[0])
                else:
                    errors.append(
                        f"{NOTE_PREFIX}paste_search: {len(blocked)} of "
                        f"{len(PASTE_SITES)} sites unavailable, results are "
                        "incomplete — " + blocked[0])
            raw_count = len(raw)

            # 2. Body verification
            sem = asyncio.Semaphore(VERIFY_CONCURRENCY)
            verified = await asyncio.gather(
                *[_verify_paste(client, sem, f, query) for f in raw],
                return_exceptions=True,
            )
    except Exception as e:  # noqa: BLE001
        return [], [], [f"DDG paste search error: {e}"]

    for v in verified:
        if isinstance(v, Finding):
            findings.append(v)
        if len(findings) >= MAX_TOTAL:
            break

    dropped = raw_count - len(findings)
    if dropped > 0:
        errors.append(f"{NOTE_PREFIX}paste_search: {dropped} results filtered "
                      f"({len(findings)}/{raw_count} verified to mention '{query}')")

    for f in findings:
        edges.append(EdgeResult(
            from_entity=f"keyword:{query}",
            # Must be the finding's own key ("{entity_type}:{label}"), NOT its
            # URL. Pointing at the URL made graph_builder create a second,
            # virtual node per paste — the snippet data landed on one node and
            # the keyword edge on the other. Same class of bug as the one
            # fixed in the abuseipdb/virustotal/crypto runners.
            to_entity=f"{f.entity_type}:{f.label}",
            relation="mentioned_in_paste",
            confidence=0.85,
        ))
    return findings, edges, errors
