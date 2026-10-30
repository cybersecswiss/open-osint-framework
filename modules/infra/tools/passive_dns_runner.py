"""Passive DNS — historical resolutions from Mnemonic's open pDNS.

The central infrastructure pivot for cybercrime work: *which domains pointed
at this IP, and when*. Every other infra tool here answers "what is true
now" — crt.sh, dns_records, shodan. Without history a C2 or phishing
analysis stops at the current state, which is exactly the state an operator
changes as soon as they are burned.

Mnemonic's v3 API is open and keyless. It answers in both directions from
one endpoint:

    query == selector   → the selector resolved TO the answer  (forward)
    answer == selector  → the answer was resolved FROM query   (reverse)

so a domain lookup yields its historical addresses and an IP lookup yields
every domain seen pointing at it. The reverse direction is the valuable one.

CIRCL's passive DNS covers different sources and is arguably richer, but it
requires an account per user; it belongs behind a credential and is not part
of this keyless runner.

Caveat worth knowing: for anonymous callers Mnemonic returns `times` (how
often the pair was observed) but frequently zeroes the first/last-seen
timestamps. We pass through whatever we get and never invent a date —
`observed_at` stays unset rather than being backfilled with "now", which
would misrepresent an archive record as a fresh observation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

API = "https://api.mnemonic.no/pdns/v3/{selector}"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
LIMIT = 500
MAX_FINDINGS = 200
TIMEOUT = 45

# rrtypes whose answer is an address, vs. those whose answer is a name.
_ADDRESS_TYPES = {"a", "aaaa"}
_NAME_TYPES = {"cname", "ns", "mx", "ptr", "srv"}

log = logging.getLogger("module-infra.passive_dns")


def _ts(value: Any) -> str | None:
    """Mnemonic timestamps are epoch milliseconds; 0 means 'not disclosed'."""
    try:
        ms = int(value or 0)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(
        tzinfo=None).isoformat()


def _entity_type_for(rrtype: str, value: str) -> str:
    if rrtype in _ADDRESS_TYPES:
        return "ip"
    if rrtype in _NAME_TYPES:
        return "domain"
    # Unknown rrtype: decide by shape rather than guessing a type name.
    return "ip" if value.replace(".", "").isdigit() or ":" in value else "domain"


async def run_passive_dns(
    query: str, query_type: str, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    selector = (query or "").strip().lower().rstrip(".")
    if not selector:
        return [], [], ["passive_dns: empty query"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    root = f"{'ip' if query_type == 'ip' else 'domain'}:{selector}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
            r = await client.get(API.format(selector=selector),
                                 params={"limit": LIMIT})
    except httpx.TimeoutException:
        return findings, edges, [f"passive_dns: mnemonic timeout ({TIMEOUT}s)"]
    except httpx.HTTPError as e:
        return findings, edges, [f"passive_dns: mnemonic unreachable: {e}"]

    if r.status_code == 404:
        return findings, edges, [f"{NOTE_PREFIX}passive_dns: nothing recorded for "
                                 f"'{selector}'."]
    if r.status_code == 429:
        return findings, edges, ["passive_dns: rate-limited by mnemonic — try again later"]
    if r.status_code != 200:
        return findings, edges, [f"passive_dns: mnemonic HTTP {r.status_code}"]

    try:
        payload = r.json()
    except ValueError:
        return findings, edges, ["passive_dns: mnemonic returned non-JSON"]

    records = payload.get("data") or []
    if not records:
        return findings, edges, [f"{NOTE_PREFIX}passive_dns: no historical records "
                                 f"for '{selector}'."]

    seen: set[str] = set()
    undated = 0
    for rec in records:
        if len(findings) >= MAX_FINDINGS:
            errors.append(f"{NOTE_PREFIX}passive_dns: capped at {MAX_FINDINGS} of "
                          f"{len(records)} records.")
            break
        rrtype = str(rec.get("rrtype") or "").lower()
        rec_query = str(rec.get("query") or "").lower().rstrip(".")
        rec_answer = str(rec.get("answer") or "").lower().rstrip(".")
        if not rec_query or not rec_answer:
            continue

        # Which side of the record is the NEW information?
        if rec_query == selector:
            other, forward = rec_answer, True
        elif rec_answer == selector:
            other, forward = rec_query, False
        else:
            continue
        if other == selector:
            continue

        etype = _entity_type_for(rrtype, other) if forward else "domain"
        key = f"{etype}:{other}"
        if key in seen:
            continue
        seen.add(key)

        first, last = _ts(rec.get("firstSeenTimestamp")), _ts(rec.get("lastSeenTimestamp"))
        if not last:
            undated += 1

        data = {
            "rrtype": rrtype,
            "observations": rec.get("times"),
            "first_seen": first,
            "last_seen": last,
            "direction": "forward" if forward else "reverse",
            "source": "mnemonic-pdns",
        }
        finding = Finding(
            entity_type=etype, label=other, confidence=0.75, data=data,
            platform="mnemonic",
        )
        # Only claim an observation time when the source actually gave one.
        if last:
            try:
                finding.found_at = datetime.fromisoformat(last)
            except ValueError:
                pass
        findings.append(finding)

        # The edge always points selector → other in resolution order, so a
        # reverse lookup still reads "domain resolved to this IP".
        if forward:
            frm, to = root, key
        else:
            frm, to = key, root
        edges.append(EdgeResult(
            from_entity=frm, to_entity=to,
            relation="historic_resolution", confidence=0.75,
        ))

    if undated and findings:
        errors.append(f"{NOTE_PREFIX}passive_dns: {undated} record(s) came without "
                      "first/last-seen dates (mnemonic withholds them for "
                      "anonymous callers) — no observation time was invented.")
    return findings, edges, errors
