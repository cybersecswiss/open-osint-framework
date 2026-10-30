"""Section 3 — All search jobs ever run on this case."""
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
        "title": "Searches performed",
        "none": "No searches have been run on this case.",
        "col_when": "When", "col_query": "Query", "col_type": "Type",
        "col_modules": "Modules", "col_status": "Status", "col_by": "By",
    },
    "de": {
        "title": "Durchgeführte Suchen",
        "none": "Es wurden noch keine Suchen für diesen Fall ausgeführt.",
        "col_when": "Wann", "col_query": "Anfrage", "col_type": "Typ",
        "col_modules": "Module", "col_status": "Status", "col_by": "Durch",
    },
    "fr": {
        "title": "Recherches effectuées",
        "none": "Aucune recherche n'a encore été effectuée sur ce dossier.",
        "col_when": "Quand", "col_query": "Requête", "col_type": "Type",
        "col_modules": "Modules", "col_status": "Statut", "col_by": "Par",
    },
    "it": {
        "title": "Ricerche eseguite",
        "none": "Nessuna ricerca è stata ancora eseguita su questo caso.",
        "col_when": "Quando", "col_query": "Query", "col_type": "Tipo",
        "col_modules": "Moduli", "col_status": "Stato", "col_by": "Da",
    },
})


@register_section(name="searches", order=30, default=True)
async def build(*, case: Case, db: AsyncSession, lang: str, **_kw) -> SectionData:
    rows = (await db.execute(
        select(SearchJob).where(SearchJob.case_id == case.id, SearchJob.tenant == case.tenant)
        .order_by(SearchJob.started_at.desc())
    )).scalars().all()
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/searches.html",
        context={
            "rows": [
                {
                    "when": fmt_dt(j.started_at),
                    "query": j.query,
                    "query_type": j.query_type,
                    "modules": ", ".join(j.modules_used or []) or "—",
                    "status": j.status,
                    "by": j.created_by,
                }
                for j in rows
            ],
            "none_text": _S.t(lang, "none") if not rows else None,
            "S": {k: _S.t(lang, k) for k in (
                "col_when", "col_query", "col_type",
                "col_modules", "col_status", "col_by",
            )},
        },
    )
