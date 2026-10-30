"""Search log with stated purpose — from the CUSTOMER's activity log.

The "searches" section lists what the operator's job table knows: when, which
modules, which status. What a reviewer asks first — *why* was this person
looked up, on whose order — lives only in the customer's own log
(services/activity.py). This section prints that record,
with the purpose, captures and access changes, as the case file's own
statement of how it was compiled.
"""
from __future__ import annotations

from typing import Any

from app.models.case import Case
from app.services.agent_client import get_from_agent
from app.services.report.base import SectionData, SectionStrings, fmt_dt, register_section

_S = SectionStrings({
    "en": {"title": "Search log", "none": "No logged activity.",
           "unavailable": "The search log could not be read from your authority's data store.",
           "col_when": "When", "col_by": "By", "col_action": "Action", "col_what": "Selector / subject",
           "col_purpose": "Purpose / legal basis", "no_purpose": "not stated",
           "a_search": "Search", "a_watch": "Watch created", "a_rescan": "Automatic rescan",
           "a_capture": "Page saved", "a_access": "Access changed", "a_merge": "Nodes merged"},
    "de": {"title": "Suchprotokoll", "none": "Keine protokollierten Vorgänge.",
           "unavailable": "Das Suchprotokoll konnte nicht aus dem Datenspeicher Ihrer Behörde gelesen werden.",
           "col_when": "Wann", "col_by": "Durch", "col_action": "Vorgang", "col_what": "Suchbegriff / Gegenstand",
           "col_purpose": "Zweck / Rechtsgrundlage", "no_purpose": "nicht angegeben",
           "a_search": "Suche", "a_watch": "Überwachung angelegt", "a_rescan": "Automatische Nachsuche",
           "a_capture": "Seite gesichert", "a_access": "Zugriff geändert", "a_merge": "Knoten zusammengeführt"},
    "fr": {"title": "Journal des recherches", "none": "Aucune opération journalisée.",
           "unavailable": "Le journal des recherches n'a pas pu être lu dans le stockage de votre autorité.",
           "col_when": "Quand", "col_by": "Par", "col_action": "Opération", "col_what": "Terme / objet",
           "col_purpose": "Finalité / base légale", "no_purpose": "non indiquée",
           "a_search": "Recherche", "a_watch": "Surveillance créée", "a_rescan": "Recherche automatique",
           "a_capture": "Page sauvegardée", "a_access": "Accès modifié", "a_merge": "Nœuds fusionnés"},
    "it": {"title": "Registro delle ricerche", "none": "Nessuna operazione registrata.",
           "unavailable": "Non è stato possibile leggere il registro delle ricerche dall'archivio della Sua autorità.",
           "col_when": "Quando", "col_by": "Da", "col_action": "Operazione", "col_what": "Termine / oggetto",
           "col_purpose": "Scopo / base legale", "no_purpose": "non indicato",
           "a_search": "Ricerca", "a_watch": "Monitoraggio creato", "a_rescan": "Ricerca automatica",
           "a_capture": "Pagina salvata", "a_access": "Accesso modificato", "a_merge": "Nodi uniti"},
})

_ACTIONS = {"search.run": "a_search", "monitoring.create": "a_watch", "monitoring.rescan": "a_rescan",
            "evidence.capture": "a_capture", "case.access_change": "a_access", "entity.merge": "a_merge"}


def _subject(e: dict[str, Any]) -> str:
    d = e.get("details") or {}
    if e.get("action") == "entity.merge":
        return ", ".join(m.get("label", "") for m in d.get("merged") or []) + f" → {(d.get('target') or {}).get('label', '')}"
    if e.get("action") == "case.access_change":
        after = d.get("after") or {}
        return ", ".join(after.get("members") or []) or "—"
    q = d.get("query") or "—"
    return f"{q} ({d['query_type']})" if d.get("query_type") else q


@register_section(name="activity", order=32, default=True)
async def build(*, case: Case, lang: str, **_kw) -> SectionData:
    rows, unavailable = [], False
    try:
        res = await get_from_agent(case.tenant, f"/api/cases/{case.id}/activity")
        rows = res.get("entries") or []
    except Exception:  # noqa: BLE001 — said in the section, not hidden
        unavailable = True
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/activity.html",
        context={
            "rows": [{
                "when": fmt_dt(e.get("timestamp")),
                "by": e.get("user_name") or "—",
                "action": _S.t(lang, _ACTIONS[e["action"]]) if e.get("action") in _ACTIONS else e.get("action"),
                "what": _subject(e),
                "purpose": (e.get("details") or {}).get("purpose"),
                "has_purpose_col": e.get("action") in ("search.run", "monitoring.create"),
            } for e in rows],
            "none_text": _S.t(lang, "unavailable") if unavailable else (_S.t(lang, "none") if not rows else None),
            "S": {k: _S.t(lang, k) for k in ("col_when", "col_by", "col_action", "col_what",
                                               "col_purpose", "no_purpose")},
        },
    )
