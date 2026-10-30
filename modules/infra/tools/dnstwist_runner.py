"""dnstwist — typosquat / homograph permutations of a domain, filtered to
the ones that actually RESOLVE = live phishing / brand-impersonation
candidates an investigator can pivot on.

Keyless. Uses dnstwist's Fuzzer to generate look-alikes (homoglyph,
bitsquatting, insertion, omission, TLD-swap, …) and resolves each A record
concurrently via dnspython. Bounded so a big domain can't run away.
"""
from __future__ import annotations

import asyncio
import logging

from schemas import EdgeResult, Finding, NOTE_PREFIX

log = logging.getLogger("module-infra.dnstwist")

MAX_RESOLVE = 1200   # permutations we'll DNS-check
MAX_RESULTS = 80     # registered look-alikes rendered
CONCURRENCY = 60


async def run_dnstwist(
    query: str, query_type: str = "domain", job_id: str = "adhoc"
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    domain = (query or "").strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain or "." not in domain:
        return [], [], ["dnstwist: provide a domain (e.g. example.com)."]

    try:
        import dnstwist
        fuzz = dnstwist.Fuzzer(domain)
        fuzz.generate()
        perms = [d for d in fuzz.domains
                 if d.get("domain") and d["domain"] != domain][:MAX_RESOLVE]
    except Exception as e:  # noqa: BLE001
        return [], [], [f"dnstwist: permutation generation failed: {type(e).__name__}: {e}"]

    import dns.asyncresolver
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 5.0
    sem = asyncio.Semaphore(CONCURRENCY)

    async def _resolve(perm: dict):
        d = perm["domain"]
        async with sem:
            try:
                ans = await resolver.resolve(d, "A")
            except Exception:  # noqa: BLE001 — NXDOMAIN/timeout = not registered
                return None
        return {"domain": d, "fuzzer": perm.get("fuzzer"), "ips": [r.address for r in ans]}

    resolved = [r for r in await asyncio.gather(*(_resolve(p) for p in perms)) if r]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []
    root = f"domain:{domain}"
    for r in resolved[:MAX_RESULTS]:
        d = r["domain"]
        findings.append(Finding(
            entity_type="typosquat_domain", platform="dnstwist",
            label=d, url=f"http://{d}", confidence=0.5,
            data={"domain": d, "fuzzer": r["fuzzer"], "ips": r["ips"],
                  "impersonates": domain, "source": "dnstwist"},
        ))
        edges.append(EdgeResult(from_entity=root, to_entity=f"typosquat_domain:{d}",
                                relation="possible_phishing", confidence=0.5))
        for ip in r["ips"][:2]:
            edges.append(EdgeResult(from_entity=f"typosquat_domain:{d}",
                                    to_entity=f"ip:{ip}",
                                    relation="resolves_to", confidence=0.6))

    if len(resolved) > MAX_RESULTS:
        errors.append(f"{NOTE_PREFIX}{len(resolved)} registered look-alikes found; "
                      f"showing the first {MAX_RESULTS}.")
    if not findings:
        errors.append(f"{NOTE_PREFIX}No registered look-alike domains for {domain}.")
    return findings, edges, errors
