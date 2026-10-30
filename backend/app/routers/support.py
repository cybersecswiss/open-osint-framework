"""
Support tickets — AUTHORITY (tenant) side. An authority user opens and
answers their own support tickets; the thread is the chat. Backed by the
license-server support store (framework-side operational data, NOT
investigation data). The operator side lives in routers/platform.py.

Scoping: a tenant user may only ever see/append to tickets belonging to
their own tenant — enforced here before proxying to the store.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.config import settings

router = APIRouter(prefix="/support", tags=["support"])


async def _lic(method: str, path: str, **kw) -> httpx.Response:
    url = f"{settings.license_server_url}{path}"
    headers = kw.pop("headers", {})
    headers["X-Internal-Key"] = settings.internal_secret
    async with httpx.AsyncClient(timeout=15) as client:
        return await client.request(method, url, headers=headers, **kw)


def _json(r: httpx.Response, ok=(200,)):
    if r.status_code in ok:
        return r.json()
    try:
        detail = r.json().get("detail", r.text)
    except Exception:  # noqa: BLE001
        detail = r.text or "support store error"
    raise HTTPException(status_code=r.status_code, detail=detail)


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    priority: str = "normal"


class MessageCreate(BaseModel):
    body: str = Field(min_length=1)


async def _owned_ticket(ticket_id: str, tenant: str) -> dict:
    """Fetch a ticket and 404 unless it belongs to this tenant."""
    t = _json(await _lic("GET", f"/api/v1/support/tickets/{ticket_id}"))
    if t.get("tenant") != tenant:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t


@router.get("/tickets")
async def list_my_tickets(user: dict = Depends(get_current_user)):
    return _json(await _lic("GET", "/api/v1/support/tickets", params={"tenant": user["tenant"]}))


@router.post("/tickets", status_code=201)
async def create_ticket(payload: TicketCreate, user: dict = Depends(get_current_user)):
    return _json(await _lic("POST", "/api/v1/support/tickets", json={
        "tenant": user["tenant"], "subject": payload.subject, "body": payload.body,
        "created_by": user["username"], "priority": payload.priority,
    }))


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    return await _owned_ticket(ticket_id, user["tenant"])


@router.post("/tickets/{ticket_id}/messages")
async def post_message(ticket_id: str, payload: MessageCreate, user: dict = Depends(get_current_user)):
    await _owned_ticket(ticket_id, user["tenant"])
    return _json(await _lic("POST", f"/api/v1/support/tickets/{ticket_id}/messages", json={
        "author_role": "tenant", "author_name": user["username"], "body": payload.body,
    }))
