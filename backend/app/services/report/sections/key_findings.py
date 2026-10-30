"""Section 1b — the twenty findings worth reading first.

A report over a large case used to open with a raw list of several hundred
rows in arbitrary order. This puts the ranked head of the case in front of
the tables, with the reason each entry ranks where it does: how many
independent tools confirmed it, and how the source rates.

The ranking is computed, not stored (see `services/relevance.py`) — mark a
false positive or run another tool and the next report reflects it.
"""
from __future__ import annotations

from typing import Any

from app.models.case import Case
from app.services.relevance import rank
from app.services.report.base import SectionData, SectionStrings, register_section
from app.services.report.filters import triage

TOP_N = 20

_S = SectionStrings({
    "en": {
        "title": "Key findings",
        "none": "No assessable findings in this case yet.",
        "intro": "The {n} highest-ranked of {total} findings. Ranking combines "
                 "corroboration, source reliability, position in the graph and "
                 "distance from the search term.",
        "col_finding": "Finding",
        "col_rating": "Rating",
        "col_confirmed": "Confirmed by",
        "col_score": "Rank",
        "single_source": "single source",
        "footnote": "Rating: source reliability A–F and information credibility "
                    "1–6 (Admiralty). “B2” = usually reliable source, probably "
                    "true information. “1” is only assigned when two or more "
                    "independent tools agree.",
    },
    "de": {
        "title": "Kernaussagen",
        "none": "In diesem Fall gibt es noch keine bewertbaren Funde.",
        "intro": "Die {n} höchstbewerteten von {total} Funden. Die Rangfolge "
                 "kombiniert Mehrfachbestätigung, Quellenzuverlässigkeit, "
                 "Stellung im Graphen und Nähe zum Suchbegriff.",
        "col_finding": "Fund",
        "col_rating": "Bewertung",
        "col_confirmed": "Bestätigt durch",
        "col_score": "Rang",
        "single_source": "eine Quelle",
        "footnote": "Bewertung: Quellenzuverlässigkeit A–F und Informations"
                    "bewertung 1–6 (Admiralty-Skala). „B2“ = üblicherweise "
                    "zuverlässige Quelle, wahrscheinlich zutreffende Information. "
                    "Die „1“ wird nur vergeben, wenn mindestens zwei unabhängige "
                    "Werkzeuge übereinstimmen.",
    },
    "fr": {
        "title": "Constatations principales",
        "none": "Aucune découverte évaluable dans ce dossier.",
        "intro": "Les {n} découvertes les mieux classées sur {total}. Le classement "
                 "combine la corroboration, la fiabilité de la source, la position "
                 "dans le graphe et la distance au terme recherché.",
        "col_finding": "Découverte",
        "col_rating": "Évaluation",
        "col_confirmed": "Confirmé par",
        "col_score": "Rang",
        "single_source": "source unique",
        "footnote": "Évaluation : fiabilité de la source A–F et crédibilité de "
                    "l'information 1–6 (échelle Admiralty). « 1 » n'est attribué "
                    "que si au moins deux outils indépendants concordent.",
    },
    "it": {
        "title": "Risultati principali",
        "none": "In questo caso non ci sono ancora risultati valutabili.",
        "intro": "I {n} risultati con punteggio più alto su {total}. La classifica "
                 "combina corroborazione, affidabilità della fonte, posizione nel "
                 "grafo e distanza dal termine cercato.",
        "col_finding": "Risultato",
        "col_rating": "Valutazione",
        "col_confirmed": "Confermato da",
        "col_score": "Pos.",
        "single_source": "fonte unica",
        "footnote": "Valutazione: affidabilità della fonte A–F e credibilità "
                    "dell'informazione 1–6 (scala Admiralty). L'“1” è assegnato "
                    "solo se almeno due strumenti indipendenti concordano.",
    },
})


@register_section(name="key_findings", order=15, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any], **_kw) -> SectionData:
    entities = agent_data.get("entities") or []
    edges = agent_data.get("edges") or []
    shown = triage(entities)["shown"]
    if not shown:
        return SectionData(
            title=_S.t(lang, "title"),
            template="sections/key_findings.html",
            context={"empty_note": _S.t(lang, "none")},
        )

    ranked = rank(shown, edges)[:TOP_N]
    rows = []
    for position, entity in enumerate(ranked, start=1):
        tools = entity.get("corroborated_by") or []
        rows.append({
            "position": position,
            "label": entity.get("label") or "—",
            "entity_type": entity.get("entity_type") or "?",
            "admiralty": entity.get("admiralty") or "—",
            "confirmed": ", ".join(tools) if len(tools) > 1
                         else (tools[0] if tools else _S.t(lang, "single_source")),
            "corroborated": len(tools) > 1,
            "url": entity.get("url"),
        })

    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/key_findings.html",
        context={
            "rows": rows,
            "intro": _S.t(lang, "intro", n=len(rows), total=len(shown)),
            "footnote": _S.t(lang, "footnote"),
            "S": {k: _S.t(lang, k) for k in
                  ("col_finding", "col_rating", "col_confirmed", "col_score")},
        },
    )
