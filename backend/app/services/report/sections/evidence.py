"""Section 6 — Evidence appendix: one citable line per finding.

The entity table names findings; this names *where each one came from*. For
a case file that is the difference between an assertion and a citation:
source URL, the tool that retrieved it, when the source said it
(`observed_at`) and when we stored it (`found_at`).

Only findings the report actually shows appear here — the appendix follows
the same triage rules as the entity table (`report/filters.py`), so the two
can never disagree about what the case contains.

This section depends on `graph_builder` keeping `Finding.url` and
`Finding.found_at`; the runners always set them, but they used to be
discarded, which left nothing to cite.
"""
from __future__ import annotations

from typing import Any

from app.models.case import Case
from app.services.report.base import (
    SectionData, SectionStrings, fmt_dt, register_section)
from app.services.report.filters import triage

_S = SectionStrings({
    "en": {
        "title": "Evidence",
        "none": "None of the findings in this case carries a source reference.",
        "intro": "{with_url} of {total} shown findings carry a source reference.",
        "col_label": "Finding",
        "col_source": "Tool",
        "col_observed": "Observed",
        "col_stored": "Stored",
        "col_url": "Source",
        "no_url": "{n} shown findings carry no source reference and are not listed here.",
    },
    "de": {
        "title": "Belegstellen",
        "none": "Keiner der Funde dieses Falls trägt eine Quellenangabe.",
        "intro": "{with_url} von {total} abgedruckten Funden tragen eine Quellenangabe.",
        "col_label": "Fund",
        "col_source": "Werkzeug",
        "col_observed": "Beobachtet",
        "col_stored": "Gespeichert",
        "col_url": "Quelle",
        "no_url": "{n} abgedruckte Funde tragen keine Quellenangabe und sind hier "
                  "nicht aufgeführt.",
    },
    "fr": {
        "title": "Références",
        "none": "Aucune découverte de ce dossier ne porte de référence de source.",
        "intro": "{with_url} des {total} découvertes affichées portent une référence.",
        "col_label": "Découverte",
        "col_source": "Outil",
        "col_observed": "Observé",
        "col_stored": "Enregistré",
        "col_url": "Source",
        "no_url": "{n} découvertes affichées ne portent aucune référence et ne sont "
                  "pas listées ici.",
    },
    "it": {
        "title": "Riferimenti",
        "none": "Nessun risultato di questo caso riporta un riferimento alla fonte.",
        "intro": "{with_url} dei {total} risultati stampati riportano un riferimento.",
        "col_label": "Risultato",
        "col_source": "Strumento",
        "col_observed": "Osservato",
        "col_stored": "Memorizzato",
        "col_url": "Fonte",
        "no_url": "{n} risultati stampati non riportano riferimenti e non sono "
                  "elencati qui.",
    },
})


def _stamp(value: Any) -> str:
    """Report-timezone timestamp, minute precision.

    This used to slice the raw ISO string (`text[:16]`), which printed
    whatever zone the value happened to carry — in practice UTC — with no
    marker saying so. `observed_at` is the evidentiary field here, so the
    column that states when something was seen has to agree with the rest of
    the document and with the screen. `fmt_dt` is that single answer.
    """
    return fmt_dt(value)


@register_section(name="evidence", order=60, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any], **_kw) -> SectionData:
    shown = triage(agent_data.get("entities") or [])["shown"]
    cited = [e for e in shown if e.get("url")]
    cited.sort(key=lambda e: ((e.get("source") or "").lower(), (e.get("label") or "").lower()))

    if not cited:
        return SectionData(
            title=_S.t(lang, "title"),
            template="sections/evidence.html",
            context={"empty_note": _S.t(lang, "none")},
        )

    uncited = len(shown) - len(cited)
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/evidence.html",
        context={
            "intro": _S.t(lang, "intro", with_url=len(cited), total=len(shown)),
            "rows": [
                {
                    "label": e.get("label") or "—",
                    "entity_type": e.get("entity_type") or "?",
                    "source": e.get("source") or "—",
                    "observed": _stamp(e.get("observed_at")),
                    "stored": _stamp(e.get("found_at")),
                    "url": e.get("url"),
                }
                for e in cited
            ],
            "no_url": _S.t(lang, "no_url", n=uncited) if uncited else None,
            "S": {k: _S.t(lang, k) for k in
                  ("col_label", "col_source", "col_observed", "col_stored", "col_url")},
        },
    )
