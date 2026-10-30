"""Merge entities: "these are the same person / the same thing".

The graph already lets an investigator draw a `same_person` link. That keeps
two nodes, two degree counts, two places to take notes and two rankings for
one real-world thing. A merge makes it one node: every edge is re-pointed,
corroboration is combined, notes and the source URL carry over, and the
merged node's name is kept on the survivor (`data.aliases`) and in
`entity_aliases` — which is also what stops the next search from creating the
merged node again (see `apply_aliases` and routers/ingest.py).

One transaction: a merge that stopped half way would leave edges pointing at
a node that no longer exists.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_framework_key
from app.database import get_db
from app.models import Edge, Entity, EntityAlias, Evidence

router = APIRouter(tags=["merge"])


class MergeIn(BaseModel):
    target_id: uuid.UUID
    source_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    merged_by: Optional[str] = Field(default=None, max_length=100)


def _union(a, b) -> list[str] | None:
    out = sorted(set(a or []) | set(b or []))
    return out or None


async def alias_map(db: AsyncSession, case_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    rows = (await db.execute(
        select(EntityAlias.alias_id, EntityAlias.target_id).where(EntityAlias.case_id == case_id)
    )).all()
    return {a: t for a, t in rows}


@router.post("/cases/{case_id}/entities/merge")
async def merge(case_id: uuid.UUID, payload: MergeIn, db: AsyncSession = Depends(get_db),
                _: bool = Depends(verify_framework_key)):
    sources = [s for s in dict.fromkeys(payload.source_ids) if s != payload.target_id]
    if not sources:
        raise HTTPException(status_code=422, detail="nothing to merge")
    ids = [payload.target_id, *sources]
    rows = {e.id: e for e in (await db.execute(
        select(Entity).where(Entity.id.in_(ids), Entity.case_id == case_id)
        .with_for_update())).scalars().all()}
    if payload.target_id not in rows or any(s not in rows for s in sources):
        raise HTTPException(status_code=404, detail="entity not found in this case")
    target = rows[payload.target_id]

    rewired = dropped = 0
    aliases = list((target.data or {}).get("aliases") or [])
    for sid in sources:
        src = rows[sid]
        target.corroborated_by = _union(target.corroborated_by, src.corroborated_by)
        target.url = target.url or src.url
        target.observed_at = target.observed_at or src.observed_at
        if target.is_relevant is None:
            target.is_relevant = src.is_relevant
        if src.notes:
            target.notes = f"{target.notes}\n\n[{src.label}] {src.notes}" if target.notes else f"[{src.label}] {src.notes}"
        aliases.append({"entity_type": src.entity_type, "label": src.label})

        for edge in (await db.execute(select(Edge).where(
                Edge.case_id == case_id, or_(Edge.from_entity == sid, Edge.to_entity == sid)))).scalars().all():
            frm = payload.target_id if edge.from_entity == sid else edge.from_entity
            to = payload.target_id if edge.to_entity == sid else edge.to_entity
            if frm == to:
                await db.delete(edge)            # would be a self-loop
                dropped += 1
                continue
            twin = await db.scalar(select(Edge).where(
                Edge.case_id == case_id, Edge.id != edge.id, Edge.from_entity == frm,
                Edge.to_entity == to, Edge.relation_type == edge.relation_type))
            if twin is not None:
                # The same statement already exists on the survivor: one edge,
                # with both sources behind it.
                twin.corroborated_by = _union(twin.corroborated_by, edge.corroborated_by)
                twin.source = twin.source or edge.source
                await db.delete(edge)
                dropped += 1
                continue
            edge.from_entity, edge.to_entity = frm, to
            rewired += 1

        await db.execute(update(Evidence).where(Evidence.entity_id == sid).values(entity_id=payload.target_id))
        # Chains: whatever had been merged into the source now points at the target.
        await db.execute(update(EntityAlias).where(EntityAlias.target_id == sid)
                         .values(target_id=payload.target_id))
        db.add(EntityAlias(alias_id=sid, case_id=case_id, target_id=payload.target_id,
                           alias_type=src.entity_type, alias_label=src.label,
                           merged_by=payload.merged_by))
        await db.flush()
        await db.execute(delete(Entity).where(Entity.id == sid))

    target.data = {**(target.data or {}), "aliases": aliases}
    await db.commit()
    return {"target_id": str(payload.target_id), "target_label": target.label,
            "merged": [{"id": str(s), "entity_type": rows[s].entity_type, "label": rows[s].label}
                       for s in sources],
            "edges_rewired": rewired, "edges_dropped": dropped}
