import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_relevant: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)
    # Source URL of the finding (`Finding.url`). Mirrors the agent column —
    # this table is the local fallback, so both stores must be able to hold
    # the same evidence or a fallback report would be weaker than a real one.
    url: Mapped[str | None] = mapped_column(Text)
    # When the SOURCE said it (runner-set), as opposed to `found_at`, which
    # is when we wrote the row. See data-agent/app/models.py for the full
    # rationale — the two are kept apart on purpose.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Every tool that independently reported this same entity. When three
    # unrelated sources return the same address, that is the strongest
    # statement in the graph — and it used to be invisible, because dedup let
    # the first finding win and silently dropped the rest.
    corroborated_by: Mapped[list | None] = mapped_column(ARRAY(String))
    # Admiralty rating, e.g. "B2": source reliability from the tool's manifest,
    # information credibility derived from corroboration + confidence.
    # See modules/base/schemas.py for the scale.
    admiralty: Mapped[str | None] = mapped_column(String(2))
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime)


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    from_entity: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE")
    )
    to_entity: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str | None] = mapped_column(String(50))
    # Same idea as on Entity: several tools asserting the SAME relation is a
    # much stronger claim than one asserting it.
    corroborated_by: Mapped[list | None] = mapped_column(ARRAY(String))
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
