"""Corporate group structure — GLEIF Legal Entity Identifier (keyless).

The LEI is the global identifier a legal entity needs to trade on financial
markets, and GLEIF publishes the register openly, including **who owns
whom**: direct and ultimate parents, and the children of an entity.

That relationship graph is what makes this useful for a procurement case.
A Swiss branch on its own says little; the same branch shown as a child of
a sanctioned Moscow parent, with the parent's own LEI and registration
number, is a different object. And because the register is name-agnostic —
it will return the entity under its Cyrillic legal name for a Latin query —
it survives the transliteration games that defeat plain name matching.

**Use `filter[fulltext]`.** `filter[entity.legalName]` is an exact match and
returns nothing for a short trade name; the full-text filter finds it inside
the full registered legal name (e.g. a Cyrillic «публичное акционерное общество …»).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from schemas import NOTE_PREFIX, EdgeResult, Finding

BASE = "https://api.gleif.org/api/v1/lei-records"
WEB = "https://search.gleif.org/#/record/{lei}"
USER_AGENT = "OOF/1.0 (+https://github.com/cybersecswiss/open-osint-framework)"
TIMEOUT = 40
MAX_RECORDS = 10
REL_CONCURRENCY = 4

log = logging.getLogger("module-corporate.gleif")

# GLEIF relationship endpoints worth following, and how each maps to an edge.
_RELATIONS = [
    ("direct-parent", "subsidiary_of", 0.9),
    ("ultimate-parent", "ultimately_owned_by", 0.9),
    ("direct-children", "parent_of", 0.9),
]


def _entity_fields(attr: dict[str, Any]) -> dict[str, Any]:
    ent = attr.get("entity") or {}
    addr = ent.get("legalAddress") or {}
    hq = ent.get("headquartersAddress") or {}
    return {
        "lei": attr.get("lei"),
        "name": ((ent.get("legalName") or {}).get("name") or "").strip(),
        "other_names": [
            (n.get("name") or "").strip()
            for n in (ent.get("otherNames") or []) if n.get("name")
        ],
        "status": ent.get("status"),
        "legal_form": ((ent.get("legalForm") or {}).get("id")),
        "registered_as": ent.get("registeredAs"),
        "jurisdiction": ent.get("jurisdiction"),
        "country": addr.get("country") or hq.get("country"),
        "city": addr.get("city") or hq.get("city"),
        "address": ", ".join(x for x in (addr.get("addressLines") or []) if x),
        "postal_code": addr.get("postalCode"),
    }


async def _related(client: httpx.AsyncClient, lei: str, path: str) -> list[dict]:
    """Fetch one relationship set. A 404 means 'no such relationship',
    which is an answer, not a failure."""
    try:
        r = await client.get(f"{BASE}/{lei}/{path}")
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json().get("data")
    except (httpx.HTTPError, ValueError) as e:
        log.info("gleif: %s for %s unavailable: %s", path, lei, e)
        return []
    if isinstance(data, dict):
        data = [data]
    return data or []


async def run(query: str, options: dict | None = None, job_id: str = "adhoc",
              query_type: str = "company_name",
              ) -> tuple[list[Finding], list[EdgeResult], list[str]]:
    term = (query or "").strip()
    if not term:
        return [], [], ["gleif_lei: empty search term"]

    findings: list[Finding] = []
    edges: list[EdgeResult] = []
    errors: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        try:
            r = await client.get(BASE, params={
                "filter[fulltext]": term,       # exact-name filter finds nothing
                "page[size]": str(MAX_RECORDS),
            })
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            return [], [], [f"gleif_lei: GLEIF unreachable: {e}"]
        except ValueError:
            return [], [], ["gleif_lei: non-JSON response from GLEIF"]

        records = payload.get("data") or []
        total = ((payload.get("meta") or {}).get("pagination") or {}).get("total", len(records))
        if not records:
            return [], [], [f"{NOTE_PREFIX}gleif_lei: no LEI record matches '{term}'."]

        sem = asyncio.Semaphore(REL_CONCURRENCY)

        async def rel(lei: str, path: str):
            async with sem:
                return path, await _related(client, lei, path)

        tasks = []
        entities = []
        for rec in records:
            e = _entity_fields(rec.get("attributes") or {})
            if not e["lei"] or not e["name"]:
                continue
            entities.append(e)
            for path, _, _ in _RELATIONS:
                tasks.append(rel(e["lei"], path))
        rel_results = await asyncio.gather(*tasks) if tasks else []

    # Relationship results come back in the order the tasks were queued:
    # len(_RELATIONS) per entity, same order as `entities`.
    per_entity = len(_RELATIONS)
    for idx, e in enumerate(entities):
        findings.append(Finding(
            entity_type="organization",
            label=e["name"],
            url=WEB.format(lei=e["lei"]),
            confidence=0.9,
            data={
                "lei": e["lei"],
                "status": e["status"],
                "jurisdiction": e["jurisdiction"],
                "country": e["country"],
                "city": e["city"],
                "address": e["address"],
                "registered_as": e["registered_as"],
                "other_names": e["other_names"],
                "register": "GLEIF LEI",
                "source": "gleif",
            },
        ))
        findings.append(Finding(
            entity_type="company_id", label=e["lei"], url=WEB.format(lei=e["lei"]),
            confidence=0.95, data={"register": "LEI", "company": e["name"], "source": "gleif"},
        ))
        edges.append(EdgeResult(
            from_entity=f"organization:{e['name']}", to_entity=f"company_id:{e['lei']}",
            relation="has_identifier", confidence=0.95,
        ))
        edges.append(EdgeResult(
            from_entity=f"{query_type}:{term}", to_entity=f"organization:{e['name']}",
            relation="matches_entity", confidence=0.8,
        ))

        # An alias under a different script is exactly what a name search
        # misses, so it is worth its own node.
        for alias in e["other_names"][:5]:
            if alias and alias.lower() != e["name"].lower():
                findings.append(Finding(
                    entity_type="organization", label=alias,
                    url=WEB.format(lei=e["lei"]), confidence=0.75,
                    data={"role": "alternative legal name", "lei": e["lei"],
                          "source": "gleif"},
                ))
                edges.append(EdgeResult(
                    from_entity=f"organization:{e['name']}",
                    to_entity=f"organization:{alias}",
                    relation="also_known_as", confidence=0.8,
                ))

        base = idx * per_entity
        for offset, (path, relation, conf) in enumerate(_RELATIONS):
            if base + offset >= len(rel_results):
                continue
            _, rows = rel_results[base + offset]
            for row in rows[:10]:
                attrs = (row.get("attributes") or {})
                other = _entity_fields(attrs)
                # A relationship record may only carry the LEI of the far end.
                name = other["name"] or (
                    (attrs.get("relationship") or {}).get("endNode", {}).get("id")
                )
                if not name:
                    continue
                findings.append(Finding(
                    entity_type="organization", label=name,
                    url=WEB.format(lei=other["lei"] or ""), confidence=0.85,
                    data={"lei": other["lei"], "country": other["country"],
                          "relation_to_query": relation, "register": "GLEIF LEI",
                          "source": "gleif"},
                ))
                edges.append(EdgeResult(
                    from_entity=f"organization:{e['name']}",
                    to_entity=f"organization:{name}",
                    relation=relation, confidence=conf,
                ))

    if total > len(entities):
        errors.append(f"{NOTE_PREFIX}gleif_lei: {total} LEI records matched, "
                      f"{len(entities)} returned.")
    return findings, edges, errors
