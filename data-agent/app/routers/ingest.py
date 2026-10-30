"""
Ingest endpoint. Idempotent — uses ON CONFLICT DO NOTHING on the
primary key so a retry from the framework doesn't duplicate rows.

The framework also pre-creates a `cases` row (with the same id it sent
in the entity payloads) so foreign keys hold; if the case row is
missing we create a stub on the fly so first-time pushes don't fail.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, distinct, func, literal_column, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import verify_framework_key
from app.database import get_db
from app.models import Case, Edge, Entity
from app.routers.merge import alias_map

log = logging.getLogger("data-agent.ingest")


def _merge_arrays(stored, incoming):
    """SQL expression: union of two text[] columns, deduped and sorted.

    Corroboration — which tools independently reported the same thing — is the
    one field that must ACCUMULATE rather than gap-fill. A tool confirming an
    existing node months later is exactly the signal worth keeping, and
    neither DO NOTHING (loses the newcomer) nor overwrite (loses the history)
    preserves it. Sorted, so re-pushing unchanged data yields an identical row.

    Mirrors `_merge_arrays` in backend/app/routers/search.py — the local
    fallback and the sovereign store must not diverge on this.
    """
    empty = literal_column("'{}'::text[]")
    combined = func.coalesce(stored, empty).op("||")(func.coalesce(incoming, empty))
    element = func.unnest(combined).column_valued("tool")
    return select(
        func.array_agg(aggregate_order_by(distinct(element), element))
    ).scalar_subquery()

router = APIRouter(tags=["ingest"])


class EntityIn(BaseModel):
    id: str
    case_id: str
    entity_type: str
    label: str
    data: dict = {}
    source: Optional[str] = None
    confidence: Optional[float] = None
    # Optional so an older framework build still ingests
    # against a newer agent — the customer's agent may well be updated
    # before (or after) the operator's framework.
    url: Optional[str] = None
    observed_at: Optional[datetime] = None
    notes: Optional[str] = None
    last_verified: Optional[datetime] = None
    corroborated_by: list[str] = []
    admiralty: Optional[str] = None


class EdgeIn(BaseModel):
    id: str
    case_id: str
    from_entity: str
    to_entity: str
    relation_type: str
    confidence: Optional[float] = None
    source: Optional[str] = None
    data: dict = {}
    corroborated_by: list[str] = []


class CaseIn(BaseModel):
    """Case metadata the framework owns and the agent mirrors.

    With only a case *id* the agent would have to invent a `job <uuid>`
    stub title. If the operator disappeared, the customer would be left
    holding thousands of entities in nameless buckets — which defeats the
    point of them holding the data at all.
    """
    case_number: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    # Which stage of the investigation this case is in. Mirrored so a
    # customer holding these cases without the operator can see which were
    # mid-collection and which were being written up.
    phase: Optional[str] = None


class IngestPayload(BaseModel):
    case_id: str
    job_id: str
    entities: list[EntityIn] = []
    edges: list[EdgeIn] = []
    case: Optional[CaseIn] = None


async def _upsert_case(
    db: AsyncSession, case_uuid: uuid.UUID, case: "CaseIn | None", job_id: str,
) -> None:
    """Make sure the parent case row exists (FK target) and carries the
    framework's metadata.

    Without metadata we still create a stub so the foreign keys hold — but
    the stub title now names the case id rather than the job id, because a
    job id tells the customer nothing at all.

    With metadata we DO UPDATE: the case number and title are owned by the
    framework, so a later push (or a rename) must win over whatever is
    stored here. `status` and `phase` only overwrite when actually supplied,
    so a partial payload can't silently reopen a closed case or reset where
    the investigator was.

    That last rule was stated here but not implemented: the code read
    `case.status or "open"`, which turns an absent status into an explicit
    "open" — exactly the silent reopen the sentence promised was impossible.
    In practice the framework always sends one, so it never fired; a
    guarantee that only holds because no caller exercises it is not a
    guarantee.
    """
    if case is None:
        await db.execute(
            pg_insert(Case)
            .values(id=case_uuid, title=f"case {case_uuid}", status="open")
            .on_conflict_do_nothing(index_elements=["id"])
        )
        return

    values: dict = {"id": case_uuid}
    if case.case_number is not None:
        values["case_number"] = case.case_number
    if case.title is not None:
        values["title"] = case.title
    if case.status is not None:
        values["status"] = case.status
    if case.phase is not None:
        values["phase"] = case.phase

    # A brand-new row still needs the NOT NULL columns filled; an UPDATE
    # must not touch what this payload did not carry, hence the split.
    insert_values = {"status": "open", "phase": "new", **values}
    stmt = pg_insert(Case).values(**insert_values)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={k: v for k, v in values.items() if k != "id"},
        )
    )
    log.info("case %s metadata synced (job=%s): %s / %s",
             case_uuid, job_id, case.case_number, case.title)


@router.put("/cases/{case_id}")
async def sync_case(
    case_id: str,
    payload: CaseIn,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    """Push case metadata without ingesting findings.

    The ingest path carries metadata too, but a case that is renamed,
    closed or reassigned between searches would otherwise never reach the
    customer's store. The framework calls this on every case update.
    """
    case_uuid = uuid.UUID(case_id)
    await _upsert_case(db, case_uuid, payload, job_id="case-sync")
    await db.commit()
    return {"case_id": case_id, "synced": True}


@router.post("/ingest")
async def ingest(
    payload: IngestPayload,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_framework_key),
):
    case_uuid = uuid.UUID(payload.case_id)
    await _upsert_case(db, case_uuid, payload.case, payload.job_id)

    # Merged-away nodes (routers/merge.py): a finding for one of them is a
    # finding for the node it was merged into. Without this the next search
    # would recreate the merged node under its deterministic id.
    aliases = await alias_map(db, case_uuid)
    folded = 0

    for e in payload.entities:
        target = aliases.get(uuid.UUID(e.id))
        if target is not None:
            row = await db.get(Entity, target)
            if row is not None:
                row.corroborated_by = sorted(set(row.corroborated_by or []) | set(e.corroborated_by or [])) or None
                row.url = row.url or e.url
            folded += 1
            continue
        stmt = pg_insert(Entity).values(
            id=uuid.UUID(e.id),
            case_id=uuid.UUID(e.case_id),
            entity_type=e.entity_type,
            label=e.label,
            data=e.data,
            source=e.source,
            confidence=e.confidence,
            url=e.url,
            observed_at=e.observed_at,
            notes=e.notes,
            last_verified=e.last_verified,
            corroborated_by=e.corroborated_by or None,
            admiralty=e.admiralty,
        )
        # Gap-fill, not overwrite.
        #
        # Plain DO NOTHING would mean provenance columns added in a later
        # schema version stay NULL forever on every row that already exists — a
        # re-scan of an existing case could never make it citable. COALESCE
        # in this direction fills a NULL and leaves a stored value alone, so:
        #
        #   * identity fields (label, data, confidence) are untouched — the
        #     placeholder-freeze logic in the search flush depends on a
        #     re-push NOT rewriting a node,
        #   * investigator state (is_relevant, notes) is untouched,
        #   * a missing citation gets filled the next time a tool returns it.
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "url": func.coalesce(Entity.url, stmt.excluded.url),
                    "observed_at": func.coalesce(Entity.observed_at, stmt.excluded.observed_at),
                    # Corroboration accumulates; the rating is recomputed from
                    # it, so a freshly supplied rating wins over the stored one.
                    "corroborated_by": _merge_arrays(
                        Entity.corroborated_by, stmt.excluded.corroborated_by),
                    "admiralty": func.coalesce(stmt.excluded.admiralty, Entity.admiralty),
                    # `data` is otherwise never touched on conflict — the
                    # placeholder-freeze logic depends on that. The one
                    # exception is the `root` marker: it was introduced after
                    # these rows were written, and without merging it a
                    # re-scan could never repair an existing case, so its
                    # exports would keep losing every edge that starts at the
                    # search term. Only that single key is merged in.
                    "data": case(
                        (stmt.excluded.data.has_key("root"),
                         Entity.data.op("||")(literal_column(
                             '\'{"root": true}\'::jsonb'))),
                        else_=Entity.data,
                    ),
                },
            )
        )
    # Flush so the just-inserted entities are visible to the FK check
    # for edges within this same transaction.
    await db.flush()

    # Edges carry FKs to entities.id. An edge pointing at an entity that
    # is neither in this payload nor already stored would raise an
    # IntegrityError and roll back the WHOLE ingest (losing every entity
    # too). Compute the set of valid endpoints and skip dangling edges.
    valid_ids: set[uuid.UUID] = {uuid.UUID(e.id) for e in payload.entities}
    existing = (await db.execute(
        select(Entity.id).where(Entity.case_id == case_uuid)
    )).scalars().all()
    valid_ids.update(existing)

    inserted_edges = 0
    skipped_edges = 0
    for edge in payload.edges:
        frm = uuid.UUID(edge.from_entity)
        to = uuid.UUID(edge.to_entity)
        remapped = frm in aliases or to in aliases
        frm, to = aliases.get(frm, frm), aliases.get(to, to)
        if frm == to:
            continue                         # both ends merged into one node
        if frm not in valid_ids or to not in valid_ids:
            skipped_edges += 1
            continue
        if remapped:
            # The edge id was derived from the old endpoints; the same
            # statement may already sit on the survivor under another id.
            twin = await db.scalar(select(Edge).where(
                Edge.case_id == case_uuid, Edge.from_entity == frm, Edge.to_entity == to,
                Edge.relation_type == edge.relation_type))
            if twin is not None:
                twin.corroborated_by = sorted(set(twin.corroborated_by or []) | set(edge.corroborated_by or [])) or None
                continue
        estmt = pg_insert(Edge).values(
            id=uuid.UUID(edge.id),
            case_id=uuid.UUID(edge.case_id),
            from_entity=frm,
            to_entity=to,
            relation_type=edge.relation_type,
            confidence=edge.confidence,
            source=edge.source,
            data=edge.data or {},
            corroborated_by=edge.corroborated_by or None,
        )
        # Same gap-fill rule as for entities: an edge stored before the
        # `source` column existed gets its citation on the next re-scan.
        await db.execute(
            estmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "source": func.coalesce(Edge.source, estmt.excluded.source),
                    "corroborated_by": _merge_arrays(
                        Edge.corroborated_by, estmt.excluded.corroborated_by),
                },
            )
        )
        inserted_edges += 1

    if skipped_edges:
        log.warning("ingest job=%s: skipped %d edge(s) with missing endpoints",
                    payload.job_id, skipped_edges)
    if folded:
        log.info("ingest job=%s: %d finding(s) folded into merged nodes", payload.job_id, folded)

    await db.commit()
    return {
        "ingested_entities": len(payload.entities),
        "ingested_edges": inserted_edges,
        "skipped_edges": skipped_edges,
        # Match the keys the framework search router looks for.
        "entities_count": len(payload.entities),
        "edges_count": inserted_edges,
    }
