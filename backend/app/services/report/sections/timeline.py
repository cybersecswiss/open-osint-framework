"""Section 5 — Chronological timeline merging all events on the case."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.search import SearchJob
from app.services.report.base import (
    SectionData, SectionStrings, fmt_dt, register_section)

_S = SectionStrings({
    "en": {
        "title": "Timeline",
        "case_created": "Case created",
        "case_updated": "Case last updated",
        "search_run": "Search run: {q} ({type})",
        "case_closed": "Case closed",
        "none": "No timeline events to show.",
    },
    "de": {
        "title": "Zeitachse",
        "case_created": "Fall erstellt",
        "case_updated": "Fall zuletzt aktualisiert",
        "search_run": "Suche ausgeführt: {q} ({type})",
        "case_closed": "Fall geschlossen",
        "none": "Keine Zeitachsen-Einträge.",
    },
    "fr": {
        "title": "Chronologie",
        "case_created": "Dossier créé",
        "case_updated": "Dossier mis à jour pour la dernière fois",
        "search_run": "Recherche exécutée : {q} ({type})",
        "case_closed": "Dossier clos",
        "none": "Aucun événement à afficher.",
    },
    "it": {
        "title": "Cronologia",
        "case_created": "Caso creato",
        "case_updated": "Caso ultimo aggiornamento",
        "search_run": "Ricerca eseguita: {q} ({type})",
        "case_closed": "Caso chiuso",
        "none": "Nessun evento da mostrare.",
    },
})


@register_section(name="timeline", order=50, default=True)
async def build(*, case: Case, db: AsyncSession, lang: str, **_kw) -> SectionData:
    events: list[tuple[str, str, str]] = []  # (when_iso, label, who)
    if case.created_at:
        events.append((fmt_dt(case.created_at),
                       _S.t(lang, "case_created"), case.created_by or "—"))
    jobs = (await db.execute(
        select(SearchJob).where(SearchJob.case_id == case.id, SearchJob.tenant == case.tenant)
        .order_by(SearchJob.started_at)
    )).scalars().all()
    for j in jobs:
        if j.started_at:
            events.append((
                fmt_dt(j.started_at),
                _S.t(lang, "search_run", q=j.query, type=j.query_type),
                j.created_by or "—",
            ))
    if case.closed_at:
        events.append((fmt_dt(case.closed_at),
                       _S.t(lang, "case_closed"), "—"))
    if case.updated_at and (not case.closed_at or case.updated_at != case.closed_at):
        events.append((fmt_dt(case.updated_at),
                       _S.t(lang, "case_updated"), "—"))

    events.sort(key=lambda e: e[0])
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/timeline.html",
        context={
            "events": events,
            "none_text": _S.t(lang, "none") if not events else None,
        },
    )
