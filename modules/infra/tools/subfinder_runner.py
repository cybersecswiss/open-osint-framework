"""
Subfinder wrapper.

Subfinder enumerates subdomains for a given domain using passive
sources. Free/no-auth sources work out of the box; richer sources
need API keys in /root/.config/subfinder/provider-config.yaml (not
configured here).
"""
from __future__ import annotations

import asyncio

from schemas import EdgeResult, Finding

# Large domains can enumerate thousands of subdomains; cap the result
# set so we don't flood the graph + agent ingest with a single search.
MAX_FINDINGS = 200


async def run_subfinder(
    domain: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        proc = await asyncio.create_subprocess_exec(
            "subfinder", "-d", domain, "-silent", "-timeout", "30",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        total = 0
        for raw in stdout.decode(errors="replace").splitlines():
            sub = raw.strip()
            if not sub or sub == domain:
                continue
            total += 1
            if len(findings) >= MAX_FINDINGS:
                continue  # keep counting for the truncation notice
            findings.append(Finding(
                entity_type="domain",
                label=sub,
                url=f"https://{sub}",
                confidence=0.8,
                data={"parent_domain": domain, "source": "subfinder"},
            ))
            edges.append(EdgeResult(
                from_entity=f"domain:{domain}",
                to_entity=f"domain:{sub}",
                relation="has_subdomain",
                confidence=0.9,
            ))
        if total > MAX_FINDINGS:
            errors.append(
                f"subfinder: capped at {MAX_FINDINGS} of {total} subdomains — "
                f"re-run on a more specific sub-domain for the rest"
            )
    except asyncio.TimeoutError:
        errors.append("subfinder timeout (120s)")
    except FileNotFoundError:
        errors.append("subfinder binary not installed")
    except Exception as e:  # noqa: BLE001
        errors.append(f"subfinder error: {e}")

    return findings, edges, errors
