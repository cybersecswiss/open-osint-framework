"""Known command-and-control infrastructure — C2IntelFeeds.

Every other infra tool in the framework answers "what is true about this host
right now". This one answers a different and, for an investigation, often more
useful question: **has this address been seen serving a C2 panel, and for
which malware family**. The data comes from drb-ra/C2IntelFeeds, which derives
it from Censys scans — so a hit is an observation of the C2 software itself,
not a reputation score somebody assigned.

The value in the case graph is corroboration. A domain that arrives from
crt.sh, resolves via dns_records and *also* appears here as a Cobalt Strike
panel is a different object from one that only a certificate log ever
mentioned — and because the finding re-emits the searched selector under its
canonical type, the framework's cross-confirmation picks that up on its own.

Feeds used (90-day windows — the shorter files exist but hold only the last
weeks, which loses exactly the older infrastructure an investigation looks
back at):

    domainC2s-90day.csv            domain, ioc
    domainC2swithURLwithIP-90day   domain, ioc, uri_path, ip
    IPC2s-90day.csv                ip, ioc
    IPPortC2s-90day.csv            ip, port, ioc

Cached in-process for six hours. The upstream updates daily, and re-fetching
four CSVs for every tool in a module run would be a self-inflicted rate limit
on a GitHub raw endpoint we do not control.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import logging
import time
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

BASE = "https://raw.githubusercontent.com/drb-ra/C2IntelFeeds/master/feeds"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 45
CACHE_TTL = 6 * 3600
REPO_URL = "https://github.com/drb-ra/C2IntelFeeds"

# (filename, key column, extra columns to carry into the finding)
FEEDS: list[tuple[str, str, tuple[str, ...]]] = [
    ("domainC2s-90day.csv", "domain", ()),
    ("domainC2swithURLwithIP-90day.csv", "domain", ("uri_path", "ip")),
    ("IPC2s-90day.csv", "ip", ()),
    ("IPPortC2s-90day.csv", "ip", ("port",)),
]

log = logging.getLogger("module-threat.c2intel")

# selector (lowercase) -> list of hit dicts. Rebuilt on TTL expiry.
_index: dict[str, list[dict[str, Any]]] = {}
_indexed_at: float = 0.0
_index_stats: dict[str, Any] = {}


def _parse(text: str, key_col: str, extras: tuple[str, ...], source: str,
           into: dict[str, list[dict[str, Any]]]) -> int:
    """Fold one CSV into the shared index. The files carry a commented header
    (`#domain,ioc`), so the leading '#' is stripped before parsing rather than
    the row being skipped — the header names the columns we need."""
    text = text.lstrip("﻿")
    if text.startswith("#"):
        text = text[1:]
    added = 0
    for row in csv.DictReader(io.StringIO(text)):
        key = (row.get(key_col) or "").strip().lower()
        if not key or key.startswith("#"):
            continue
        hit: dict[str, Any] = {
            "ioc": (row.get("ioc") or "").strip(),
            "feed": source,
        }
        for col in extras:
            val = (row.get(col) or "").strip()
            if val:
                hit[col] = val
        into.setdefault(key, []).append(hit)
        added += 1
    return added


async def _load_index(client: httpx.AsyncClient) -> tuple[dict, list[str]]:
    """Build (or reuse) the selector index. Returns (index, notes).

    A feed that fails is reported, never silently dropped: a partial sweep
    that reads as a complete one turns "we did not look" into "not a C2".
    """
    global _indexed_at, _index, _index_stats
    if _index and (time.time() - _indexed_at) < CACHE_TTL:
        return _index, []

    fresh: dict[str, list[dict[str, Any]]] = {}
    notes: list[str] = []
    failed: list[str] = []
    rows_total = 0
    for filename, key_col, extras in FEEDS:
        try:
            r = await client.get(f"{BASE}/{filename}")
            r.raise_for_status()
        except httpx.HTTPError as e:
            failed.append(f"{filename} ({type(e).__name__})")
            continue
        rows_total += _parse(r.text, key_col, extras, filename, fresh)

    if not fresh:
        # Keep whatever we had rather than replacing a usable index with an
        # empty one — a stale answer beats a false "no hits".
        if _index:
            notes.append(f"{NOTE_PREFIX}c2_intel: feeds unreachable, using the "
                         "cached index from the last successful fetch.")
            return _index, notes
        notes.append(f"{NOTE_PREFIX}c2_intel: no feed could be fetched "
                     f"({', '.join(failed) or 'unknown error'}).")
        return {}, notes

    _index = fresh
    _indexed_at = time.time()
    _index_stats = {"selectors": len(fresh), "rows": rows_total,
                    "feeds": len(FEEDS) - len(failed)}
    if failed:
        notes.append(f"{NOTE_PREFIX}c2_intel: {len(failed)} of {len(FEEDS)} feeds "
                     f"could not be fetched ({', '.join(failed)}) — coverage is "
                     "reduced for this run.")
    return _index, notes


def _family(ioc: str) -> str:
    """Reduce a feed's free-text label to the malware family it names.

    The upstream writes five different strings for two families — "Possible
    Cobaltstrike C2 IP", "Possible Cobalt Strike C2 Domain", "… C2 Fronted
    Domain", "… C2 Fronting Domain", "Possible Metasploit C2 IP". Emitted
    verbatim those become five `malware` nodes for two actors, which is
    exactly the shadow-node problem the canonical dedup exists to prevent:
    two hosts running the same implant would never converge in the graph.

    The raw string is kept in the finding's data, so nothing is lost — only
    the node identity is canonicalised.
    """
    s = (ioc or "").strip()
    if not s:
        return ""
    for prefix in ("Possible ", "Potential ", "Likely "):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):]
            break
    # Drop the trailing "C2 <what it was seen as>" qualifier.
    low = s.lower()
    cut = low.find(" c2 ")
    if cut != -1:
        s = s[:cut]
    elif low.endswith(" c2"):
        s = s[:-3]
    s = " ".join(s.split())
    # One-word spellings of multi-word product names.
    aliases = {"cobaltstrike": "Cobalt Strike", "cobalt strike": "Cobalt Strike",
               "metasploit": "Metasploit", "sliver": "Sliver",
               "brute ratel": "Brute Ratel", "bruteratel": "Brute Ratel",
               "havoc": "Havoc", "mythic": "Mythic", "covenant": "Covenant"}
    return aliases.get(s.lower(), s)


def _selector(query: str, query_type: str) -> str:
    q = (query or "").strip().lower().rstrip(".")
    if query_type == "url":
        q = q.split("://", 1)[-1].split("/", 1)[0]
    return q.split("@")[-1]


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "domain",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    selector = _selector(query, query_type)
    if not selector:
        return [], [], ["c2_intel: empty selector"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        index, errors = await _load_index(client)

    hits = index.get(selector) or []
    if not hits:
        # Not a finding and not an error. Absence of evidence is worth
        # recording as a note so the analyst knows the list was consulted.
        if index:
            errors.append(f"{NOTE_PREFIX}c2_intel: {selector} is not in "
                          f"{_index_stats.get('selectors', 0):,} known C2 "
                          "selectors (90-day window).")
        return [], [], errors

    try:
        is_ip = bool(ipaddress.ip_address(selector))
    except ValueError:
        is_ip = False
    root_type = "ip_address" if is_ip else "domain"

    # Re-emit the selector under its canonical type. This is what makes the
    # hit count as an independent confirmation of a node another tool found.
    raw_labels = sorted({h["ioc"] for h in hits if h.get("ioc")})
    families = sorted({f for f in (_family(x) for x in raw_labels) if f})
    ports = sorted({h["port"] for h in hits if h.get("port")})
    paths = sorted({h["uri_path"] for h in hits if h.get("uri_path")})
    resolved = sorted({h["ip"] for h in hits if h.get("ip")})
    # Domain fronting is an operational detail worth carrying: it changes how
    # the traffic looks on the wire and therefore how it can be hunted.
    fronting = any("front" in x.lower() for x in raw_labels)

    findings.append(Finding(
        entity_type=root_type,
        label=selector,
        url=REPO_URL,
        confidence=0.85,
        data={
            "c2": True,
            "c2_families": families,
            # The verbatim upstream wording, kept so the canonicalisation
            # above can always be checked against what the feed actually said.
            "c2_feed_labels": raw_labels,
            "c2_ports": ports,
            "c2_uri_paths": paths,
            "c2_domain_fronting": fronting,
            "observed_in_feeds": sorted({h["feed"] for h in hits}),
            "source": "c2intelfeeds",
        },
    ))

    # The malware family is the pivot worth having as its own node: two
    # unrelated hosts serving the same family belong in one picture.
    for family in families:
        findings.append(Finding(
            entity_type="malware",
            label=family,
            url=REPO_URL,
            confidence=0.8,
            data={"source": "c2intelfeeds", "role": "c2 framework"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{root_type}:{selector}",
            to_entity=f"malware:{family}",
            relation="hosts_c2_for",
            confidence=0.85,
            data={"feed_labels": [x for x in raw_labels if _family(x) == family],
                  "domain_fronting": fronting},
        ))

    # A domain feed that also carries the panel's IP gives a free pivot.
    for ip in resolved:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue
        findings.append(Finding(
            entity_type="ip_address", label=ip, url=REPO_URL, confidence=0.8,
            data={"c2": True, "source": "c2intelfeeds"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{root_type}:{selector}",
            to_entity=f"ip_address:{ip}",
            relation="resolved_to",
            confidence=0.8,
        ))

    return findings, edges, errors
