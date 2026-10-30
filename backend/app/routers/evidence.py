"""Evidence capture — save a page as it was, into the customer's store.

`POST /cases/{id}/evidence` asks the capture service (capture/main.py) for a
screenshot and an MHTML archive of one URL, and hands both to the customer's
agent, which re-hashes them on arrival. The operator keeps nothing but the
two SHA-256 values in its audit trail — enough to prove later that a file is
the one that was captured, without holding the file or even its URL.

The customer's own activity log gets the full statement: who captured which
URL, when, with which hashes — hash-chained, so the record of the capture is
as tamper-evident as the capture.
"""
from __future__ import annotations

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.services import audit
from app.services.activity import record_activity
from app.services.agent_client import (
    AgentAuthError, AgentUnavailable, get_bytes_from_agent, get_from_agent,
    post_large_to_agent, push_to_agent,
)
from app.services.case_access import assert_case_visible
from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

log = logging.getLogger("osint.evidence")
router = APIRouter(tags=["evidence"])

# Entity types whose label IS a page address when no source URL is stored.
_LABEL_IS_URL = {"url", "website", "onion_address", "onion"}
_LABEL_IS_HOST = {"domain", "subdomain"}

_STORE_DOWN = (AgentUnavailable, AgentKeyUnavailable, TenantNotConfigured)


class CaptureRequest(BaseModel):
    entity_id: uuid.UUID | None = None
    # A URL typed by hand (a page not yet in the case). One of the two.
    url: str | None = Field(default=None, max_length=2000)


async def _url_for_entity(tenant: str, case_id: uuid.UUID, entity_id: uuid.UUID) -> str:
    res = await push_to_agent(tenant, "/api/entities/lookup", {"ids": [str(entity_id)]})
    for e in res.get("entities") or []:
        if str(e.get("id")) == str(entity_id) and str(e.get("case_id")) == str(case_id):
            if e.get("url"):
                return e["url"]
            label = (e.get("label") or "").strip()
            etype = e.get("entity_type") or ""
            if etype in _LABEL_IS_URL:
                return label if "://" in label else f"http://{label}"
            if etype in _LABEL_IS_HOST:
                return f"https://{label}/"
            raise HTTPException(status_code=422, detail="evidence_no_url")
    raise HTTPException(status_code=404, detail="Entity not found")


async def _call_capture(url: str) -> httpx.Response:
    # Below Cloudflare's 100 s: an onion page may take 70 s to load.
    async with httpx.AsyncClient(timeout=95) as c:
        return await c.post(f"{settings.capture_url}/capture", json={"url": url})


@router.post("/cases/{case_id}/evidence", status_code=201)
async def capture(
    case_id: uuid.UUID,
    payload: CaptureRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, case_id)
    tenant = user["tenant"]
    try:
        if payload.entity_id:
            url = await _url_for_entity(tenant, case_id, payload.entity_id)
        elif payload.url and payload.url.strip():
            url = payload.url.strip()
        else:
            raise HTTPException(status_code=422, detail="evidence_no_url")
    except AgentAuthError:
        raise
    except _STORE_DOWN as e:
        raise HTTPException(status_code=503, detail="evidence_store_unavailable") from e

    try:
        r = await _call_capture(url)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail="capture_unavailable") from e
    if r.status_code == 422:
        raise HTTPException(status_code=422, detail="evidence_blocked")
    if r.status_code != 200:
        detail = ""
        try:
            detail = r.json().get("detail", "")
        except ValueError:
            pass
        raise HTTPException(status_code=502, detail=f"capture_failed: {str(detail)[:200]}")
    cap = r.json()

    record = {
        "case_id": str(case_id),
        "entity_id": str(payload.entity_id) if payload.entity_id else None,
        "url": url, "final_url": cap.get("final_url"), "http_status": cap.get("http_status"),
        "title": cap.get("title"), "captured_at": cap["captured_at"],
        "captured_by": user.get("username"), "via_tor": bool(cap.get("via_tor")),
        "user_agent": cap.get("user_agent"),
        "meta": {k: cap.get(k) for k in (
            "requested_at", "response_headers", "blocked_requests", "redirect_chain",
            "screenshot_truncated", "page_height")},
        "screenshot_png_b64": cap["screenshot_png_b64"],
        "screenshot_sha256": cap["screenshot_sha256"],
        "archive_b64": cap["archive_b64"], "archive_sha256": cap["archive_sha256"],
        "archive_type": cap["archive_type"],
    }
    try:
        stored = await post_large_to_agent(tenant, "/api/evidence", record)
    except AgentAuthError:
        raise
    except _STORE_DOWN as e:
        # Nothing is kept here as a stand-in: evidence is case content.
        raise HTTPException(status_code=503, detail="evidence_store_unavailable") from e

    await record_activity(
        tenant, "evidence.capture", user_name=user.get("username"), case_id=case_id,
        ip=audit.client_ip(request),
        details={"evidence_id": stored["id"], "query": url, "final_url": cap.get("final_url"),
                 "http_status": cap.get("http_status"), "via_tor": bool(cap.get("via_tor")),
                 "screenshot_sha256": cap["screenshot_sha256"],
                 "archive_sha256": cap["archive_sha256"]})
    await audit.log_action(
        tenant, "evidence.capture", user=user, target_type="case", target_id=case_id,
        # Hashes only — enough to verify a file later, nothing about the page.
        details={"evidence_id": stored["id"], "screenshot_sha256": cap["screenshot_sha256"],
                 "archive_sha256": cap["archive_sha256"]},
        ip=audit.client_ip(request))
    return stored


@router.get("/cases/{case_id}/evidence")
async def list_evidence(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await assert_case_visible(db, user, case_id)
    try:
        return await get_from_agent(user["tenant"], f"/api/cases/{case_id}/evidence")
    except AgentAuthError:
        raise
    except _STORE_DOWN as e:
        raise HTTPException(status_code=503, detail="evidence_store_unavailable") from e


@router.get("/cases/{case_id}/evidence/{evidence_id}/{kind}")
async def download_evidence(
    case_id: uuid.UUID,
    evidence_id: uuid.UUID,
    kind: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if kind not in ("screenshot", "archive"):
        raise HTTPException(status_code=404, detail="Not found")
    await assert_case_visible(db, user, case_id)
    try:
        body, headers = await get_bytes_from_agent(
            user["tenant"], f"/api/evidence/{evidence_id}/{kind}?case_id={case_id}")
    except AgentAuthError:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=404 if e.response.status_code == 404 else 502,
                            detail="Evidence not found")
    except _STORE_DOWN as e:
        raise HTTPException(status_code=503, detail="evidence_store_unavailable") from e
    keep = {k: v for k, v in headers.items()
            if k.lower() in ("content-disposition", "x-content-sha256")}
    return Response(content=body, media_type=headers.get("content-type", "application/octet-stream"),
                    headers=keep)
