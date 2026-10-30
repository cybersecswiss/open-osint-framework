"""Section 3 — the case graph as a picture.

The connections are the finding, and a table of them is not how anyone
reads a network. This renders the same graph the investigator sees in the
UI, as deterministic inline SVG (see `report/graph_svg.py`).

The caption always states how much of the graph is on the page. A picture
that silently drops half the nodes is worse than no picture.
"""
from __future__ import annotations

from typing import Any

from app.models.case import Case
from app.services.report.base import SectionData, SectionStrings, register_section
from app.services.report.graph_svg import MAX_NODES, build_svg, legend

_S = SectionStrings({
    "en": {
        "title": "Graph",
        "none": "No graph can be drawn — this case has no connected entities yet.",
        "caption": "{drawn} entities and {edges} connections.",
        "omitted": "The {omitted} least connected of {total} entities are not "
                   "drawn (the picture holds the {cap} most connected).",
        "placeholder_note": "Hollow nodes are graph placeholders — edge endpoints "
                            "no tool has confirmed as a finding.",
        "ring_note": "A double ring marks a finding two or more independent "
                     "tools reported.",
        "legend": "Legend",
    },
    "de": {
        "title": "Graph",
        "none": "Es lässt sich kein Graph zeichnen — dieser Fall hat noch keine "
                "verbundenen Entitäten.",
        "caption": "{drawn} Entitäten und {edges} Verbindungen.",
        "omitted": "Die {omitted} am schwächsten verbundenen von {total} Entitäten "
                   "sind nicht gezeichnet (das Bild zeigt die {cap} am stärksten "
                   "verbundenen).",
        "placeholder_note": "Hohle Knoten sind Graph-Platzhalter — Kantenendpunkte, "
                            "die kein Tool als Fund bestätigt hat.",
        "ring_note": "Ein doppelter Ring markiert einen Fund, den zwei oder "
                     "mehr unabhängige Werkzeuge geliefert haben.",
        "legend": "Legende",
    },
    "fr": {
        "title": "Graphe",
        "none": "Aucun graphe ne peut être dessiné — ce dossier n'a pas encore "
                "d'entités connectées.",
        "caption": "{drawn} entités et {edges} connexions.",
        "omitted": "Les {omitted} entités les moins connectées sur {total} ne sont "
                   "pas dessinées (l'image montre les {cap} plus connectées).",
        "placeholder_note": "Les nœuds creux sont des substituts de graphe — des "
                            "extrémités qu'aucun outil n'a confirmées.",
        "ring_note": "Un double anneau marque une découverte rapportée par au "
                     "moins deux outils indépendants.",
        "legend": "Légende",
    },
    "it": {
        "title": "Grafo",
        "none": "Non è possibile disegnare un grafo — questo caso non ha ancora "
                "entità collegate.",
        "caption": "{drawn} entità e {edges} connessioni.",
        "omitted": "Le {omitted} entità meno collegate su {total} non sono "
                   "disegnate (l'immagine mostra le {cap} più collegate).",
        "placeholder_note": "I nodi vuoti sono segnaposto del grafo — estremi che "
                            "nessuno strumento ha confermato.",
        "ring_note": "Un doppio anello marca un risultato riportato da due o "
                     "più strumenti indipendenti.",
        "legend": "Legenda",
    },
})


@register_section(name="graph_snapshot", order=28, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any], **_kw) -> SectionData:
    entities = agent_data.get("entities") or []
    edges = agent_data.get("edges") or []
    if not entities or not edges:
        return SectionData(
            title=_S.t(lang, "title"),
            template="sections/graph_snapshot.html",
            context={"empty_note": _S.t(lang, "none")},
        )

    svg, stats = build_svg(entities, edges)
    if not svg:
        return SectionData(
            title=_S.t(lang, "title"),
            template="sections/graph_snapshot.html",
            context={"empty_note": _S.t(lang, "none")},
        )

    has_placeholder = any((e.get("data") or {}).get("virtual") for e in entities)
    has_corroborated = any(len(e.get("corroborated_by") or []) > 1 for e in entities)

    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/graph_snapshot.html",
        context={
            "svg": svg,
            "caption": _S.t(lang, "caption", drawn=stats["drawn"], edges=stats["edges"]),
            "omitted": (
                _S.t(lang, "omitted", omitted=stats["omitted"],
                     total=len(entities), cap=MAX_NODES)
                if stats["omitted"] else None
            ),
            "placeholder_note": _S.t(lang, "placeholder_note") if has_placeholder else None,
            "ring_note": _S.t(lang, "ring_note") if has_corroborated else None,
            "legend_title": _S.t(lang, "legend"),
            "legend": legend(entities),
        },
    )
