"""Case export: CSV, Maltego CSV, MISP event, STIX 2.1 bundle.

A case that can only leave the system as a PDF is a dead end. Cybercrime work
is cooperative: findings go to another force, into a MISP community, or into
whatever link-analysis tool the receiving unit already runs. Four formats
cover that, and each is deliberately lossy in a *documented* way rather than
pretending to be a full fidelity dump.

  csv       one row per finding — the format everyone can open
  maltego   link-oriented CSV for Maltego's table import
  misp      a MISP Event with attributes, ready for POST /events
  stix      a STIX 2.1 bundle (indicators + relationships)

Two rules run through all of them:

* **Placeholders never leave.** A `data.virtual` node is an edge endpoint no
  tool confirmed. Exporting it would hand a partner agency an assertion
  nobody ever made.
* **Provenance travels.** Source tool, corroborating tools, the Admiralty
  rating and the source URL are carried in every format that has somewhere to
  put them. An IOC without provenance is not intelligence, it is a rumour.
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.relevance import score_entities

# --- shared helpers -------------------------------------------------------

FORMATS = ("csv", "maltego", "misp", "stix")

_HASH_RE = {
    32: "MD5",
    40: "SHA-1",
    64: "SHA-256",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _is_placeholder(entity: dict[str, Any]) -> bool:
    """An unconfirmed edge endpoint — but NOT the search root.

    The node for the selector the investigator searched for is technically a
    virtual node too, and it anchors most of the graph. Dropping it as
    "unconfirmed" severed nearly every relationship in the export: hundreds
    of edges collapsed to a couple of dozen, because almost all of them start
    at the root. It is the
    subject of the investigation, so it travels; the endpoints nobody
    confirmed do not.
    """
    data = entity.get("data") or {}
    return bool(data.get("virtual")) and not data.get("root")


def _real_entities(entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entities if not _is_placeholder(e)]


def _prepare(
    entities: list[dict[str, Any]], edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop placeholders, drop the edges that only they held up, rank the rest."""
    kept = _real_entities(entities)
    ids = {str(e.get("id")) for e in kept}
    live_edges = [
        x for x in edges
        if str(x.get("from_entity")) in ids and str(x.get("to_entity")) in ids
    ]
    scores = score_entities(entities, edges)
    for e in kept:
        e = e  # noqa: PLW2901
        e["relevance_score"] = scores.get(str(e.get("id")), 0.0)
    kept.sort(key=lambda e: (-e.get("relevance_score", 0.0), (e.get("label") or "").lower()))
    return kept, live_edges


def _provenance(entity: dict[str, Any]) -> str:
    """One-line, human-readable provenance for formats with a free-text slot."""
    bits = []
    tools = entity.get("corroborated_by") or []
    if len(tools) > 1:
        bits.append("confirmed by " + ", ".join(tools))
    elif tools:
        bits.append("source: " + tools[0])
    elif entity.get("source"):
        bits.append("source: " + str(entity["source"]))
    if entity.get("admiralty"):
        bits.append("rating " + str(entity["admiralty"]))
    if entity.get("observed_at"):
        bits.append("observed " + str(entity["observed_at"])[:19])
    if entity.get("url"):
        bits.append(str(entity["url"]))
    if entity.get("notes"):
        bits.append("note: " + str(entity["notes"]))
    return " | ".join(bits)


# --- CSV ------------------------------------------------------------------

_CSV_COLUMNS = [
    "label", "entity_type", "admiralty", "corroborated_by", "sources",
    "relevance_score", "is_relevant", "url", "observed_at", "found_at",
    "notes", "id",
]


def to_csv(entities: list[dict[str, Any]], edges: list[dict[str, Any]], **_kw) -> str:
    kept, _ = _prepare(entities, edges)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for e in kept:
        tools = e.get("corroborated_by") or []
        writer.writerow({
            "label": e.get("label"),
            "entity_type": e.get("entity_type"),
            "admiralty": e.get("admiralty") or "",
            "corroborated_by": len(tools),
            "sources": ", ".join(tools) or (e.get("source") or ""),
            "relevance_score": e.get("relevance_score"),
            "is_relevant": "" if e.get("is_relevant") is None else e.get("is_relevant"),
            "url": e.get("url") or "",
            "observed_at": e.get("observed_at") or "",
            "found_at": e.get("found_at") or "",
            "notes": e.get("notes") or "",
            "id": e.get("id"),
        })
    return buf.getvalue()


# --- Maltego --------------------------------------------------------------

def to_maltego_csv(
    entities: list[dict[str, Any]], edges: list[dict[str, Any]], **_kw
) -> str:
    """Link-oriented CSV for Maltego's "import graph from table".

    One row per relation, plus a row per unconnected finding so isolated hits
    are not silently lost — a partner importing this must see everything the
    case holds, not just the connected component.
    """
    kept, live_edges = _prepare(entities, edges)
    by_id = {str(e.get("id")): e for e in kept}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["SourceType", "SourceValue", "LinkLabel", "TargetType",
                     "TargetValue", "LinkSource", "Rating"])

    connected: set[str] = set()
    for x in live_edges:
        src = by_id.get(str(x.get("from_entity")))
        dst = by_id.get(str(x.get("to_entity")))
        if not src or not dst:
            continue
        connected.add(str(src.get("id")))
        connected.add(str(dst.get("id")))
        tools = x.get("corroborated_by") or ([x["source"]] if x.get("source") else [])
        writer.writerow([
            src.get("entity_type"), src.get("label"),
            x.get("relation_type"),
            dst.get("entity_type"), dst.get("label"),
            ", ".join(tools), src.get("admiralty") or "",
        ])

    for e in kept:
        if str(e.get("id")) in connected:
            continue
        writer.writerow([e.get("entity_type"), e.get("label"), "", "", "",
                         ", ".join(e.get("corroborated_by") or []),
                         e.get("admiralty") or ""])
    return buf.getvalue()


# --- MISP -----------------------------------------------------------------

# entity_type → (MISP category, MISP attribute type)
_MISP_MAP: dict[str, tuple[str, str]] = {
    "domain": ("Network activity", "domain"),
    "typosquat_domain": ("Network activity", "domain"),
    "ip": ("Network activity", "ip-dst"),
    "url": ("Network activity", "url"),
    "onion_service": ("Network activity", "hostname"),
    "email_address": ("Social network", "email"),
    "username": ("Social network", "github-username"),
    "social_account": ("Social network", "text"),
    "btc_address": ("Financial fraud", "btc"),
    "eth_address": ("Financial fraud", "text"),
    "vulnerability": ("External analysis", "vulnerability"),
    "asn": ("Network activity", "AS"),
    "phone": ("Person", "phone-number"),
    "person": ("Person", "text"),
    "organization": ("Other", "text"),
    # Contact identifiers actors advertise on crime forums. MISP has a
    # dedicated `jabber-id` type; Tox and Session do not exist there, so they
    # go out as `text` under Social network rather than being forced into a
    # type that means something else on the receiving side.
    "jabber_id": ("Social network", "jabber-id"),
    "tox_id": ("Social network", "text"),
    "session_id": ("Social network", "text"),
    "pgp_key": ("Social network", "pgp-public-key"),
    # Added with the newer sources. Without these they fell to
    # ("Other", "text"), which is not wrong but tells the receiving analyst
    # nothing about what kind of statement the row is.
    "ransomware_group": ("Attribution", "threat-actor"),
    "threat_actor": ("Attribution", "threat-actor"),
    "ransomware_victim": ("Other", "target-user"),
    "ransom_note": ("Payload delivery", "text"),
    "darknet_market": ("Other", "text"),
    "machine_code": ("Payload delivery", "text"),
    # Both hashes are murmur3 fingerprints for pivoting, not payload hashes —
    # "Other/text" is the honest place for them. Putting them under Payload
    # delivery would invite a receiving instance to treat them as file
    # hashes and hunt for a file that does not exist.
    "favicon_hash": ("Other", "text"),
    "dom_hash": ("Other", "text"),
}


# Entity types that name an ACTOR rather than an observable, and the MISP
# galaxy each maps to. A galaxy cluster is how a receiving instance links our
# event to everything it already knows about that group — without it, an
# analyst on the other side gets the string "akira" and has to recognise it.
#
# The galaxy tag is emitted on the EVENT, not on the attribute: MISP galaxies
# describe what an event is about, and an attribute-level cluster would claim
# that the IP *is* the actor rather than that it belongs to their activity.
#
# `misp-galaxy:ransomware` is used rather than `threat-actor` for groups: the
# cluster names in that galaxy are the leak-site names our sources report
# ("akira", "lockbit3"), so they match without a translation table we would
# then have to maintain and would silently get wrong.
_GALAXY_FOR_TYPE: dict[str, str] = {
    "ransomware_group": "misp-galaxy:ransomware",
    "threat_actor": "misp-galaxy:threat-actor",
}


def _galaxy_tags(entities: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Event-level galaxy clusters for the actors named in this case.

    **Rejected leads are excluded here even though they still appear as
    attributes.** `_prepare` drops placeholders and nothing else — the
    relevance filter lives in the report, not in the exports — so an entity
    the analyst marked `is_relevant = False` does travel out as an attribute.
    For an attribute that is defensible: it is one row among many, carrying
    its provenance, and `to_ids` already keeps it out of detection.

    A galaxy tag is not that. It sits on the EVENT and says what the case is
    about. Attributing an investigation to a group the analyst examined and
    threw out would be a conclusion nobody drew, stated in the one place a
    receiving instance reads first.

    Names go out as reported: inventing a canonical spelling would be a claim
    about identity we cannot support.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for e in entities:
        galaxy = _GALAXY_FOR_TYPE.get(e.get("entity_type") or "")
        label = str(e.get("label") or "").strip()
        if not galaxy or not label or e.get("is_relevant") is False:
            continue
        tag = f'{galaxy}="{label}"'
        if tag in seen:
            continue
        seen.add(tag)
        out.append({"name": tag})
    return out


def _misp_attribute(entity: dict[str, Any]) -> dict[str, Any]:
    etype = entity.get("entity_type") or ""
    label = str(entity.get("label") or "")

    if etype == "hash":
        attr_type = _HASH_RE.get(len(label.strip()), "other")
        category = "Payload delivery"
    else:
        category, attr_type = _MISP_MAP.get(etype, ("Other", "text"))

    tags = []
    if entity.get("admiralty"):
        tags.append({"name": f'admiralty-scale:source-reliability="{entity["admiralty"][0]}"'})
        tags.append({"name": f'admiralty-scale:information-credibility="{entity["admiralty"][1:]}"'})
    if len(entity.get("corroborated_by") or []) > 1:
        tags.append({"name": 'osint:certainty="corroborated"'})

    return {
        "uuid": str(entity.get("id")),
        "category": category,
        "type": attr_type,
        "value": label,
        # to_ids stays False unless the analyst marked it relevant: pushing
        # unvetted OSINT straight into detection rules is how a partner ends
        # up alerting on their own DNS resolver.
        "to_ids": entity.get("is_relevant") is True,
        "comment": _provenance(entity)[:65535],
        "disable_correlation": False,
        "Tag": tags,
    }


def to_misp(
    entities: list[dict[str, Any]], edges: list[dict[str, Any]],
    case: Any = None, **_kw,
) -> str:
    kept, _ = _prepare(entities, edges)
    title = getattr(case, "title", None) or "OSINT case"
    number = getattr(case, "case_number", None) or ""
    event = {
        "Event": {
            "uuid": str(uuid.uuid4()),
            "info": f"{number} {title}".strip(),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            # 2 = "Moderate" distribution default; the receiving instance's
            # admin decides what to do with it. Never default to "All".
            "distribution": "1",
            "threat_level_id": "3",
            "analysis": "1",
            "published": False,
            "Attribute": [_misp_attribute(e) for e in kept],
            "Tag": ([{"name": 'osint:source-type="block-or-filter-list"'}]
                    + _galaxy_tags(kept)),
        }
    }
    return json.dumps(event, indent=2, ensure_ascii=False)


# --- STIX 2.1 -------------------------------------------------------------

_STIX_PATTERN: dict[str, str] = {
    "domain": "[domain-name:value = '{v}']",
    "typosquat_domain": "[domain-name:value = '{v}']",
    "onion_service": "[domain-name:value = '{v}']",
    "url": "[url:value = '{v}']",
    "email_address": "[email-addr:value = '{v}']",
    "asn": "[autonomous-system:number = '{n}']",
}


def _stix_pattern(entity: dict[str, Any]) -> str | None:
    etype = entity.get("entity_type") or ""
    value = str(entity.get("label") or "").replace("'", "\\'")
    if not value:
        return None
    if etype == "ip":
        kind = "ipv6-addr" if ":" in value else "ipv4-addr"
        return f"[{kind}:value = '{value}']"
    if etype == "hash":
        algo = _HASH_RE.get(len(value))
        return f"[file:hashes.'{algo}' = '{value}']" if algo else None
    if etype == "asn":
        digits = re.sub(r"\D", "", value)
        return _STIX_PATTERN["asn"].format(n=digits) if digits else None
    template = _STIX_PATTERN.get(etype)
    return template.format(v=value) if template else None


def _stix_id(prefix: str, entity_id: Any) -> str:
    """Deterministic STIX id from our own uuid, so re-exporting an unchanged
    case produces the same bundle rather than a new set of objects the
    receiving system treats as new intelligence."""
    return f"{prefix}--{entity_id}"


def to_stix(
    entities: list[dict[str, Any]], edges: list[dict[str, Any]],
    case: Any = None, tenant_name: str = "OOF", **_kw,
) -> str:
    kept, live_edges = _prepare(entities, edges)
    created = _now()
    identity_id = f"identity--{uuid.uuid5(uuid.NAMESPACE_DNS, tenant_name)}"

    objects: list[dict[str, Any]] = [{
        "type": "identity", "spec_version": "2.1", "id": identity_id,
        "created": created, "modified": created,
        "name": tenant_name, "identity_class": "organization",
    }]

    exported: dict[str, str] = {}
    unmapped = 0
    for e in kept:
        eid = str(e.get("id"))
        pattern = _stix_pattern(e)
        labels = [str(e.get("entity_type") or "unknown")]
        if len(e.get("corroborated_by") or []) > 1:
            labels.append("corroborated")

        common = {
            "spec_version": "2.1",
            "created": created, "modified": created,
            "created_by_ref": identity_id,
            "name": str(e.get("label") or "")[:250],
            "labels": labels,
            "external_references": (
                [{"source_name": str(e.get("source") or "osint"),
                  "url": str(e.get("url"))}]
                if e.get("url") else []
            ),
        }
        if pattern:
            obj = {
                "type": "indicator", "id": _stix_id("indicator", eid),
                "pattern": pattern, "pattern_type": "stix",
                "valid_from": str(e.get("observed_at") or e.get("found_at") or created),
                **common,
            }
            if e.get("admiralty"):
                obj["confidence"] = _admiralty_to_confidence(str(e["admiralty"]))
        else:
            # No standard observable for this kind — a custom object keeps the
            # finding in the bundle instead of dropping it silently.
            unmapped += 1
            # Custom PROPERTIES need the `x_` prefix just as much as the
            # custom TYPE does (STIX 2.1 §11.3). These two shipped as bare
            # `entity_type` / `value`, which a strict validator rejects — and
            # a bundle that a TIP refuses at import is worth no more than no
            # bundle at all. Everything else about this export validates, so
            # this was the one thing standing between it and a clean import.
            obj = {
                "type": "x-osint-entity", "id": _stix_id("x-osint-entity", eid),
                "x_entity_type": e.get("entity_type"),
                "x_value": e.get("label"),
                **common,
            }
        if e.get("notes"):
            obj["description"] = str(e["notes"])[:2000]
        objects.append(obj)
        exported[eid] = obj["id"]

    for x in live_edges:
        src = exported.get(str(x.get("from_entity")))
        dst = exported.get(str(x.get("to_entity")))
        if not src or not dst:
            continue
        objects.append({
            "type": "relationship", "spec_version": "2.1",
            "id": _stix_id("relationship", x.get("id") or uuid.uuid4()),
            "created": created, "modified": created,
            "created_by_ref": identity_id,
            "relationship_type": "related-to",
            "description": str(x.get("relation_type") or ""),
            "source_ref": src, "target_ref": dst,
        })

    bundle = {"type": "bundle", "id": f"bundle--{uuid.uuid4()}", "objects": objects}
    if unmapped:
        # Say it in the bundle, not just in our own logs: the receiver needs to
        # know that part of this is outside standard STIX vocabulary.
        objects.insert(1, {
            "type": "note", "spec_version": "2.1",
            "id": f"note--{uuid.uuid5(uuid.NAMESPACE_DNS, 'osint-unmapped')}",
            "created": created, "modified": created,
            "created_by_ref": identity_id,
            "abstract": "Non-standard object types in this bundle",
            "content": (
                f"{unmapped} of {len(kept)} findings have no standard STIX "
                "observable and are exported as `x-osint-entity` custom objects "
                "(x_entity_type + x_value). Placeholders — graph endpoints no "
                "tool confirmed — are excluded entirely."
            ),
            "object_refs": [identity_id],
        })
    return json.dumps(bundle, indent=2, ensure_ascii=False)


def _admiralty_to_confidence(admiralty: str) -> int:
    """Admiralty → the STIX 2.1 confidence scale (0-100).

    STIX has no reliability/credibility pair, so the two collapse into one
    number. The mapping follows the "Admiralty Credibility" table in STIX 2.1
    Appendix A for the digit, nudged down for weak sources — a lossy but
    documented conversion, which is better than omitting confidence entirely.
    """
    credibility = {"1": 90, "2": 70, "3": 50, "4": 30, "5": 10}.get(admiralty[1:], 0)
    penalty = {"A": 0, "B": 0, "C": 5, "D": 15, "E": 25, "F": 10}.get(admiralty[:1], 10)
    return max(0, min(100, credibility - penalty))


RENDERERS = {
    "csv": (to_csv, "text/csv", "csv"),
    "maltego": (to_maltego_csv, "text/csv", "maltego.csv"),
    "misp": (to_misp, "application/json", "misp.json"),
    "stix": (to_stix, "application/json", "stix.json"),
}
