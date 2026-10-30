"""Section 4 — Alerts. Skipped if there are none, so empty cases don't
get a useless empty page."""
from __future__ import annotations

from typing import Any

from app.models.case import Case
from app.services.report.base import SectionData, SectionStrings, register_section

_S = SectionStrings({
    "en": {
        "title": "Alerts",
        "col_when": "When", "col_type": "Type", "col_old": "Old", "col_new": "New",
    },
    "de": {
        "title": "Alerts",
        "col_when": "Wann", "col_type": "Typ", "col_old": "Alt", "col_new": "Neu",
    },
    "fr": {
        "title": "Alertes",
        "col_when": "Quand", "col_type": "Type", "col_old": "Ancien", "col_new": "Nouveau",
    },
    "it": {
        "title": "Avvisi",
        "col_when": "Quando", "col_type": "Tipo", "col_old": "Vecchio", "col_new": "Nuovo",
    },
})


@register_section(name="alerts", order=40, default=True)
async def build(*, case: Case, lang: str, agent_data: dict[str, Any], **_kw) -> SectionData | None:
    alerts = agent_data.get("alerts") or []
    if not alerts:
        # Nothing to render — the section opts out so the report
        # doesn't get a blank "Alerts" page on a quiet case.
        return None
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/alerts.html",
        context={
            "rows": alerts,
            "S": {k: _S.t(lang, k) for k in ("col_when", "col_type", "col_old", "col_new")},
        },
    )
