"""
Support ticket/thread store. Internal-key only — the framework
backend proxies both the tenant side (tenant opens/answers their own
tickets) and the operator side (product owners see/answer all tickets)
here, injecting the correct tenant + author. This store does no auth
scoping itself beyond the internal key; the framework backend enforces
who may see which tenant's tickets.
"""
import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SupportMessage, SupportTicket, get_db, settings

router = APIRouter(prefix="/api/v1/support", tags=["support"])


def verify_internal(x_internal_key: str = Header(..., alias="X-Internal-Key")):
    if not hmac.compare_digest(x_internal_key, settings.internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


class TicketCreate(BaseModel):
    tenant: str
    subject: str
    body: str
    created_by: str
    priority: str = "normal"


class MessageCreate(BaseModel):
    author_role: str  # tenant | operator
    author_name: str
    body: str


class StatusUpdate(BaseModel):
    status: str  # open | closed


def _ticket_dict(t: SupportTicket, message_count: int = 0) -> dict:
    return {
        "id": str(t.id), "tenant": t.tenant, "subject": t.subject,
        "status": t.status, "priority": t.priority, "created_by": t.created_by,
        "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
        "last_message_at": t.last_message_at.isoformat(), "message_count": message_count,
    }


@router.post("/tickets")
async def create_ticket(
    payload: TicketCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    now = datetime.utcnow()
    t = SupportTicket(
        tenant=payload.tenant, subject=payload.subject[:300],
        created_by=payload.created_by, priority=payload.priority,
        status="open", created_at=now, updated_at=now, last_message_at=now,
    )
    db.add(t)
    await db.flush()
    db.add(SupportMessage(
        ticket_id=t.id, author_role="tenant", author_name=payload.created_by,
        body=payload.body, created_at=now,
    ))
    await db.commit()
    return _ticket_dict(t, 1)


@router.get("/tickets")
async def list_tickets(
    tenant: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    q = select(SupportTicket)
    if tenant:
        q = q.where(SupportTicket.tenant == tenant)
    if status:
        q = q.where(SupportTicket.status == status)
    q = q.order_by(SupportTicket.last_message_at.desc())
    rows = (await db.execute(q)).scalars().all()
    counts = dict(
        (await db.execute(
            select(SupportMessage.ticket_id, func.count()).group_by(SupportMessage.ticket_id)
        )).all()
    )
    return [_ticket_dict(t, counts.get(t.id, 0)) for t in rows]


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    msgs = (await db.execute(
        select(SupportMessage).where(SupportMessage.ticket_id == t.id)
        .order_by(SupportMessage.created_at.asc())
    )).scalars().all()
    d = _ticket_dict(t, len(msgs))
    d["messages"] = [
        {"id": str(m.id), "author_role": m.author_role, "author_name": m.author_name,
         "body": m.body, "created_at": m.created_at.isoformat()}
        for m in msgs
    ]
    return d


@router.post("/tickets/{ticket_id}/messages")
async def add_message(
    ticket_id: str,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    now = datetime.utcnow()
    db.add(SupportMessage(
        ticket_id=t.id, author_role=payload.author_role,
        author_name=payload.author_name, body=payload.body, created_at=now,
    ))
    t.updated_at = now
    t.last_message_at = now
    # A new message on a closed ticket reopens it.
    if t.status == "closed":
        t.status = "open"
    await db.commit()
    return {"ok": True}


@router.delete("/tickets/{ticket_id}")
async def delete_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    await db.execute(delete(SupportMessage).where(SupportMessage.ticket_id == t.id))
    await db.delete(t)
    await db.commit()
    return {"ok": True, "deleted": ticket_id}


@router.put("/tickets/{ticket_id}/status")
async def set_status(
    ticket_id: str,
    payload: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    t = await db.get(SupportTicket, ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if payload.status not in ("open", "closed"):
        raise HTTPException(status_code=400, detail="Invalid status")
    t.status = payload.status
    t.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "status": t.status}
