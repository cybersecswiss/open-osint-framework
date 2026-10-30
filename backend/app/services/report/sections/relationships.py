"""Section 2b — Relationships, grouped by type, with the tool that asserted each.

Originally the edges appeared in the report as a single number in the
summary (`"edges": len(...)`). A report that lists entities but not how they
connect is a list of hits, not an investigation product — the connections
*are* the finding.

Each row cites its source tool. That only became possible once `edge.source`
survived the framework→agent boundary; before that the information existed
in the framework and died on the way to the customer's store.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models.case import Case
from app.services.report.base import SectionData, SectionStrings, register_section
from app.services.report.filters import entity_index, is_placeholder

# Cap per relation type. A domain search can produce 271 `has_subdomain`
# edges; printing all of them buries the three that matter. The number of
# omitted rows is always printed — a silent cap reads as completeness.
_MAX_PER_GROUP = 40

_S = SectionStrings({
    "en": {
        "title": "Relationships",
        "none": "No relationships have been recorded for this case yet.",
        "col_from": "From",
        "col_to": "To",
        "col_source": "Source",
        "col_confidence": "Conf.",
        "type_count": "{type} ({count})",
        "truncated": "… and {n} more of this type (not printed).",
        "intro": "{edges} connections between {entities} entities, grouped by type.",
    },
    "de": {
        "title": "Beziehungen",
        "none": "Für diesen Fall wurden noch keine Beziehungen erfasst.",
        "col_from": "Von",
        "col_to": "Nach",
        "col_source": "Quelle",
        "col_confidence": "Konf.",
        "type_count": "{type} ({count})",
        "truncated": "… und {n} weitere dieses Typs (nicht abgedruckt).",
        "intro": "{edges} Verbindungen zwischen {entities} Entitäten, nach Typ gruppiert.",
    },
    "fr": {
        "title": "Relations",
        "none": "Aucune relation n'a encore été enregistrée pour ce dossier.",
        "col_from": "De",
        "col_to": "Vers",
        "col_source": "Source",
        "col_confidence": "Conf.",
        "type_count": "{type} ({count})",
        "truncated": "… et {n} autres de ce type (non imprimées).",
        "intro": "{edges} connexions entre {entities} entités, groupées par type.",
    },
    "it": {
        "title": "Relazioni",
        "none": "Per questo caso non sono ancora state registrate relazioni.",
        "col_from": "Da",
        "col_to": "A",
        "col_source": "Fonte",
        "col_confidence": "Aff.",
        "type_count": "{type} ({count})",
        "truncated": "… e altre {n} di questo tipo (non stampate).",
        "intro": "{edges} connessioni tra {entities} entità, raggruppate per tipo.",
    },
})


def _describe(index: dict[str, dict[str, Any]], entity_id: Any) -> str:
    """Human-readable endpoint. Placeholders are marked as such rather than
    silently rendered as ordinary nodes — an endpoint nobody confirmed is a
    weaker claim than one a tool returned."""
    ent = index.get(str(entity_id))
    if not ent:
        return "—"
    label = ent.get("label") or "—"
    etype = ent.get("entity_type") or "?"
    suffix = " ·" if is_placeholder(ent) else ""
    return f"{label} ({etype}){suffix}"


@register_section(name="relationships", order=25, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any], **_kw) -> SectionData:
    entities = agent_data.get("entities") or []
    edges = agent_data.get("edges") or []
    index = entity_index(entities)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in edges:
        grouped[e.get("relation_type") or "unknown"].append(e)

    groups = []
    for rel_type, rows in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        rows.sort(key=lambda r: (
            -(float(r.get("confidence") or 0)),
            _describe(index, r.get("from_entity")).lower(),
        ))
        printed = rows[:_MAX_PER_GROUP]
        groups.append({
            "header": _S.t(lang, "type_count", type=rel_type, count=len(rows)),
            "rows": [
                {
                    "from": _describe(index, r.get("from_entity")),
                    "to": _describe(index, r.get("to_entity")),
                    "source": r.get("source") or "—",
                    "confidence": r.get("confidence"),
                }
                for r in printed
            ],
            "truncated": (
                _S.t(lang, "truncated", n=len(rows) - len(printed))
                if len(rows) > len(printed) else None
            ),
        })

    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/relationships.html",
        context={
            "groups": groups,
            "empty_note": _S.t(lang, "none") if not edges else None,
            "intro": (
                _S.t(lang, "intro", edges=len(edges), entities=len(entities))
                if edges else None
            ),
            "S": {k: _S.t(lang, k) for k in
                  ("col_from", "col_to", "col_source", "col_confidence")},
        },
    )
