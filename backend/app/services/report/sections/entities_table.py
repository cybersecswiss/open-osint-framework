"""Section 2 — Entities, grouped by type, then sorted by label.

Two things this section deliberately does NOT do any more: print every row a
search produced, and treat graph-connectivity placeholders as findings. A
report over a large domain search used to be a raw list of hundreds of rows,
most of them nodes no tool ever confirmed — unusable as an investigation file. The triage rules live in `report/filters.py` so every
section applies the same ones.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models.case import Case
from app.services.report.base import SectionData, SectionStrings, register_section
from app.services.relevance import rank
from app.services.report.filters import triage

_S = SectionStrings({
    "en": {
        "title": "Entities",
        "no_entities": "No entities have been collected for this case yet.",
        "none_shown": "Every finding in this case is marked as a false positive.",
        "col_label": "Label",
        "col_source": "Source",
        "col_confidence": "Rating",
        "col_evidence": "Evidence",
        "type_count": "{type} ({count})",
        "filtered": "Showing the {shown} findings marked as relevant. "
                    "{suppressed} further findings are not printed.",
        "untriaged": "Showing all {shown} findings — none has been assessed yet.",
        "excluded": "Excluded: {rejected} marked as false positives, "
                    "{placeholders} graph placeholders (unconfirmed edge endpoints).",
    },
    "de": {
        "title": "Entitäten",
        "no_entities": "Für diesen Fall wurden noch keine Entitäten gesammelt.",
        "none_shown": "Alle Funde dieses Falls sind als Fehltreffer markiert.",
        "col_label": "Bezeichnung",
        "col_source": "Quelle",
        "col_confidence": "Bewertung",
        "col_evidence": "Belegstelle",
        "type_count": "{type} ({count})",
        "filtered": "Abgedruckt sind die {shown} als relevant markierten Funde. "
                    "{suppressed} weitere Funde sind nicht abgedruckt.",
        "untriaged": "Abgedruckt sind alle {shown} Funde — es wurde noch keiner bewertet.",
        "excluded": "Ausgenommen: {rejected} als Fehltreffer markiert, "
                    "{placeholders} Graph-Platzhalter (unbestätigte Kantenendpunkte).",
    },
    "fr": {
        "title": "Entités",
        "no_entities": "Aucune entité n'a encore été collectée pour ce dossier.",
        "none_shown": "Toutes les découvertes de ce dossier sont marquées comme faux positifs.",
        "col_label": "Étiquette",
        "col_source": "Source",
        "col_confidence": "Évaluation",
        "col_evidence": "Référence",
        "type_count": "{type} ({count})",
        "filtered": "Affichage des {shown} découvertes marquées pertinentes. "
                    "{suppressed} autres ne sont pas imprimées.",
        "untriaged": "Affichage des {shown} découvertes — aucune n'a encore été évaluée.",
        "excluded": "Exclus : {rejected} marqués faux positifs, "
                    "{placeholders} substituts de graphe (extrémités non confirmées).",
    },
    "it": {
        "title": "Entità",
        "no_entities": "Per questo caso non sono ancora state raccolte entità.",
        "none_shown": "Tutti i risultati di questo caso sono marcati come falsi positivi.",
        "col_label": "Etichetta",
        "col_source": "Fonte",
        "col_confidence": "Valutazione",
        "col_evidence": "Riferimento",
        "type_count": "{type} ({count})",
        "filtered": "Vengono stampati i {shown} risultati marcati come rilevanti. "
                    "Altri {suppressed} non sono stampati.",
        "untriaged": "Vengono stampati tutti i {shown} risultati — nessuno è stato valutato.",
        "excluded": "Esclusi: {rejected} marcati come falsi positivi, "
                    "{placeholders} segnaposto del grafo (estremi non confermati).",
    },
})


@register_section(name="entities_table", order=20, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any], **_kw) -> SectionData:
    entities = agent_data.get("entities") or []
    edges = agent_data.get("edges") or []
    t = triage(entities)
    shown = t["shown"]

    # Within each type, most relevant first rather than alphabetical. A
    # 206-row `domain` group sorted by name buries whatever matters; sorted by
    # corroboration and centrality it starts with it.
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in rank(shown, edges):
        grouped[e.get("entity_type") or "unknown"].append(e)

    groups = [
        {
            "header": _S.t(lang, "type_count", type=type_name, count=len(rows)),
            "rows": rows,
        }
        for type_name, rows in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
    ]

    # State the selection rule in the report itself. A filtered list that
    # doesn't say it is filtered invites the reader to mistake it for the
    # complete picture.
    if not entities:
        scope = None
        empty = _S.t(lang, "no_entities")
    elif not shown:
        scope = None
        empty = _S.t(lang, "none_shown")
    else:
        empty = None
        scope = (
            _S.t(lang, "filtered", shown=len(shown), suppressed=t["suppressed"])
            if t["filtered"]
            else _S.t(lang, "untriaged", shown=len(shown))
        )

    excluded = None
    if t["rejected"] or t["placeholders"]:
        excluded = _S.t(lang, "excluded",
                        rejected=len(t["rejected"]),
                        placeholders=len(t["placeholders"]))

    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/entities_table.html",
        context={
            "groups": groups,
            "no_entities": empty,
            "scope": scope,
            "excluded": excluded,
            "S": {k: _S.t(lang, k) for k in
                  ("col_label", "col_source", "col_confidence", "col_evidence")},
        },
    )
