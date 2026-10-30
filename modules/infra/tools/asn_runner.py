"""ASN / BGP context from RIPEstat — keyless.

Shodan says what a host runs. This says *who carries it*: the announcing AS,
its holder, the covering prefix and the registry block. That is what turns a
list of IPs into infrastructure — several "unrelated" C2 hosts sitting in one
AS is a bulletproof-hoster pattern, and it is invisible as long as each
address is looked at on its own.

Two calls, both open:

    prefix-overview   IP  → covering prefix + announcing ASN(s) + holder
    as-overview       ASN → holder + registry block

The ASN becomes its own node, so every host that resolves into the same AS
converges on one place in the graph. That convergence IS the finding.
"""
from __future__ import annotations

import logging
import re

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

BASE = "https://stat.ripe.net/data/{call}/data.json"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 30

_ASN_RE = re.compile(r"^(?:AS)?(\d{1,10})$", re.IGNORECASE)

log = logging.getLogger("module-infra.asn")


async def _call(client: httpx.AsyncClient, call: str, resource: str) -> dict | None:
    try:
        r = await client.get(BASE.format(call=call), params={"resource": resource})
    except httpx.HTTPError as e:
        log.warning("ripestat %s failed: %s", call, e)
        return None
    if r.status_code != 200:
        return None
    try:
        payload = r.json()
    except ValueError:
        return None
    if payload.get("status") not in (None, "ok"):
        return None
    return payload.get("data") or None


async def run_asn(
    query: str, query_type: str, job_id: str = "adhoc",
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    selector = (query or "").strip()
    if not selector:
        return [], [], ["asn_lookup: empty query"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
        asn_match = _ASN_RE.match(selector)
        if asn_match:
            # Direct AS lookup: describe the AS itself.
            asn = asn_match.group(1)
            root = f"asn:AS{asn}"
            overview = await _call(client, "as-overview", f"AS{asn}")
            if not overview:
                return findings, edges, [f"asn_lookup: RIPEstat knows no AS{asn}"]
            findings.append(_asn_finding(asn, overview))
            return findings, edges, errors

        # IP path: which prefix covers it, and who announces that prefix.
        root = f"ip:{selector}"
        prefix = await _call(client, "prefix-overview", selector)
        if not prefix:
            return findings, edges, [f"asn_lookup: RIPEstat has no routing data "
                                     f"for '{selector}'"]

        resource = prefix.get("resource")
        announced = bool(prefix.get("announced"))
        if resource:
            findings.append(Finding(
                entity_type="ip_range", label=str(resource), confidence=0.9,
                platform="ripestat",
                data={
                    "announced": announced,
                    "is_less_specific": prefix.get("is_less_specific"),
                    "registry_block": (prefix.get("block") or {}).get("name"),
                    "registry_desc": (prefix.get("block") or {}).get("desc"),
                    "related_prefixes": (prefix.get("related_prefixes") or [])[:10],
                    "source": "ripestat/prefix-overview",
                },
            ))
            edges.append(EdgeResult(
                from_entity=root, to_entity=f"ip_range:{resource}",
                relation="in_prefix", confidence=0.9,
            ))

        if not announced:
            errors.append(f"{NOTE_PREFIX}asn_lookup: {selector} is not currently "
                          "announced in BGP — the prefix shown is the covering "
                          "less-specific block.")

        for entry in prefix.get("asns") or []:
            asn = str(entry.get("asn") or "").strip()
            if not asn:
                continue
            overview = await _call(client, "as-overview", f"AS{asn}")
            findings.append(_asn_finding(asn, overview or {},
                                         holder_fallback=entry.get("holder")))
            edges.append(EdgeResult(
                from_entity=f"asn:AS{asn}", to_entity=root,
                relation="announces", confidence=0.9,
            ))
            if resource:
                edges.append(EdgeResult(
                    from_entity=f"asn:AS{asn}", to_entity=f"ip_range:{resource}",
                    relation="announces", confidence=0.9,
                ))

    if not findings:
        errors.append(f"asn_lookup: no routing information for '{selector}'")
    return findings, edges, errors


def _asn_finding(asn: str, overview: dict, holder_fallback: str | None = None) -> Finding:
    holder = overview.get("holder") or holder_fallback or ""
    block = overview.get("block") or {}
    return Finding(
        entity_type="asn",
        label=f"AS{asn}",
        url=f"https://stat.ripe.net/AS{asn}",
        confidence=0.9,
        platform="ripestat",
        data={
            "holder": holder,
            "announced": overview.get("announced"),
            "registry_block": block.get("name"),
            "registry_desc": block.get("desc"),
            "source": "ripestat/as-overview",
        },
    )
