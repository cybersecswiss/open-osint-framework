"""Section 1 — Summary: case description + counts of everything."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case
from app.models.monitoring import Alert, MonitoringConfig
from app.models.search import SearchJob
from app.services.report.base import SectionData, SectionStrings, register_section
from app.services.report.filters import triage

_S = SectionStrings({
    "en": {
        "title": "Summary",
        "description": "Description",
        "no_description": "(no description)",
        "counts_title": "Activity overview",
        "findings": "Findings",
        "relevant": "Marked relevant",
        "placeholders": "Graph placeholders",
        "cited": "With source reference",
        "edges": "Connections",
        "searches": "Searches run",
        "monitorings": "Active monitorings",
        "alerts": "Alerts",
        "data_source": "Data source",
        "agent": "customer agent",
        "local": "local fallback",
    },
    "de": {
        "title": "Zusammenfassung",
        "description": "Beschreibung",
        "no_description": "(keine Beschreibung)",
        "counts_title": "Aktivitätsübersicht",
        "findings": "Funde",
        "relevant": "Als relevant markiert",
        "placeholders": "Graph-Platzhalter",
        "cited": "Mit Quellenangabe",
        "edges": "Verbindungen",
        "searches": "Durchgeführte Suchen",
        "monitorings": "Aktive Monitorings",
        "alerts": "Alerts",
        "data_source": "Datenquelle",
        "agent": "Customer-Agent",
        "local": "Lokaler Fallback",
    },
    "fr": {
        "title": "Résumé",
        "description": "Description",
        "no_description": "(aucune description)",
        "counts_title": "Aperçu de l'activité",
        "findings": "Découvertes",
        "relevant": "Marquées pertinentes",
        "placeholders": "Substituts de graphe",
        "cited": "Avec référence de source",
        "edges": "Connexions",
        "searches": "Recherches effectuées",
        "monitorings": "Surveillances actives",
        "alerts": "Alertes",
        "data_source": "Source des données",
        "agent": "agent client",
        "local": "secours local",
    },
    "it": {
        "title": "Riepilogo",
        "description": "Descrizione",
        "no_description": "(nessuna descrizione)",
        "counts_title": "Panoramica attività",
        "findings": "Risultati",
        "relevant": "Marcati rilevanti",
        "placeholders": "Segnaposto del grafo",
        "cited": "Con riferimento",
        "edges": "Connessioni",
        "searches": "Ricerche eseguite",
        "monitorings": "Monitoraggi attivi",
        "alerts": "Avvisi",
        "data_source": "Origine dati",
        "agent": "agente cliente",
        "local": "fallback locale",
    },
})


@register_section(name="summary", order=10, default=True)
async def build(*, case: Case, db: AsyncSession, lang: str,
                agent_data: dict[str, Any], **_kw) -> SectionData:
    tenant = case.tenant
    n_searches = await db.scalar(
        select(func.count()).select_from(SearchJob).where(SearchJob.case_id == case.id, SearchJob.tenant == tenant)
    ) or 0
    n_monitorings = await db.scalar(
        select(func.count()).select_from(MonitoringConfig).where(
            MonitoringConfig.case_id == case.id,
            MonitoringConfig.tenant == tenant,
            MonitoringConfig.is_active == True,  # noqa: E712
        )
    ) or 0
    n_alerts = await db.scalar(
        select(func.count()).select_from(Alert).where(Alert.case_id == case.id, Alert.tenant == tenant)
    ) or 0
    entities = agent_data.get("entities") or []
    n_edges = len(agent_data.get("edges") or [])

    # A single "entities" number counted graph placeholders as findings and
    # said nothing about how much of the haul was ever assessed. Both are
    # exactly what a reader needs to judge the rest of the report, so the
    # count is broken out instead.
    t = triage(entities)
    n_cited = sum(1 for e in t["shown"] if e.get("url"))

    counts = {
        _S.t(lang, "findings"): t["total_real"],
        _S.t(lang, "relevant"): len(t["relevant"]),
        _S.t(lang, "placeholders"): len(t["placeholders"]),
        _S.t(lang, "cited"): n_cited,
        _S.t(lang, "edges"): n_edges,
        _S.t(lang, "searches"): n_searches,
        _S.t(lang, "monitorings"): n_monitorings,
        _S.t(lang, "alerts"): n_alerts,
    }

    return SectionData(
        title=_S.t(lang, "title"),
        template="sections/summary.html",
        context={
            "description": case.description or _S.t(lang, "no_description"),
            "counts": counts,
            "S": {k: _S.t(lang, k) for k in (
                "description", "counts_title", "data_source", "agent", "local",
            )},
            "data_source": _S.t(lang, "agent" if agent_data.get("source") == "agent" else "local"),
        },
    )
