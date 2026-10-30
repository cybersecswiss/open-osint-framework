"""How many independent blocklists carry this indicator — Bert-JanP catalogue.

A single blocklist hit says very little: lists disagree, copy from each other
and age badly. What carries weight is *agreement between lists that do not
share a source*, which is the same reasoning the framework's own
cross-confirmation is built on. This runner asks that question directly: of
the open feeds that cover this indicator type, how many list it.

The feed catalogue is Bert-JanP/Open-Source-Threat-Intel-Feeds — a maintained
CSV of ~145 feeds with a vendor, a category (IP / DNS / URL / MD5 / SHA256 …)
and, usefully, a FeedStatus column the maintainer keeps current. Offline feeds
are skipped on that flag rather than being probed and reported as failures.

Three bounds, all deliberate and all reported rather than silent:

  * **Feeds per run** (`MAX_FEEDS`) — querying every list of a category would
    mean dozens of requests per search, from one datacenter IP, for every tool
    in a module run. That is precisely how this project rate-limited itself
    out of admin.ch once already. The response says how many of how many were
    consulted.
  * **Bytes per feed** — a feed that answers with tens of megabytes is skipped
    rather than parsed into a 256 MB container.
  * **Cache** — parsed indicator sets are held in-process for an hour, so a
    second search costs nothing. Blocklists move on the scale of hours.

A no-hit answer is a note, never an error and never silence: "checked 18
lists, none carry this address" is a real result an analyst can act on.
"""
from __future__ import annotations

import asyncio
import csv
import io
import ipaddress
import logging
import re
import time
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

CATALOGUE = ("https://raw.githubusercontent.com/Bert-JanP/"
             "Open-Source-Threat-Intel-Feeds/main/ThreatIntelFeeds.csv")
CATALOGUE_URL = "https://github.com/Bert-JanP/Open-Source-Threat-Intel-Feeds"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"

CATALOGUE_TTL = 24 * 3600
FEED_TTL = 3600
FEED_TIMEOUT = 15
MAX_FEEDS = 20          # per run, per category
MAX_FEED_BYTES = 4_000_000
CONCURRENCY = 6

# query_type -> catalogue categories that can answer it
CATEGORIES: dict[str, tuple[str, ...]] = {
    "ip": ("IP",),
    "domain": ("DNS",),
    "url": ("URL",),
    "hash": ("MD5", "SHA1", "SHA256"),
}

log = logging.getLogger("module-threat.ioc_reputation")

_catalogue: list[dict[str, str]] = []
_catalogue_at: float = 0.0
# url -> (fetched_at, set of lowercase indicators)
_feed_cache: dict[str, tuple[float, set[str]]] = {}

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_COMMENT = ("#", ";", "//")


async def _load_catalogue(client: httpx.AsyncClient) -> list[dict[str, str]]:
    global _catalogue, _catalogue_at
    if _catalogue and (time.time() - _catalogue_at) < CATALOGUE_TTL:
        return _catalogue
    r = await client.get(CATALOGUE)
    r.raise_for_status()
    rows = [row for row in csv.DictReader(io.StringIO(r.text), delimiter=";")
            if (row.get("FeedStatus") or "").strip().lower() == "active"
            and (row.get("Url") or "").strip()]
    # One URL can appear under several categories (TweetFeed lists the same
    # CSV for IP, DNS, URL and three hash types); keep the first per (url,
    # category) so a feed cannot be counted twice as "agreement".
    seen: set[tuple[str, str]] = set()
    uniq = []
    for row in rows:
        key = ((row.get("Url") or "").strip(), (row.get("Category") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(row)
    _catalogue = uniq
    _catalogue_at = time.time()
    return _catalogue


def _extract(text: str, want_ip: bool) -> set[str]:
    """Parse a blocklist into a set of lowercase indicators.

    Formats in the wild: bare lines, CSV, and hosts files. Comment lines are
    dropped, and for a hosts-file line ("0.0.0.0 evil.example") the sinkhole
    address must not become an indicator — so for non-IP feeds the LAST field
    is taken, and for IP feeds only things that parse as an IP are kept.
    """
    out: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(_COMMENT):
            continue
        parts = [p for p in re.split(r"[\s,;]+", line) if p]
        if not parts:
            continue
        if want_ip:
            for token in parts:
                token = token.strip('"').strip("'")
                try:
                    ipaddress.ip_address(token)
                except ValueError:
                    continue
                out.add(token.lower())
        else:
            token = parts[-1].strip('"').strip("'").lower().rstrip(".")
            # Skip the sinkhole address of a hosts-file entry.
            if len(parts) > 1 and _IP_RE.fullmatch(parts[0] or ""):
                token = parts[-1].strip('"').strip("'").lower().rstrip(".")
            if token and not token.startswith(_COMMENT):
                out.add(token)
    return out


async def _feed_indicators(client: httpx.AsyncClient, url: str,
                           want_ip: bool) -> set[str] | None:
    cached = _feed_cache.get(url)
    if cached and (time.time() - cached[0]) < FEED_TTL:
        return cached[1]
    try:
        r = await client.get(url, timeout=FEED_TIMEOUT)
        r.raise_for_status()
    except (httpx.HTTPError, UnicodeDecodeError):
        return None
    if len(r.content) > MAX_FEED_BYTES:
        return None
    try:
        text = r.text
    except Exception:  # noqa: BLE001 — undecodable payload is not our problem
        return None
    indicators = _extract(text, want_ip)
    _feed_cache[url] = (time.time(), indicators)
    return indicators


def _normalise(query: str, query_type: str) -> str:
    q = (query or "").strip().lower()
    if query_type == "domain":
        q = q.split("://", 1)[-1].split("/", 1)[0].rstrip(".")
    return q


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "ip",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    selector = _normalise(query, query_type)
    if not selector:
        return [], [], ["ioc_reputation: empty selector"]

    categories = CATEGORIES.get(query_type)
    if not categories:
        return [], [], [f"ioc_reputation: unsupported query type '{query_type}'"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=FEED_TIMEOUT, headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        try:
            catalogue = await _load_catalogue(client)
        except httpx.HTTPError as e:
            return [], [], [f"ioc_reputation: feed catalogue unreachable: {e}"]

        candidates = [row for row in catalogue
                      if (row.get("Category") or "").strip() in categories]
        if not candidates:
            return [], [], [f"{NOTE_PREFIX}ioc_reputation: the catalogue lists no "
                            f"active feed for {query_type}."]

        selected = candidates[:MAX_FEEDS]
        want_ip = query_type == "ip"
        sem = asyncio.Semaphore(CONCURRENCY)

        async def check(row: dict[str, str]):
            async with sem:
                indicators = await _feed_indicators(client, row["Url"].strip(), want_ip)
            if indicators is None:
                return row, None
            return row, selector in indicators

        results = await asyncio.gather(*[check(r) for r in selected])

    hits = [row for row, found in results if found]
    unreachable = [row for row, found in results if found is None]
    checked = len(results) - len(unreachable)

    if len(candidates) > len(selected):
        errors.append(f"{NOTE_PREFIX}ioc_reputation: consulted {len(selected)} of "
                      f"{len(candidates)} available {'/'.join(categories)} feeds "
                      "(per-run cap).")
    if unreachable:
        errors.append(f"{NOTE_PREFIX}ioc_reputation: {len(unreachable)} of "
                      f"{len(selected)} feeds did not answer — coverage is "
                      "reduced for this run.")

    if not hits:
        errors.append(f"{NOTE_PREFIX}ioc_reputation: {selector} appears on none of "
                      f"the {checked} blocklists that were reachable.")
        return [], [], errors

    entity_type = {"ip": "ip_address", "domain": "domain",
                   "url": "url", "hash": "file_hash"}[query_type]
    vendors = sorted({(r.get("Vendor") or "?").strip() for r in hits})

    # Re-emitting the selector is the point: the framework's cross-confirmation
    # then counts this as an independent report of a node other tools found.
    findings.append(Finding(
        entity_type=entity_type,
        label=selector,
        url=CATALOGUE_URL,
        # More agreeing lists is a stronger statement, but this is aggregated
        # open reporting, not a primary observation — capped accordingly.
        confidence=min(0.9, 0.6 + 0.05 * len(hits)),
        data={
            "blocklist_hits": len(hits),
            "blocklists_checked": checked,
            "blocklist_vendors": vendors,
            "blocklist_entries": [
                {"vendor": (r.get("Vendor") or "").strip(),
                 "description": (r.get("Description") or "").strip()[:200],
                 "url": (r.get("Url") or "").strip()}
                for r in hits
            ],
            "source": "ioc_reputation",
        },
    ))

    # Each listing vendor becomes a node, so two indicators flagged by the
    # same source visibly converge in the graph.
    for vendor in vendors:
        findings.append(Finding(
            entity_type="threat_source", label=vendor, url=CATALOGUE_URL,
            confidence=0.7, data={"source": "ioc_reputation"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{entity_type}:{selector}",
            to_entity=f"threat_source:{vendor}",
            relation="listed_by",
            confidence=0.75,
        ))

    return findings, edges, errors
