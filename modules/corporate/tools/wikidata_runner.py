"""Entity structure and affiliations — Wikidata (keyless).

Wikidata is a curated, sourced knowledge graph, and for this module it fills
a gap the registers cannot: **relationships that cross jurisdictions and
record types**. A commercial register knows a company's officers in one
country; Wikidata knows that the company is a subsidiary of another, who
chairs it, which state owns a stake, and which people held which position
when.

It is community-maintained, so it is a *lead* source, not a record — findings
rate Admiralty **C**, and every one carries its Wikidata item id so the
statement can be traced to its own references.

Two properties do most of the work for procurement cases:
`parent organization` / `owned by` for the corporate chain, and
`chairperson` / `chief executive officer` / `board member` for people.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

API = "https://www.wikidata.org/w/api.php"
WEB = "https://www.wikidata.org/wiki/{qid}"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
MAX_ITEMS = 3
MAX_PER_PROPERTY = 8

log = logging.getLogger("module-corporate.wikidata")

# property id -> (edge relation, entity type of the far end, confidence)
_PROPERTIES: dict[str, tuple[str, str, float]] = {
    "P749":  ("subsidiary_of", "organization", 0.8),      # parent organization
    "P127":  ("owned_by", "organization", 0.8),           # owned by
    "P355":  ("parent_of", "organization", 0.8),          # has subsidiary
    "P1830": ("owns", "organization", 0.7),               # owner of
    "P488":  ("chair", "person", 0.75),                   # chairperson
    "P169":  ("chief_executive", "person", 0.75),         # CEO
    "P3320": ("board_member", "person", 0.7),             # board member
    "P1037": ("director", "person", 0.7),                 # director/manager
    "P112":  ("founded_by", "person", 0.7),               # founded by
    "P17":   ("country", "location", 0.8),                # country
    "P159":  ("headquarters", "location", 0.8),           # headquarters location
    "P1454": ("legal_form", "legal_form", 0.7),           # legal form
}


async def _search(client: httpx.AsyncClient, term: str) -> list[dict]:
    r = await client.get(API, params={
        "action": "wbsearchentities", "search": term,
        "language": "en", "uselang": "en", "format": "json", "limit": MAX_ITEMS,
    })
    r.raise_for_status()
    return r.json().get("search") or []


async def _entities(client: httpx.AsyncClient, qids: list[str]) -> dict[str, Any]:
    if not qids:
        return {}
    r = await client.get(API, params={
        "action": "wbgetentities", "ids": "|".join(qids),
        "props": "labels|descriptions|claims", "languages": "en|de|fr|it",
        "format": "json",
    })
    r.raise_for_status()
    return r.json().get("entities") or {}


def _label(entity: dict, fallback: str = "") -> str:
    labels = entity.get("labels") or {}
    for lang in ("en", "de", "fr", "it"):
        if labels.get(lang, {}).get("value"):
            return labels[lang]["value"]
    return fallback


def _claim_targets(entity: dict, prop: str) -> list[str]:
    """Q-ids referenced by a property."""
    out = []
    for claim in (entity.get("claims") or {}).get(prop, []):
        dv = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(dv, dict) and dv.get("id"):
            out.append(dv["id"])
    return out[:MAX_PER_PROPERTY]


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["wikidata_entity: empty search term"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        try:
            matches = await _search(client, term)
        except (httpx.HTTPError, ValueError) as e:
            return [], [], [f"wikidata_entity: Wikidata unreachable: {e}"]
        if not matches:
            return [], [], [f"{NOTE_PREFIX}wikidata_entity: no Wikidata item "
                            f"matches '{term}'."]

        qids = [m["id"] for m in matches[:MAX_ITEMS] if m.get("id")]
        try:
            entities = await _entities(client, qids)
        except (httpx.HTTPError, ValueError) as e:
            return [], [], [f"wikidata_entity: item fetch failed: {e}"]

        # Resolve the far ends of every relationship in one further call.
        wanted: set[str] = set()
        for qid in qids:
            ent = entities.get(qid) or {}
            for prop in _PROPERTIES:
                wanted.update(_claim_targets(ent, prop))
        related: dict[str, Any] = {}
        targets = list(wanted)
        for chunk in [targets[i:i + 45] for i in range(0, len(targets), 45)]:
            try:
                related.update(await _entities(client, chunk))
            except (httpx.HTTPError, ValueError):
                errors.append(f"{NOTE_PREFIX}wikidata_entity: some related items "
                              "could not be resolved.")
                break

    root_type = "person" if query_type == "person_name" else "organization"

    for qid in qids:
        ent = entities.get(qid) or {}
        name = _label(ent, term)
        desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "")
        findings.append(Finding(
            entity_type=root_type, label=name, url=WEB.format(qid=qid),
            confidence=0.7,
            data={"wikidata_id": qid, "description": desc,
                  "note": "community-maintained knowledge base — a lead, not a record",
                  "source": "wikidata"},
        ))
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}", to_entity=f"{root_type}:{name}",
            relation="matches_entity", confidence=0.7,
        ))

        for prop, (relation, far_type, conf) in _PROPERTIES.items():
            for target_qid in _claim_targets(ent, prop):
                target = related.get(target_qid) or {}
                target_name = _label(target)
                if not target_name:
                    continue
                findings.append(Finding(
                    entity_type=far_type, label=target_name,
                    url=WEB.format(qid=target_qid), confidence=conf,
                    data={"wikidata_id": target_qid, "relation_to_query": relation,
                          "source": "wikidata"},
                ))
                edges.append(EdgeResult(
                    from_entity=f"{root_type}:{name}",
                    to_entity=f"{far_type}:{target_name}",
                    relation=relation, confidence=conf,
                    data={"wikidata_property": prop},
                ))

    return findings, edges, errors
