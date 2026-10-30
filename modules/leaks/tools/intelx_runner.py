"""
IntelX deep-link helper.

IntelX (intelx.io) indexes breach dumps, paste sites, and dark-web
leaks. Their API is paid; this runner just emits a deep-link finding
that opens the public web search for the queried selector. Useful as
a graph anchor — investigator clicks through and confirms manually.

If you later add an INTELX_API_KEY this file is the place to wire
the actual /intelligent/search call.
"""
from __future__ import annotations

import urllib.parse

from schemas import EdgeResult, Finding


async def run_intelx_link(
    query: str, query_type: str
) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    if query_type not in {"email", "domain", "username"}:
        return [], [], [f"IntelX: unsupported query_type={query_type}"]

    encoded = urllib.parse.quote_plus(query)
    url = f"https://intelx.io/?s={encoded}"
    findings = [Finding(
        entity_type="search_link",
        platform="intelx",
        label=f"intelx:{query}",
        url=url,
        confidence=0.4,
        data={
            "query": query, "query_type": query_type,
            "note": "Deep-link only — manual review on intelx.io",
            "source": "intelx",
        },
    )]
    # Hook the deep-link to the queried entity so it doesn't float as
    # an isolated graph node — investigator can pivot from query → link.
    edges = [EdgeResult(
        from_entity=f"{query_type}:{query}",
        to_entity=f"search_link:intelx:{query}",
        relation="search_link_for",
        confidence=0.4,
    )]
    return findings, edges, []
