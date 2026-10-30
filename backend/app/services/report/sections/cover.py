"""Section 0 — Cover page. Branding + case identity + who-when."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.case import Case
from app.services.report.base import (
    SectionData, SectionStrings, fmt_dt, fmt_dt_zoned, register_section,
    tz_label)

_S = SectionStrings({
    "en": {
        "title": "Cover",
        "case_number": "Case Number",
        "title_label": "Title",
        "status": "Status",
        "priority": "Priority",
        "assigned": "Assigned to",
        "created": "Created",
        "generated": "Report generated",
        "by": "by",
        "for": "for",
        "tz_note": "All times in local time {tz}.",
    },
    "de": {
        "title": "Titelseite",
        "case_number": "Fallnummer",
        "title_label": "Titel",
        "status": "Status",
        "priority": "Priorität",
        "assigned": "Zugewiesen an",
        "created": "Erstellt",
        "generated": "Report erstellt",
        "by": "von",
        "for": "für",
        "tz_note": "Alle Zeitangaben in Ortszeit {tz}.",
    },
    "fr": {
        "title": "Couverture",
        "case_number": "Numéro de dossier",
        "title_label": "Titre",
        "status": "Statut",
        "priority": "Priorité",
        "assigned": "Attribué à",
        "created": "Créé",
        "generated": "Rapport généré",
        "by": "par",
        "for": "pour",
        "tz_note": "Toutes les heures en heure locale {tz}.",
    },
    "it": {
        "title": "Copertina",
        "case_number": "Numero del caso",
        "title_label": "Titolo",
        "status": "Stato",
        "priority": "Priorità",
        "assigned": "Assegnato a",
        "created": "Creato",
        "generated": "Report generato",
        "by": "da",
        "for": "per",
        "tz_note": "Tutti gli orari in ora locale {tz}.",
    },
})


@register_section(name="cover", order=0, default=True)
async def build(*, case: Case, lang: str, tenant_settings: dict[str, Any],
                user: dict[str, Any], **_kw) -> SectionData:
    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/cover.html",
        context={
            "logo_b64": tenant_settings.get("logo_b64"),
            "org_name": tenant_settings.get("display_name") or "",
            "classification": tenant_settings.get("report_classification") or "",
            "case_number": case.case_number,
            "case_title": case.title,
            "status": case.status,
            "priority": case.priority,
            "assigned_to": case.assigned_to,
            "created_at": fmt_dt(case.created_at, dash=""),
            "created_by": case.created_by,
            "generated_at": fmt_dt_zoned(datetime.now(timezone.utc)),
            "generated_by": user.get("username") or user.get("email") or "—",
            # Said once here so no table below has to repeat it on every row.
            "tz_note": _S.t(lang, "tz_note", tz=tz_label()),
            "S": {k: _S.t(lang, k) for k in (
                "case_number", "title_label", "status", "priority",
                "assigned", "created", "generated", "by", "for",
            )},
        },
    )
