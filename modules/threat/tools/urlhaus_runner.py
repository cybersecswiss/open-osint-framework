"""
URLhaus (abuse.ch) lookup.

Since 2024, URLhaus requires an Auth-Key header for every request
(free at https://auth.abuse.ch/). Without it the API returns HTTP
401 — we surface that as a key-missing error so the operator knows
to register.

Endpoints:
  POST /v1/host/    {host: <domain>}
  POST /v1/url/     {url: <url>}
  POST /v1/payload/ {sha256_hash: <hash>}  or {md5_hash: <hash>}
"""
from __future__ import annotations

import os

import httpx

from schemas import EdgeResult, Finding, credential

BASE = "https://urlhaus-api.abuse.ch/v1"
USER_AGENT = "OOF/1.0"


def _headers(options: dict | None) -> dict[str, str]:
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    # One abuse.ch key covers all their services; accept either name.
    key = credential(options, "URLHAUS_API_KEY") or credential(options, "ABUSECH_API_KEY")
    if key:
        h["Auth-Key"] = key
    return h


async def _post(path: str, data: dict, options: dict | None = None) -> tuple[dict | None, str | None]:
    try:
        async with httpx.AsyncClient(timeout=30, headers=_headers(options)) as client:
            r = await client.post(f"{BASE}{path}", data=data)
            if r.status_code == 401:
                return None, ("URLhaus: HTTP 401 — set URLHAUS_API_KEY in .env "
                              "(free at https://auth.abuse.ch/)")
            if r.status_code != 200:
                return None, f"URLhaus HTTP {r.status_code}"
            return r.json(), None
    except httpx.TimeoutException:
        return None, "URLhaus timeout (30s)"
    except Exception as e:  # noqa: BLE001
        return None, f"URLhaus error: {e}"


async def run_urlhaus(
    query: str, query_type: str, options: dict | None = None
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    if query_type == "domain":
        payload, err = await _post("/host/", {"host": query}, options)
    elif query_type == "url":
        payload, err = await _post("/url/", {"url": query}, options)
    elif query_type == "hash":
        payload, err = await _post("/payload/", {"sha256_hash": query} if len(query) == 64 else {"md5_hash": query}, options)
    else:
        return [], [], [f"URLhaus: unsupported query_type={query_type}"]
    if err:
        return [], [], [err]
    if not payload or payload.get("query_status") not in ("ok", "no_results"):
        return [], [], [f"URLhaus query_status={(payload or {}).get('query_status')}"]
    if payload.get("query_status") == "no_results":
        return [], [], []

    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    if query_type in ("domain", "url"):
        urls = payload.get("urls") or []
        if not isinstance(urls, list) and "url" in payload:
            urls = [payload]
        for entry in urls[:50]:
            url = entry.get("url") or ""
            threat = entry.get("threat") or ""
            tags = entry.get("tags") or []
            findings.append(Finding(
                entity_type="malicious_url",
                platform="urlhaus",
                label=url[:200],
                url=url,
                confidence=0.95,
                data={
                    "url": url, "threat": threat, "tags": tags,
                    "date_added": entry.get("date_added"),
                    "url_status": entry.get("url_status"),
                    "source": "urlhaus",
                },
            ))
            edges.append(EdgeResult(
                from_entity=f"{query_type}:{query}",
                to_entity=f"malicious_url:{url}",
                relation="urlhaus_listed",
                confidence=0.95,
            ))
    elif query_type == "hash":
        sha256 = payload.get("sha256_hash") or query
        findings.append(Finding(
            entity_type="malware_sample",
            platform="urlhaus",
            label=f"sample:{sha256[:16]}",
            url=f"https://urlhaus.abuse.ch/sample/{sha256}/",
            confidence=0.95,
            data={
                "sha256": sha256,
                "md5": payload.get("md5_hash"),
                "file_type": payload.get("file_type"),
                "file_size": payload.get("file_size"),
                "signature": payload.get("signature"),
                "tags": payload.get("tags") or [],
                "source": "urlhaus",
            },
        ))
        edges.append(EdgeResult(
            from_entity=f"hash:{query}",
            to_entity=f"malware_sample:{sha256}",
            relation="urlhaus_sample_of",
            confidence=0.95,
        ))

    return findings, edges, []
