"""
WHOIS lookup wrapper.

For domains we use the python-whois library (which shells out to the
system `whois` binary if needed). For IPs we hit the system whois CLI
directly because RFC 9224 RDAP/JSON would require chasing referrals
across multiple RIRs.

Output is best-effort and key fields are normalized (registrar,
creation/expiry dates, registrant org). Edges link the queried entity
to its registrar and registrant for graph pivoting.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

from schemas import EdgeResult, Finding

log = logging.getLogger("module-infra.whois")


def _stringify(v: Any) -> str:
    if isinstance(v, list) and v:
        v = v[0]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v) if v is not None else ""


def _domain_lookup(domain: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    import whois  # lazy import — keeps healthcheck lean

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        w = whois.whois(domain)
    except Exception as e:  # noqa: BLE001
        return findings, edges, [f"whois lookup failed for {domain}: {e}"]

    if not w or not w.get("domain_name"):
        return findings, edges, [f"whois returned no data for {domain}"]

    registrar = _stringify(w.get("registrar"))
    registrant_org = _stringify(w.get("org") or w.get("registrant_organization"))
    registrant_country = _stringify(w.get("country"))
    creation = _stringify(w.get("creation_date"))
    expiration = _stringify(w.get("expiration_date"))
    name_servers = w.get("name_servers") or []
    if isinstance(name_servers, str):
        name_servers = [name_servers]

    findings.append(Finding(
        entity_type="whois_record",
        label=f"whois:{domain}",
        confidence=0.9,
        data={
            "domain": domain,
            "registrar": registrar,
            "registrant_org": registrant_org,
            "registrant_country": registrant_country,
            "creation_date": creation,
            "expiration_date": expiration,
            "name_servers": [str(n).lower() for n in name_servers if n],
            "source": "whois",
        },
    ))
    # The whois record is metadata about the domain — link it back so
    # it doesn't float as an isolated graph node.
    edges.append(EdgeResult(
        from_entity=f"whois_record:whois:{domain}",
        to_entity=f"domain:{domain}",
        relation="describes",
        confidence=0.95,
    ))

    if registrar:
        edges.append(EdgeResult(
            from_entity=f"domain:{domain}",
            to_entity=f"organization:registrar:{registrar.lower()}",
            relation="registered_with",
            confidence=0.9,
        ))
    if registrant_org:
        edges.append(EdgeResult(
            from_entity=f"domain:{domain}",
            to_entity=f"organization:{registrant_org.lower()}",
            relation="registered_to",
            confidence=0.85,
        ))
    for ns in name_servers:
        ns_clean = str(ns).lower().rstrip(".")
        if not ns_clean:
            continue
        edges.append(EdgeResult(
            from_entity=f"domain:{domain}",
            to_entity=f"domain:{ns_clean}",
            relation="uses_nameserver",
            confidence=0.95,
        ))

    return findings, edges, errors


async def _ip_lookup(ip: str) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    try:
        proc = await asyncio.create_subprocess_exec(
            "whois", ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        return findings, edges, [f"whois IP lookup timeout for {ip}"]
    except FileNotFoundError:
        return findings, edges, ["whois binary not installed"]

    text = stdout.decode(errors="replace")
    org = country = netname = ""
    for raw in text.splitlines():
        line = raw.strip()
        low = line.lower()
        if low.startswith("orgname:") or low.startswith("org-name:"):
            org = line.split(":", 1)[1].strip()
        elif low.startswith("country:"):
            country = line.split(":", 1)[1].strip()
        elif low.startswith("netname:"):
            netname = line.split(":", 1)[1].strip()

    if not (org or netname):
        return findings, edges, [f"whois returned no usable data for {ip}"]

    findings.append(Finding(
        entity_type="whois_record",
        label=f"whois:{ip}",
        confidence=0.85,
        data={
            "ip": ip, "org": org, "country": country, "netname": netname,
            "source": "whois",
        },
    ))
    edges.append(EdgeResult(
        from_entity=f"whois_record:whois:{ip}",
        to_entity=f"ip:{ip}",
        relation="describes",
        confidence=0.95,
    ))
    if org:
        edges.append(EdgeResult(
            from_entity=f"ip:{ip}",
            to_entity=f"organization:{org.lower()}",
            relation="hosted_by",
            confidence=0.85,
        ))
    return findings, edges, errors


async def run_whois(
    query: str, query_type: str, job_id: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    if query_type == "ip":
        return await _ip_lookup(query)
    # default: treat as domain (sync lib → run in thread)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_domain_lookup, query),
            timeout=45,
        )
    except asyncio.TimeoutError:
        return [], [], [f"whois domain lookup timeout for {query}"]
