"""Who may see a case — the one place that decides it.

Originally the rule was "same tenant", written out as
`Case.tenant == tenant` in some thirty places. A restricted case narrows that
to the people working it. Every route that touches a case, directly or
through something that belongs to one (an entity, an edge, a search job, a
watch, an alert), must ask here — a single forgotten route is a leak, and
the leak would look like normal operation.

Rule for a restricted case: its creator, its assignee, its members, and the
tenant's admins. Admins are included on purpose — someone has to be able to
reassign a case whose investigator has left — and that is stated in the
handbook so nobody mistakes "restricted" for "hidden from admins".

A case that is not visible answers **404, not 403**: to someone outside the
circle, the case does not exist. A 403 would confirm that it does.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case


def is_admin(user: dict) -> bool:
    return "admin" in (user.get("roles") or [])


def can_see(case: Case, user: dict) -> bool:
    if case.tenant != user.get("tenant"):
        return False
    if not case.restricted or is_admin(user):
        return True
    name = user.get("username")
    if not name:
        return False
    return name == case.created_by or name == case.assigned_to or name in (case.members or [])


def can_manage_access(case: Case, user: dict) -> bool:
    """Who may restrict a case or change its members: the creator or an admin.
    Not every member — someone already inside could otherwise widen the
    circle, which is exactly what a restricted case is meant to prevent."""
    return is_admin(user) or (bool(user.get("username")) and user.get("username") == case.created_by)


def visible_clause(user: dict) -> ColumnElement[bool]:
    """SQL condition for "cases this user may see" — for list queries."""
    tenant_ok = Case.tenant == user.get("tenant")
    if is_admin(user):
        return tenant_ok
    name = user.get("username")
    if not name:
        return tenant_ok & (Case.restricted == false())
    return tenant_ok & or_(
        Case.restricted == false(),
        Case.created_by == name,
        Case.assigned_to == name,
        Case.members.any(name),
    )


async def get_visible_case(db: AsyncSession, user: dict, case_id: uuid.UUID) -> Case:
    case = await db.scalar(select(Case).where(Case.id == case_id, Case.tenant == user.get("tenant")))
    if case is None or not can_see(case, user):
        raise HTTPException(status_code=404, detail="Case not found")
    return case


async def visible_case_ids(db: AsyncSession, user: dict) -> set[uuid.UUID]:
    return set((await db.execute(select(Case.id).where(visible_clause(user)))).scalars().all())


async def assert_case_visible(db: AsyncSession, user: dict, case_id) -> None:
    try:
        cid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Case not found")
    await get_visible_case(db, user, cid)


