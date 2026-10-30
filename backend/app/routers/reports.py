"""
Report endpoint — POST /cases/{id}/report → application/pdf.

Caller chooses which sections to include via the `sections` array in
the body. Empty / missing → use every section that's registered with
default=True. Unknown sections in the array are silently dropped (so
client-side staleness doesn't fail the request).
"""
from __future__ import annotations

import logging
import uuid

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.services import audit
from app.services.case_access import get_visible_case
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.case import Case
from app.services.export import RENDERERS
from app.services.report import generate_report, list_sections
from app.services.report.generator import fetch_agent_data

log = logging.getLogger("osint.reports")
router = APIRouter(tags=["reports"])


class ReportRequest(BaseModel):
    sections: list[str] | None = None
    lang: str = "en"
    # An extract of the findings marked relevant; Word output.
    only_relevant: bool = False
    format: Literal["pdf", "docx"] = "pdf"


@router.get("/report/sections")
async def available_sections(_: dict = Depends(get_current_user)):
    """List all registered sections so the frontend can render the
    "include in report" checkboxes without hard-coding the list."""
    return [
        {"name": s.name, "order": s.order, "default": s.default}
        for s in list_sections()
    ]


@router.get("/cases/{case_id}/export")
async def export_case(
    case_id: uuid.UUID,
    request: Request,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export a case as CSV, Maltego CSV, a MISP event or a STIX 2.1 bundle.

    Same data source as the PDF (customer agent, local fallback) and the same
    triage rule: graph placeholders never leave the building. Every export is
    audited with a hash of the payload, because handing findings to another
    agency is exactly the kind of act a case file has to be able to prove.
    """
    fmt = (format or "csv").lower()
    if fmt not in RENDERERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{format}'. Supported: {', '.join(sorted(RENDERERS))}",
        )
    case = await get_visible_case(db, user, case_id)

    agent_data = await fetch_agent_data(user["tenant"], str(case_id), db)
    render, media_type, suffix = RENDERERS[fmt]
    try:
        body = render(
            agent_data.get("entities") or [],
            agent_data.get("edges") or [],
            case=case,
            tenant_name=user["tenant"],
        )
    except Exception:
        log.exception("export failed for case %s (format=%s)", case_id, fmt)
        raise HTTPException(status_code=500, detail="Export failed")

    payload = body.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    filename = f"{case.case_number or case.id}.{suffix}".replace("/", "_")
    await audit.log_action(user["tenant"], "case.export", user=user,
                           target_type="case", target_id=case_id,
                           details={"format": fmt, "sha256": digest,
                                    "bytes": len(payload),
                                    "source": agent_data.get("source")},
                           ip=audit.client_ip(request))
    return Response(
        content=payload,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-SHA256": digest},
    )


@router.post("/cases/{case_id}/report")
async def render_report(
    case_id: uuid.UUID,
    request: Request,
    payload: ReportRequest = ReportRequest(),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    case = await get_visible_case(db, user, case_id)

    try:
        pdf_bytes = await generate_report(
            case=case,
            tenant=user["tenant"],
            user=user,
            db=db,
            section_names=payload.sections,
            lang=(payload.lang or "en").lower()[:2],
            only_relevant=payload.only_relevant,
            fmt=payload.format,
        )
    except Exception:
        log.exception("report generation failed for case %s", case_id)
        raise HTTPException(status_code=500, detail="Report generation failed")

    ext = "docx" if payload.format == "docx" else "pdf"
    filename = f"{case.case_number or case.id}{'-auszug' if payload.only_relevant else ''}.{ext}".replace("/", "_")
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    await audit.log_action(user["tenant"], "report.export", user=user,
                           target_type="case", target_id=case_id,
                           details={"case_number": case.case_number,
                                    "sha256": pdf_sha256, "bytes": len(pdf_bytes),
                                    "sections": payload.sections, "lang": payload.lang,
                                    "format": ext, "only_relevant": payload.only_relevant},
                           ip=audit.client_ip(request))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf" if ext == "pdf" else
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-SHA256": pdf_sha256},
    )
