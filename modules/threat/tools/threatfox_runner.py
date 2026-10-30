"""
ThreatFox (abuse.ch) IOC lookup.

Since 2024 abuse.ch requires an Auth-Key header on every request (one
free key from https://auth.abuse.ch/ covers ThreatFox, MalwareBazaar and
URLhaus). Without it the API returns HTTP 401 — surfaced as a
key-missing error.

POST https://threatfox-api.abuse.ch/api/v1/
     {"query": "search_ioc", "search_term": <ip|domain|url|hash>}
"""
from __future__ import annotations

import httpx

from schemas import EdgeResult, Finding, credential

API_URL = "https://threatfox-api.abuse.ch/api/v1/"
USER_AGENT = "OOF/1.0"
MAX_ROWS = 25


def _key(options: dict | None) -> str:
    # One abuse.ch account/key for all their services; accept either name.
    return credential(options, "ABUSECH_API_KEY") or credential(options, "URLHAUS_API_KEY")


async def run_threatfox(
    query: str, query_type: str, options: dict | None = None,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    q = (query or "").strip()
    if not q:
        return [], [], ["ThreatFox: empty query"]
    key = _key(options)
    if not key:
        return [], [], ["ThreatFox: ABUSECH_API_KEY not set "
                        "(free at https://auth.abuse.ch/, one key for all abuse.ch)"]

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json",
               "Auth-Key": key}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.post(API_URL, json={"query": "search_ioc", "search_term": q})
            if r.status_code == 401:
                return [], [], ["ThreatFox: HTTP 401 — invalid/missing ABUSECH_API_KEY "
                                "(get one free at https://auth.abuse.ch/)"]
            if r.status_code != 200:
                return [], [], [f"ThreatFox HTTP {r.status_code}"]
            body = r.json()
    except httpx.TimeoutException:
        return [], [], ["ThreatFox timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"ThreatFox error: {e}"]

    if body.get("query_status") != "ok":
        # "no_result" is a clean miss, not an error.
        return [], [], []

    root = f"{query_type}:{q}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    seen: set[str] = set()
    for row in (body.get("data") or [])[:MAX_ROWS]:
        family = row.get("malware_printable") or row.get("malware") or "unknown"
        if family in seen:
            continue
        seen.add(family)
        findings.append(Finding(
            entity_type="malware", platform="threatfox",
            label=family, confidence=0.75,
            data={"threat_type": row.get("threat_type"),
                  "malware": row.get("malware"),
                  "confidence_level": row.get("confidence_level"),
                  "first_seen": row.get("first_seen"),
                  "ioc_type": row.get("ioc_type"),
                  "tags": row.get("tags"),
                  "malware_alias": row.get("malware_alias"),
                  "reference": row.get("reference"),
                  "source": "threatfox"},
        ))
        edges.append(EdgeResult(from_entity=root, to_entity=f"malware:{family}",
                                relation="threatfox_ioc", confidence=0.75))
    return findings, edges, []
