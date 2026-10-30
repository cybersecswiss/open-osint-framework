"""Captured pages — stored here, in the customer's database, never with the
operator. See models.Evidence and capture/main.py for how they are made."""
from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_framework_key
from app.database import get_db
from app.models import Case, Evidence

router = APIRouter(tags=["evidence"])


class EvidenceIn(BaseModel):
    case_id: uuid.UUID
    entity_id: Optional[uuid.UUID] = None
    url: str = Field(max_length=2000)
    final_url: Optional[str] = Field(default=None, max_length=4000)
    http_status: Optional[int] = None
    title: Optional[str] = Field(default=None, max_length=500)
    captured_at: datetime
    captured_by: Optional[str] = Field(default=None, max_length=100)
    via_tor: bool = False
    user_agent: Optional[str] = Field(default=None, max_length=500)
    meta: dict = Field(default_factory=dict)
    screenshot_png_b64: str
    screenshot_sha256: str = Field(min_length=64, max_length=64)
    archive_b64: str
    archive_sha256: str = Field(min_length=64, max_length=64)
    archive_type: str = Field(max_length=40)


def _decode(b64: str, expected: str, what: str) -> bytes:
    raw = base64.b64decode(b64, validate=True)
    # Re-hashed on arrival: the hash is the whole value of this record, so it
    # is checked where the bytes are stored, not trusted from the sender.
    if hashlib.sha256(raw).hexdigest() != expected.lower():
        raise HTTPException(status_code=422, detail=f"{what}: SHA-256 does not match the content")
    return raw


def _meta(e: Evidence) -> dict:
    return {
        "id": str(e.id), "case_id": str(e.case_id),
        "entity_id": str(e.entity_id) if e.entity_id else None,
        "url": e.url, "final_url": e.final_url,
        "http_status": e.http_status,
        "title": e.title, "captured_at": e.captured_at.isoformat(),
        "captured_by": e.captured_by, "via_tor": e.via_tor, "user_agent": e.user_agent,
        "screenshot_sha256": e.screenshot_sha256, "archive_sha256": e.archive_sha256,
        "archive_type": e.archive_type, "meta": e.meta or {},
    }


@router.post("/evidence", status_code=201)
async def store(payload: EvidenceIn, db: AsyncSession = Depends(get_db),
                _: bool = Depends(verify_framework_key)):
    if await db.scalar(select(Case.id).where(Case.id == payload.case_id)) is None:
        raise HTTPException(status_code=404, detail="case not found")
    shot = _decode(payload.screenshot_png_b64, payload.screenshot_sha256, "screenshot")
    archive = _decode(payload.archive_b64, payload.archive_sha256, "archive")
    e = Evidence(
        case_id=payload.case_id, entity_id=payload.entity_id, url=payload.url,
        final_url=payload.final_url, http_status=payload.http_status, title=payload.title,
        captured_at=payload.captured_at.replace(tzinfo=None), captured_by=payload.captured_by,
        via_tor=payload.via_tor, user_agent=payload.user_agent,
        meta={**payload.meta, "screenshot_bytes": len(shot), "archive_bytes": len(archive)},
        screenshot=shot, screenshot_sha256=payload.screenshot_sha256.lower(),
        archive=archive, archive_sha256=payload.archive_sha256.lower(),
        archive_type=payload.archive_type)
    db.add(e)
    await db.commit()
    return _meta(e)


@router.get("/cases/{case_id}/evidence")
async def list_for_case(case_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                        _: bool = Depends(verify_framework_key)):
    # Only the metadata columns — the blobs are fetched one at a time.
    cols = [c for c in Evidence.__table__.c if c.name not in ("screenshot", "archive")]
    rows = (await db.execute(
        select(*cols).where(Evidence.case_id == case_id).order_by(Evidence.captured_at.desc())
    )).all()
    return {"evidence": [_meta(Evidence(**dict(r._mapping))) for r in rows]}


@router.get("/evidence/{evidence_id}/{kind}")
async def download(evidence_id: uuid.UUID, kind: str, case_id: uuid.UUID,
                   db: AsyncSession = Depends(get_db),
                   _: bool = Depends(verify_framework_key)):
    if kind not in ("screenshot", "archive"):
        raise HTTPException(status_code=404, detail="unknown kind")
    e = await db.scalar(select(Evidence).where(Evidence.id == evidence_id, Evidence.case_id == case_id))
    if e is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    if kind == "screenshot":
        body, ctype, sha, ext = e.screenshot, "image/png", e.screenshot_sha256, "png"
    else:
        mhtml = e.archive_type == "multipart/related"
        body, sha = e.archive, e.archive_sha256
        ctype, ext = ("multipart/related", "mhtml") if mhtml else ("text/html", "html")
    return Response(content=body, media_type=ctype, headers={
        "X-Content-SHA256": sha,
        "Content-Disposition": f'attachment; filename="evidence-{e.id}.{ext}"'})
