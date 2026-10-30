"""
crt.sh certificate-transparency lookup.

Pulls all CT log entries that mention the queried domain or any of
its subdomains. Useful for passive subdomain discovery and for
spotting newly issued certs that hint at infrastructure expansion
(common cybercrime IOC: a fresh cert on a typo-squatted domain).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from schemas import EdgeResult, Finding

CRTSH_URL = "https://crt.sh/"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
MAX_FINDINGS = 200

log = logging.getLogger("module-infra.crtsh")


async def run_crtsh(
    domain: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    # crt.sh's Postgres backend is fragile — accept 404/5xx as
    # "transient empty" rather than treating them as a hard error.
    params = {"q": f"%.{domain}", "output": "json"}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            r = await client.get(CRTSH_URL, params=params)
            if r.status_code == 404:
                return findings, edges, []
            if r.status_code in (502, 503, 504):
                return findings, edges, [f"crt.sh upstream {r.status_code} (try again later)"]
            if r.status_code != 200:
                return findings, edges, [f"crt.sh HTTP {r.status_code}"]
            try:
                data: list[dict[str, Any]] = r.json()
            except ValueError:
                return findings, edges, ["crt.sh returned non-JSON (rate-limited?)"]
    except httpx.TimeoutException:
        return findings, edges, ["crt.sh timeout (60s)"]
    except Exception as e:  # noqa: BLE001
        return findings, edges, [f"crt.sh error: {e}"]

    seen: set[str] = set()
    for row in data:
        # name_value can be one or many DNS names separated by newlines
        for name in (row.get("name_value") or "").splitlines():
            host = name.strip().lower().lstrip("*.")
            if not host or host == domain or host in seen:
                continue
            if not host.endswith(domain):
                continue
            seen.add(host)
            if len(findings) >= MAX_FINDINGS:
                break
            findings.append(Finding(
                entity_type="domain",
                label=host,
                url=f"https://{host}",
                confidence=0.7,
                data={
                    "parent_domain": domain,
                    "issuer": row.get("issuer_name", ""),
                    "not_before": row.get("not_before", ""),
                    "not_after": row.get("not_after", ""),
                    "source": "crt.sh",
                },
            ))
            edges.append(EdgeResult(
                from_entity=f"domain:{domain}",
                to_entity=f"domain:{host}",
                relation="ct_log_subdomain",
                confidence=0.7,
            ))
        if len(findings) >= MAX_FINDINGS:
            break

    return findings, edges, errors
