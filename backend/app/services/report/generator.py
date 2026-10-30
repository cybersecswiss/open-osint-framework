"""
Report generator: orchestrates the section plugins, renders the
combined HTML, hands it to WeasyPrint for PDF.

Why generate the HTML ourselves and not just hand WeasyPrint a single
big template? Because the section plugins each carry their *own*
Jinja2 template — that's what makes "drop a new file in sections/"
work without touching the report shell. We render each section's
template separately and stitch the fragments.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from app.config import settings
from app.models.case import Case
from app.services.report.filters import report_scope
from app.services.report.base import (
    SectionData, SectionMeta, SectionStrings, fmt_dt_zoned, get_section,
    list_sections)

log = logging.getLogger("osint.report")

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ── Tenant settings (logo + display_name) used by the cover ──────

async def _fetch_tenant_settings(tenant: str) -> dict[str, Any]:
    url = f"{settings.license_server_url}/api/v1/tenants/{tenant}/settings"
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url, headers={"X-Internal-Key": settings.internal_secret})
        if r.status_code == 200:
            return r.json()
    except httpx.HTTPError:
        log.exception("tenant settings fetch failed (report)")
    return {}


# ── Agent data (entities + edges + alerts) used by several sections ─

async def fetch_agent_data(tenant: str, case_id: str, db: AsyncSession) -> dict[str, Any]:
    """Try the customer agent first, fall back to the framework-local DB.

    Public because the export endpoint needs exactly the same data with
    exactly the same fallback and auth semantics — two ways of reading a case
    would eventually become two different cases.
    Single shot for all three payloads so we don't hit the agent three
    times per report.

    When the agent is unreachable we now read entities/edges/alerts from
    the local tables here — previously the fallback left them empty and
    every report rendered 0 entities even when the data was sitting in
    the local DB."""
    from app.services.agent_client import AgentAuthError, AgentUnavailable, get_from_agent
    from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured
    from app.routers.agent_proxy import _local_alerts, _local_graph

    out: dict[str, Any] = {"entities": [], "edges": [], "alerts": []}
    import uuid as _uuid
    case_uuid = _uuid.UUID(case_id)
    try:
        graph = await get_from_agent(tenant, f"/api/cases/{case_id}/graph")
        out["entities"] = graph.get("entities") or []
        out["edges"] = graph.get("edges") or []
        out["source"] = graph.get("source", "agent")
    except (AgentAuthError, AgentKeyUnavailable):
        # Do not paper over a rejected key with the local copy — a report
        # is evidentiary output; it must not quietly change its source.
        raise
    except (AgentUnavailable, TenantNotConfigured) as e:
        log.info("report: agent unavailable for tenant=%s case=%s (%s) — local fallback",
                 tenant, case_id, e)
        local = await _local_graph(db, tenant, case_uuid)
        out["entities"] = local.get("entities") or []
        out["edges"] = local.get("edges") or []
        out["source"] = "local-fallback"
    # Alerts are read from the framework DB, not the agent.
    #
    # Monitoring is operator-side: `monitoring_configs` and `alerts` both
    # live here, and the agent's /alerts endpoint is a placeholder that has
    # always returned an empty array. Asking the agent first therefore made
    # the alerts section silently empty on every deployment that HAS an
    # agent — i.e. every real one — while looking like it worked.
    #
    # Reading them from where they actually are is the honest fix. Whether
    # alerts should move into the sovereign store at all is a separate,
    # deliberate decision (they carry entity ids and old/new values, which
    # is case content), not to be settled by a silent change here.
    local_alerts = await _local_alerts(db, tenant, case_uuid)
    out["alerts"] = local_alerts.get("alerts") or []
    return out


# ── Public entry point ──────────────────────────────────────────

# Strings the shell itself needs. Sections carry their own bundles; these
# four keys belong to no section, which is exactly why the colophon stayed
# English for as long as it did — it had no owner.
_SHELL = SectionStrings({
    "en": {"only_relevant": "Extract: relevant findings only", "generated": "Generated", "by": "by", "case": "Case",
           "failed_title": "Section unavailable",
           "failed_body": "The “{name}” section could not be generated and is "
                          "missing from this report. This is a technical "
                          "failure, not a statement that there was nothing to "
                          "show. Please regenerate the report or contact "
                          "support."},
    "de": {"only_relevant": "Auszug: nur relevante Funde", "generated": "Erstellt", "by": "von", "case": "Fall",
           "failed_title": "Abschnitt nicht verfügbar",
           "failed_body": "Der Abschnitt „{name}“ konnte nicht erzeugt werden "
                          "und fehlt in diesem Bericht. Das ist ein technischer "
                          "Fehler und bedeutet nicht, dass es nichts zu zeigen "
                          "gab. Bitte den Bericht neu erzeugen oder den Support "
                          "kontaktieren."},
    "fr": {"only_relevant": "Extrait : résultats pertinents uniquement", "generated": "Généré le", "by": "par", "case": "Dossier",
           "failed_title": "Section indisponible",
           "failed_body": "La section « {name} » n’a pas pu être générée et "
                          "manque dans ce rapport. Il s’agit d’une erreur "
                          "technique, et non d’une indication qu’il n’y avait "
                          "rien à afficher. Veuillez régénérer le rapport ou "
                          "contacter le support."},
    "it": {"only_relevant": "Estratto: solo risultati rilevanti", "generated": "Generato il", "by": "da", "case": "Caso",
           "failed_title": "Sezione non disponibile",
           "failed_body": "La sezione «{name}» non ha potuto essere generata e "
                          "manca in questo report. Si tratta di un errore "
                          "tecnico e non significa che non ci fosse nulla da "
                          "mostrare. Rigenerare il report o contattare il "
                          "supporto."},
})


def _failed_section(name: str, lang: str, title: str | None = None) -> dict[str, Any]:
    """A visible gap where a section should have been."""
    body = _SHELL.t(lang, "failed_body", name=title or name)
    return {
        "name": name,
        "title": f"{title or name} — {_SHELL.t(lang, 'failed_title')}",
        "html": f'<p class="tag red">{escape(body)}</p>',
    }


async def generate_report(
    *,
    case: Case,
    tenant: str,
    user: dict[str, Any],
    db: AsyncSession,
    section_names: list[str] | None = None,
    lang: str = "en",
    only_relevant: bool = False,
    fmt: str = "pdf",
) -> bytes:
    """Build the report. `section_names` controls which sections render;
    None = use every section that's registered with `default=True`.

    `only_relevant`: an extract of the findings the investigator
    marked relevant, and the links between them. Said on every page header,
    so an extract is never read as the whole case.

    `fmt`: "pdf" (WeasyPrint) or "docx" (the same HTML, converted — editable
    in Word, without the page furniture CSS cannot express there)."""
    metas: Iterable[SectionMeta]
    if section_names:
        metas = []
        for name in section_names:
            m = get_section(name)
            if m is None:
                log.warning("report: ignoring unknown section %r", name)
                continue
            metas.append(m)
        # Re-sort by registered order so caller's input order doesn't
        # break section flow. The user picks which, the framework
        # picks where.
        metas = sorted(metas, key=lambda m: (m.order, m.name))
    else:
        metas = [m for m in list_sections() if m.default]

    tenant_settings = await _fetch_tenant_settings(tenant)
    agent_data = await fetch_agent_data(tenant, str(case.id), db)
    if only_relevant:
        agent_data = relevant_only(agent_data)
    # Every section's triage follows the explicit choice (filters.report_scope).
    report_scope.set("relevant" if only_relevant else "all")

    rendered_sections: list[dict[str, Any]] = []
    for meta in metas:
        # A section that cannot be built is REPORTED, not dropped.
        #
        # Both failure paths below used to `continue`, which produced a PDF
        # that simply lacked the section — no gap, no note, nothing in the
        # document to distinguish "the alerts section broke" from "this case
        # has no alerts". That is the same defect that keeps turning up in
        # the UI, except here it is in the artefact that gets filed as an
        # annex and read by someone who cannot check the server log.
        #
        # The report still renders — a broken evidence section must not cost
        # the investigator the other nine — but it says so where the section
        # would have been.
        try:
            data: SectionData | None = await meta.builder(
                case=case, db=db, lang=lang,
                agent_data=agent_data,
                tenant_settings=tenant_settings,
                user=user,
                only_relevant=only_relevant,
            )
        except Exception:
            log.exception("report: section %s build failed", meta.name)
            rendered_sections.append(_failed_section(meta.name, lang))
            continue
        if data is None or data.skip:
            continue
        try:
            html_fragment = _env.get_template(data.template).render(**data.context)
        except Exception:
            log.exception("report: section %s template render failed", meta.name)
            rendered_sections.append(_failed_section(meta.name, lang, data.title))
            continue
        rendered_sections.append({
            "name": meta.name,
            "title": data.title,
            "html": html_fragment,
        })

    # Shell: wraps the section fragments with global header/footer +
    # page-break CSS. This is the only top-level template the
    # generator owns — sections can't override it.
    shell_html = _env.get_template("base.html").render(
        sections=rendered_sections,
        tenant_settings=tenant_settings,
        case=case,
        generated_at=fmt_dt_zoned(datetime.now(timezone.utc)),
        generated_by=user.get("username") or user.get("email") or "—",
        lang=lang,
        only_relevant=only_relevant,
        S={k: _SHELL.t(lang, k) for k in ("generated", "by", "case", "only_relevant")},
    )

    if fmt == "docx":
        from app.services.report.docx_export import html_to_docx
        header = " · ".join(x for x in (
            tenant_settings.get("report_classification"),
            tenant_settings.get("display_name"),
            case.case_number,
            _SHELL.t(lang, "only_relevant") if only_relevant else None) if x)
        return await asyncio.to_thread(
            html_to_docx, rendered_sections, header, tenant_settings.get("report_classification") or "")

    # WeasyPrint is synchronous and CPU/IO-heavy. Run it off the event
    # loop so a report render doesn't block other requests on this worker.
    return await asyncio.to_thread(lambda: HTML(string=shell_html).write_pdf())


def relevant_only(agent_data: dict[str, Any]) -> dict[str, Any]:
    """The findings marked relevant, and only the links between them."""
    ents = [e for e in agent_data.get("entities") or [] if e.get("is_relevant") is True]
    ids = {str(e.get("id")) for e in ents}
    edges = [e for e in agent_data.get("edges") or []
             if str(e.get("from_entity")) in ids and str(e.get("to_entity")) in ids]
    return {**agent_data, "entities": ents, "edges": edges}
