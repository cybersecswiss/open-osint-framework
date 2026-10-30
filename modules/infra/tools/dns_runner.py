"""
DNS-records lookup.

A/AAAA/MX/NS/TXT/CNAME via dnspython. Each non-empty record set
becomes a finding; A/AAAA/MX/NS records also produce edges so the
graph picks up infrastructure pivots (shared mailservers, shared
nameservers — classic actor-clustering signals).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from schemas import EdgeResult, Finding

log = logging.getLogger("module-infra.dns")

RECORD_TYPES = ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]


def _resolve_all(domain: str) -> tuple[dict[str, list[str]], list[str]]:
    import dns.resolver  # lazy

    out: dict[str, list[str]] = {}
    errors: list[str] = []
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 8.0
    resolver.timeout = 4.0

    for rt in RECORD_TYPES:
        try:
            answer = resolver.resolve(domain, rt)
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN:
            errors.append(f"NXDOMAIN for {domain}")
            return out, errors
        except dns.resolver.NoNameservers:
            errors.append("DNS: no nameservers")
            continue
        except Exception as e:  # noqa: BLE001
            errors.append(f"DNS {rt} lookup failed: {e}")
            continue
        values: list[str] = []
        for r in answer:
            if rt == "MX":
                values.append(f"{r.preference} {str(r.exchange).rstrip('.')}")
            else:
                values.append(str(r).strip('"').rstrip("."))
        if values:
            out[rt] = values
    return out, errors


def _build(domain: str, records: dict[str, list[str]]) -> tuple[list[Finding], list[EdgeResult]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []

    for rt, values in records.items():
        findings.append(Finding(
            entity_type=f"dns_{rt.lower()}",
            label=f"{rt}:{domain}",
            confidence=0.95,
            data={"domain": domain, "record_type": rt, "values": values, "source": "dns"},
        ))
        # Connect every DNS-record metadata entity back to its parent
        # domain so it shows as part of the same cluster instead of
        # floating off as an island.
        edges.append(EdgeResult(
            from_entity=f"dns_{rt.lower()}:{rt}:{domain}",
            to_entity=f"domain:{domain}",
            relation="record_of",
            confidence=0.95,
        ))

    for ip in records.get("A", []) + records.get("AAAA", []):
        edges.append(EdgeResult(
            from_entity=f"domain:{domain}",
            to_entity=f"ip:{ip}",
            relation="resolves_to",
            confidence=0.95,
        ))
    for mx in records.get("MX", []):
        host = mx.split()[-1].lower()
        edges.append(EdgeResult(
            from_entity=f"domain:{domain}",
            to_entity=f"domain:{host}",
            relation="uses_mailserver",
            confidence=0.9,
        ))
    for ns in records.get("NS", []):
        edges.append(EdgeResult(
            from_entity=f"domain:{domain}",
            to_entity=f"domain:{ns.lower()}",
            relation="uses_nameserver",
            confidence=0.95,
        ))
    return findings, edges


async def run_dns_records(
    domain: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    try:
        records, errors = await asyncio.wait_for(
            asyncio.to_thread(_resolve_all, domain),
            timeout=20,
        )
    except asyncio.TimeoutError:
        return [], [], [f"DNS lookup timeout for {domain}"]

    if not records:
        return [], [], errors or [f"no DNS records found for {domain}"]
    findings, edges = _build(domain, records)
    return findings, edges, errors
