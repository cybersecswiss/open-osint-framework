"""
Tor hidden-service search (live results, clearnet + Tor).

Queries several onion search engines in parallel and returns the discovered
hidden services as findings so they show inline in the graph.

**Ahmia is usable again.** This runner previously gave up on it, believing it
could no longer be scraped. The real obstacle is a CSRF nonce: ahmia.fi puts
a hidden input with a RANDOM name AND value on its home page, and a search
without it returns an empty result list (~4 KB, 0 hits) rather than an error.
Carrying the nonce over yields full results (~1 MB, 1400+ hits). On the
sample query "hosting": torch 42 + tordex 81 = 91 unique onions before,
633 after adding Ahmia and tor66 — a 7x increase.

Ahmia runs over **clearnet**, so it also covers the window where the `tor`
container is still bootstrapping (90 s start_period) and every onion engine
is unreachable.

Results are filtered against Ahmia's abuse blacklist (see AhmiaBlacklist).

Engine list, the nonce mechanism and the blacklist were identified from
darkdump (https://github.com/josh0xA/darkdump, MIT, Josh Schiavone). Engines
that tool offers but which were found dead were deliberately left
out: excavator and notevil answer with near-empty pages (<3 KB, 1 link),
onionland's result markup no longer matches any documented selector, and
tordex.cc (clearnet) returns HTTP 522. darkdump's alternative TorDex onion
resolves to the same service as ours.

The public entrypoint is still ``run_ahmia`` and the manifest tool id is
still ``ahmia`` for backward compatibility, but the search is engine-agnostic.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from schemas import NOTE_PREFIX, EdgeResult, Finding
# Shared with modules/forums. It used to be defined here,
# which is exactly why the forums Tor sweep ran unfiltered — see
# onion_blacklist.py. Re-exported for other darknet runners.
from onion_blacklist import (  # noqa: F401
    FILTER_ABUSE, AhmiaBlacklist, screen_hosts,
)

# socks5h → .onion resolution stays Tor-side. Empty ⇒ onion engines are skipped
# (Ahmia over clearnet still runs).
TOR_PROXY = os.getenv("TOR_SOCKS_PROXY", "").strip()

# Tor-Browser-shaped UA; several engines serve a stripped page otherwise.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; rv:115.0) "
              "Gecko/20100101 Firefox/115.0")

# Cap what reaches the graph. Ahmia alone can return 2500 hits for a broad
# term, and dumping those into a case buries the analyst. Engines return
# roughly relevance-ordered results, so the head is the useful part; the note
# reports how many were found in total so nothing is silently hidden.
MAX_RESULTS = int(os.getenv("DARKNET_MAX_RESULTS", "40") or 40)

# FILTER_ABUSE is imported from onion_blacklist above. It is on by default:
# it keeps investigators from being pointed at abuse material they did not
# ask for. Set DARKNET_FILTER_ABUSE=false for cases where such material IS
# the target of the investigation — the count of filtered hits is always
# reported either way.

ONION_RE = re.compile(r"([a-z2-7]{56}|[a-z2-7]{16})\.onion")

AHMIA_CLEARNET = "https://ahmia.fi"
AHMIA_SEARCH = f"{AHMIA_CLEARNET}/search/"

# Server-rendered onion search engines. A None value means "the query".
ONION_ENGINES = [
    {"name": "torch",
     "url": "http://torchdeedp3i2jigzjdmfpn5ttjhthh5wbmda2rr3jvqjg5p77c54dqd.onion/search",
     "params": {"query": None}},
    {"name": "tordex",
     "url": "http://tordexu73joywapk2txdr54jed4imqledpcvcuf75qsas2gwdgksvnyd.onion/search",
     "params": {"query": None}},
    {"name": "tor66",
     "url": "http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion/search",
     "params": {"q": None, "sorttype": "rel"}},
]

# The engines' own hosts + Ahmia's self-mirror — never report these as hits.
ENGINE_HOSTS = {
    "torchdeedp3i2jigzjdmfpn5ttjhthh5wbmda2rr3jvqjg5p77c54dqd.onion",
    "tordexu73joywapk2txdr54jed4imqledpcvcuf75qsas2gwdgksvnyd.onion",
    "tordexpmg4xy32rfp4ovnz7zq5ujoejwq2u26uxxtkscgo5u3losmeid.onion",
    "tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion",
    "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion",
}

log = logging.getLogger("module-darknet.torsearch")


def _deep_link_finding(query: str) -> Finding:
    return Finding(
        entity_type="search_link",
        platform="ahmia",
        label=f"ahmia:{query}",
        url=f"{AHMIA_SEARCH}?q={urllib.parse.quote_plus(query)}",
        confidence=0.4,
        data={
            "query": query,
            "note": "No search engine returned results; open Ahmia in Tor "
                    "Browser to search manually.",
            "source": "ahmia",
            "url": f"{AHMIA_SEARCH}?q={urllib.parse.quote_plus(query)}",
        },
    )


def _deep_link_edge(query: str) -> EdgeResult:
    return EdgeResult(
        from_entity=f"keyword:{query}",
        to_entity=f"search_link:ahmia:{query}",
        relation="search_link_for",
        confidence=0.4,
    )


def _host_of(href: str) -> str | None:
    m = ONION_RE.search(href or "")
    return m.group(0).lower() if m else None


def _harvest_anchors(html: str) -> dict[str, str]:
    """Return {onion_host: best_title} from a result page's anchors.

    Generic across engines: every engine renders its hits as <a href> to the
    onion URL, so matching on the href avoids per-engine CSS selectors that
    break whenever an engine reskins — which is exactly how onionland's
    documented selector went stale.
    """
    soup = BeautifulSoup(html, "html.parser")
    titles: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        host = _host_of(a["href"])
        if not host or host in ENGINE_HOSTS:
            continue
        text = a.get_text(strip=True)
        # Skip anchors whose text is just the raw URL echo — keep real titles.
        if text.startswith("http") or ".onion" in text:
            text = ""
        if len(text) > len(titles.get(host, "")):
            titles[host] = text[:200]
    return titles


async def _query_onion_engine(client: httpx.AsyncClient, engine: dict,
                              query: str) -> dict[str, str]:
    params = {k: (query if v is None else v) for k, v in engine["params"].items()}
    try:
        r = await client.get(engine["url"], params=params)
        r.raise_for_status()
        return _harvest_anchors(r.text)
    except Exception as e:  # noqa: BLE001
        log.warning("tor engine %s failed: %s", engine["name"], e)
        return {}


async def _query_ahmia(client: httpx.AsyncClient, query: str) -> dict[str, str]:
    """Ahmia over clearnet, carrying its CSRF nonce.

    The home page carries a hidden input whose NAME and VALUE are both
    random. Without it the search returns an empty result list with HTTP 200
    — no error, just nothing, which is what made this look like an
    unscrapeable endpoint.
    """
    try:
        home = await client.get(f"{AHMIA_CLEARNET}/")
        home.raise_for_status()
        soup = BeautifulSoup(home.text, "html.parser")
        params = {"q": query}
        for inp in soup.find_all("input", {"type": "hidden"}):
            if inp.get("name"):
                params[inp["name"]] = inp.get("value", "")
        if len(params) == 1:
            log.warning("ahmia: no hidden nonce found — markup may have changed")
        r = await client.get(AHMIA_SEARCH, params=params)
        r.raise_for_status()
        return _harvest_anchors(r.text)
    except Exception as e:  # noqa: BLE001
        log.warning("ahmia clearnet failed: %s", e)
        return {}


async def run_ahmia(query: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    errors: list[str] = []
    notes: list[str] = []
    merged: dict[str, str] = {}

    # --- clearnet: Ahmia + the blacklist (no Tor required) ---
    # The blacklist is fetched alongside the query rather than after it: it is
    # a clearnet request that does not depend on the result set, so paying for
    # it serially would add its latency to every darknet search.
    async with httpx.AsyncClient(
        timeout=60, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as client:
        if FILTER_ABUSE:
            _, ahmia_hits = await asyncio.gather(
                AhmiaBlacklist.load(client), _query_ahmia(client, query))
        else:
            ahmia_hits = await _query_ahmia(client, query)
    merged.update(ahmia_hits)

    # --- Tor: the onion engines ---
    if TOR_PROXY:
        async with httpx.AsyncClient(
            proxy=TOR_PROXY, timeout=70, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        ) as client:
            results = await asyncio.gather(
                *(_query_onion_engine(client, e, query) for e in ONION_ENGINES))
        for titles in results:
            for host, title in titles.items():
                # First non-empty title wins; keep the entry even if empty.
                if host not in merged or (not merged[host] and title):
                    merged[host] = title
    else:
        notes.append(NOTE_PREFIX + "No TOR_SOCKS_PROXY configured — searched "
                                   "Ahmia over clearnet only, onion engines "
                                   "skipped.")

    if not merged:
        return [_deep_link_finding(query)], [_deep_link_edge(query)], errors + notes

    # --- abuse filtering ---
    # screen_hosts() is shared with modules/forums so both Tor paths withhold
    # the same things and say so in the same words. The list was preloaded
    # concurrently with the Ahmia query above, so this hits the TTL cache and
    # issues no request of its own.
    # `enabled` is passed explicitly rather than left to the shared default so
    # this module's own FILTER_ABUSE binding stays the switch — that is what
    # test_edge_keys.py patches, and a test that silently stops disabling the
    # filter would start making real network calls.
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        merged, screen_notes = await screen_hosts(client, merged,
                                                  enabled=FILTER_ABUSE)
    notes.extend(screen_notes)

    if not merged:
        notes.append(NOTE_PREFIX + "All results were filtered by the abuse "
                                   "blacklist.")
        return [_deep_link_finding(query)], [_deep_link_edge(query)], errors + notes

    if len(merged) > MAX_RESULTS:
        notes.append(NOTE_PREFIX + f"Showing the top {MAX_RESULTS} of "
                                   f"{len(merged)} hidden services found "
                                   "(DARKNET_MAX_RESULTS raises the cap).")

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    for host, title in list(merged.items())[:MAX_RESULTS]:
        # Label MUST be the onion host — it is the node's stable identity and
        # the edge endpoint (`onion_service:<host>`). Keying on the title
        # instead would (a) split one service across engines that title it
        # differently and (b) mismatch the edge → a virtual shadow node.
        # The human-readable title lives in data for the detail view.
        findings.append(Finding(
            entity_type="onion_service",
            platform="tor",
            label=host,
            url=f"http://{host}",
            confidence=0.55,
            data={"onion": host, "title": title, "query": query,
                  "source": "tor_search", "url": f"http://{host}"},
        ))
        edges.append(EdgeResult(
            from_entity=f"keyword:{query}",
            to_entity=f"onion_service:{host}",
            relation="tor_search_match",
            confidence=0.55,
        ))
    return findings, edges, errors + notes
