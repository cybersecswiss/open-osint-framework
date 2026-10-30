"""
AbuseIPDB v2 lookup. IP reputation score 0–100 + abuse-report counts.
Free key (https://www.abuseipdb.com/account/api).
"""
from __future__ import annotations

import os

import httpx

from schemas import EdgeResult, Finding, credential

API_URL = "https://api.abuseipdb.com/api/v2/check"
USER_AGENT = "OOF/1.0"


async def run_abuseipdb(ip: str, options: dict | None = None) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = credential(options, "ABUSEIPDB_API_KEY")
    if not key:
        return [], [], [
            "AbuseIPDB: ABUSEIPDB_API_KEY not set in .env "
            "(free tier at https://www.abuseipdb.com/account/api)"
        ]
    headers = {"Key": key, "Accept": "application/json", "User-Agent": USER_AGENT}
    params = {"ipAddress": ip, "maxAgeInDays": "90", "verbose": ""}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(API_URL, params=params)
            if r.status_code == 401:
                return [], [], ["AbuseIPDB: HTTP 401 — API key rejected"]
            if r.status_code == 429:
                return [], [], ["AbuseIPDB: rate-limited (HTTP 429)"]
            if r.status_code != 200:
                return [], [], [f"AbuseIPDB HTTP {r.status_code}"]
            data = (r.json() or {}).get("data") or {}
    except httpx.TimeoutException:
        return [], [], ["AbuseIPDB timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"AbuseIPDB error: {e}"]

    score = int(data.get("abuseConfidenceScore") or 0)
    reports = int(data.get("totalReports") or 0)
    country = data.get("countryCode") or ""
    isp = data.get("isp") or ""

    # The edge endpoint must be the finding's own key ("{entity_type}:{label}")
    # or graph_builder resolves it to a second, virtual node. Bind both to one
    # variable so they can't drift apart again.
    label = f"abuseipdb:{score}/100:{ip}"
    findings = [Finding(
        entity_type="ip_reputation",
        platform="abuseipdb",
        label=label,
        url=f"https://www.abuseipdb.com/check/{ip}",
        confidence=0.85,
        data={
            "ip": ip, "abuse_score": score, "total_reports": reports,
            "country": country, "isp": isp, "domain": data.get("domain", ""),
            "usage_type": data.get("usageType", ""), "source": "abuseipdb",
        },
    )]
    edges = [EdgeResult(
        from_entity=f"ip:{ip}",
        to_entity=f"ip_reputation:{label}",
        relation="reputation_of",
        confidence=0.9,
    )]
    if isp:
        edges.append(EdgeResult(
            from_entity=f"ip:{ip}",
            to_entity=f"organization:{isp.lower()}",
            relation="hosted_by",
            confidence=0.85,
        ))
    return findings, edges, []
