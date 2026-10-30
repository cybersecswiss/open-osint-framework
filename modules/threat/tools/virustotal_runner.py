"""
VirusTotal v3 lookup.

Free public API key (https://www.virustotal.com/gui/my-apikey) is
rate-limited to 4 req/min — enough for ad-hoc OSINT but not bulk.
The runner returns a clean error pointing at the registration URL
when no key is configured.

Resource type per query_type:
  domain → /api/v3/domains/{domain}
  ip     → /api/v3/ip_addresses/{ip}
  url    → /api/v3/urls/{base64url}
  hash   → /api/v3/files/{sha256|sha1|md5}
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

from schemas import EdgeResult, Finding, credential

VT_BASE = "https://www.virustotal.com/api/v3"
USER_AGENT = "OOF/1.0"
log = logging.getLogger("module-threat.virustotal")


def _api_key(options: dict | None) -> str | None:
    raw = credential(options, "VIRUSTOTAL_API_KEY")
    return raw or None


def _resource_path(query: str, query_type: str) -> str | None:
    if query_type == "domain":
        return f"/domains/{query}"
    if query_type == "ip":
        return f"/ip_addresses/{query}"
    if query_type == "url":
        b64 = base64.urlsafe_b64encode(query.encode()).rstrip(b"=").decode()
        return f"/urls/{b64}"
    if query_type == "hash":
        return f"/files/{query}"
    return None


async def run_virustotal(
    query: str, query_type: str, options: dict | None = None
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    key = _api_key(options)
    if not key:
        return [], [], [
            "VirusTotal: VIRUSTOTAL_API_KEY not set in .env "
            "(free tier at https://www.virustotal.com/gui/my-apikey)"
        ]
    path = _resource_path(query, query_type)
    if not path:
        return [], [], [f"VirusTotal: unsupported query_type={query_type}"]

    headers = {"x-apikey": key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(f"{VT_BASE}{path}")
            if r.status_code == 401:
                return [], [], ["VirusTotal: HTTP 401 — API key rejected"]
            if r.status_code == 404:
                return [], [], [f"VirusTotal: no record for {query}"]
            if r.status_code == 429:
                return [], [], ["VirusTotal: rate-limited (HTTP 429)"]
            if r.status_code != 200:
                return [], [], [f"VirusTotal HTTP {r.status_code}"]
            payload = r.json()
    except httpx.TimeoutException:
        return [], [], ["VirusTotal timeout (30s)"]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"VirusTotal error: {e}"]

    attrs: dict[str, Any] = (payload.get("data") or {}).get("attributes") or {}
    stats = attrs.get("last_analysis_stats") or {}
    malicious = int(stats.get("malicious") or 0)
    suspicious = int(stats.get("suspicious") or 0)
    harmless = int(stats.get("harmless") or 0)
    total = malicious + suspicious + harmless + int(stats.get("undetected") or 0)
    verdict = "malicious" if malicious > 0 else ("suspicious" if suspicious > 0 else "clean")

    # Edge endpoint must equal this finding's key ("{entity_type}:{label}") —
    # see the same note in abuseipdb_runner.
    label = f"vt:{verdict}:{query}"
    findings = [Finding(
        entity_type="vt_verdict",
        platform="virustotal",
        label=label,
        url=f"https://www.virustotal.com/gui/search/{query}",
        confidence=0.9,
        data={
            "query": query, "query_type": query_type, "verdict": verdict,
            "malicious": malicious, "suspicious": suspicious,
            "harmless": harmless, "total": total,
            "reputation": attrs.get("reputation"),
            "last_analysis_date": attrs.get("last_analysis_date"),
            "source": "virustotal",
        },
    )]
    edges = [EdgeResult(
        from_entity=f"{query_type}:{query}",
        to_entity=f"vt_verdict:{label}",
        relation="vt_classified_as",
        confidence=0.9,
    )]
    return findings, edges, []
