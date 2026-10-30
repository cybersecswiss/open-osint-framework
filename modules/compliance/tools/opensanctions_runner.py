"""
OpenSanctions lookup (sanctions / PEP / watchlist screening).

OpenSanctions consolidates OFAC, EU, UN, SECO (Switzerland) and many
more lists into one graph. Screening a name, company or crypto wallet
against it is a top-value check for law-enforcement: it flags sanctioned
entities, politically exposed persons (PEPs) and crime/watchlist hits,
and — via the entity's own properties — surfaces connections (aliases,
addresses, linked companies, wallets).

The hosted API is key-gated (https://www.opensanctions.org/api/); without
a key it returns HTTP 401, surfaced as a clean key-missing error. (A
self-hosted `yente` instance is keyless — point OPENSANCTIONS_BASE at it.)
"""
from __future__ import annotations

import os

import httpx

from schemas import EdgeResult, Finding, credential

BASE = os.environ.get("OPENSANCTIONS_BASE", "https://api.opensanctions.org").rstrip("/")
USER_AGENT = "OOF/1.0"
MAX_RESULTS = 10


def _topic_flags(props: dict) -> dict:
    topics = props.get("topics", []) or []
    return {
        "sanctioned": any(t == "sanction" for t in topics),
        "pep": any(str(t).startswith("role.pep") or t == "role.pep" for t in topics),
        "crime": any(str(t).startswith("crime") for t in topics),
        "topics": topics,
    }


async def run_opensanctions(
    query: str, query_type: str, options: dict | None = None,
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    q = (query or "").strip()
    if not q:
        return [], [], ["OpenSanctions: empty query"]

    key = credential(options, "OPENSANCTIONS_API_KEY")
    self_hosted = "api.opensanctions.org" not in BASE
    if not key and not self_hosted:
        return [], [], ["OpenSanctions: OPENSANCTIONS_API_KEY not set "
                        "(get one at https://www.opensanctions.org/api/, or point "
                        "OPENSANCTIONS_BASE at a self-hosted yente instance)"]

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"ApiKey {key}"
    params = {"q": q, "limit": str(MAX_RESULTS)}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(f"{BASE}/search/default", params=params)
            if r.status_code in (401, 403):
                return [], [], [f"OpenSanctions HTTP {r.status_code} — check "
                                "OPENSANCTIONS_API_KEY (https://www.opensanctions.org/api/)"]
            if r.status_code != 200:
                return [], [], [f"OpenSanctions HTTP {r.status_code}"]
            body = r.json()
    except httpx.TimeoutException:
        return [], [], ["OpenSanctions timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"OpenSanctions error: {e}"]

    results = body.get("results") or []
    if not results:
        return [], [], []

    root = f"{query_type}:{q}"
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    for res in results[:MAX_RESULTS]:
        props = res.get("properties", {}) or {}
        flags = _topic_flags(props)
        caption = res.get("caption") or res.get("id") or "?"
        oid = res.get("id")
        findings.append(Finding(
            entity_type="sanction_match", platform="opensanctions",
            label=caption,
            url=f"https://www.opensanctions.org/entities/{oid}/" if oid else None,
            confidence=0.7,
            data={"schema": res.get("schema"),
                  "sanctioned": flags["sanctioned"], "pep": flags["pep"],
                  "crime": flags["crime"], "topics": flags["topics"],
                  "datasets": res.get("datasets"),
                  "countries": props.get("country"),
                  "birth_date": props.get("birthDate"),
                  "aliases": props.get("alias"),
                  "opensanctions_id": oid,
                  "match_score": res.get("score"),
                  "url": f"https://www.opensanctions.org/entities/{oid}/" if oid else None,
                  "source": "opensanctions"},
        ))
        edges.append(EdgeResult(
            from_entity=root, to_entity=f"sanction_match:{caption}",
            relation="sanctions_match", confidence=0.7))
    return findings, edges, []
