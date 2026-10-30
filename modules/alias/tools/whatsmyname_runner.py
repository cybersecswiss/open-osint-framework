"""
WhatsMyName lookup.

Loads the upstream WhatsMyName web-app site list (community-curated,
much more current than sherlock's bundled list) and probes each
target URL for the queried username. A "hit" is a 200-or-3xx response
with the e_string (expected substring) present in the body. We cap
concurrency to keep the module from getting itself rate-limited.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from schemas import EdgeResult, Finding, NOTE_PREFIX
from verifier import verify_findings

LIST_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
USER_AGENT = "OOF/1.0"
CONCURRENCY = 30
PER_SITE_TIMEOUT = 8

log = logging.getLogger("module-alias.whatsmyname")


async def _fetch_sites(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(LIST_URL, timeout=15)
    r.raise_for_status()
    return (r.json() or {}).get("sites") or []


async def _probe(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 site: dict, username: str) -> Finding | None:
    name = site.get("name") or "?"
    cat = site.get("cat") or ""
    e_code = int(site.get("e_code") or 200)
    e_string = site.get("e_string") or ""
    uri_check = (site.get("uri_check") or "").replace("{account}", username)
    if not uri_check:
        return None
    async with sem:
        try:
            r = await client.get(uri_check, timeout=PER_SITE_TIMEOUT,
                                 follow_redirects=True)
        except (httpx.TimeoutException, httpx.RequestError):
            return None
    if r.status_code != e_code:
        return None
    if e_string and e_string not in r.text:
        return None
    return Finding(
        entity_type="social_account",
        platform=name.lower(),
        label=f"{name.lower()}/{username}",
        url=uri_check,
        confidence=0.8,
        data={"username": username, "platform": name, "category": cat,
              "url": uri_check, "source": "whatsmyname"},
    )


async def run_whatsmyname(
    username: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    headers = {"User-Agent": USER_AGENT}
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        async with httpx.AsyncClient(headers=headers,
                                     timeout=httpx.Timeout(15)) as client:
            try:
                sites = await _fetch_sites(client)
            except Exception as e:  # noqa: BLE001
                return [], [], [f"WhatsMyName: failed to fetch site list: {e}"]

            sem = asyncio.Semaphore(CONCURRENCY)
            tasks = [_probe(client, sem, s, username) for s in sites]
            results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:  # noqa: BLE001
        return [], [], [f"WhatsMyName error: {e}"]

    for res in results:
        if isinstance(res, Finding):
            findings.append(res)

    # Even with the e_string check the upstream wmn-data.json list is
    # known to produce false positives on platforms that recently
    # changed their "not found" page. Re-verify every URL against the
    # shared content probe.
    raw_count = len(findings)
    findings = await verify_findings(findings, username)
    dropped = raw_count - len(findings)
    if dropped > 0:
        errors.append(f"{NOTE_PREFIX}whatsmyname: {dropped} false positives filtered "
                      f"({len(findings)}/{raw_count} verified)")

    for f in findings:
        edges.append(EdgeResult(
            from_entity=f"username:{username}",
            # Edge target must equal the finding's graph key
            # (entity_type:label). f.label is "platform/username" (slash);
            # a colon form spawns an empty virtual shadow node.
            to_entity=f"social_account:{f.label}",
            relation="is_account_of",
            confidence=0.85,
        ))
    return findings, edges, errors
