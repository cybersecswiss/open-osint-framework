"""
Customer-side schema. No tenant column — each customer runs their own
agent with their own DB, so isolation is at the deployment level.
"""
import uuid
from datetime import datetime

from sqlalchemy import (  # noqa: F401
    ARRAY, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="open")
    # Mirrored from the framework — see routers/ingest.py::CaseIn.
    phase: Mapped[str] = mapped_column(String(20), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Node positions and investigator-drawn groups for the case map. Not a
    # finding — the arrangement itself, which is the investigator's work.
    # See routers/query.py::put_layout for the shape and why it is validated.
    layout: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    is_relevant: Mapped[bool | None] = mapped_column(Boolean)
    # The source URL the finding came from — the *Belegstelle*. Runners set
    # `Finding.url`, and the framework passes it through — without it a hit
    # would be an assertion without a citation.
    url: Mapped[str | None] = mapped_column(Text)
    # Investigator's own note on this node. Belongs in the sovereign store,
    # not in the operator's DB — that is why the column lives here.
    notes: Mapped[str | None] = mapped_column(Text)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime)
    # Two distinct timestamps, deliberately:
    #   found_at    — when THIS agent ingested the row (unchanged meaning,
    #                 so older rows keep theirs).
    #   observed_at — when the SOURCE actually said it (`Finding.found_at`,
    #                 set by the runner). For fast-moving sources (leak
    #                 sites, Telegram, pastes) this is the evidentiary one.
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Every tool that independently reported this same entity, and the
    # Admiralty rating derived from that plus the tool's declared source
    # reliability (e.g. "B2"). See modules/base/schemas.py for the scale.
    corroborated_by: Mapped[list | None] = mapped_column(ARRAY(String))
    admiralty: Mapped[str | None] = mapped_column(String(2))
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True
    )
    from_entity: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE")
    )
    to_entity: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    # Which tool asserted this relation. Without it a report can list
    # relationships but cannot cite them, which is the whole point of a
    # relationship section in an investigation file.
    source: Mapped[str | None] = mapped_column(String(50))
    corroborated_by: Mapped[list | None] = mapped_column(ARRAY(String))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str | None] = mapped_column(String(64))
    # The case an entry belongs to, so the case file can show its
    # own activity (who searched what, and why) without scanning JSON.
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)


class Evidence(Base):
    """A captured web page: screenshot + archive + hashes.

    Stored in the database rather than on a volume on purpose: the data
    server's backups are database dumps (backup.sh), so evidence is backed up and
    restored with the case it belongs to, and a case delete removes it in the
    same transaction. `entity_id` carries no foreign key — marking the finding
    a false positive must not destroy the record of what the page showed.
    """
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    captured_by: Mapped[str | None] = mapped_column(String(100))
    via_tor: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    screenshot: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    screenshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    archive: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    archive_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_type: Mapped[str] = mapped_column(String(40), nullable=False)


class EntityAlias(Base):
    """"This node IS that node".

    Entity ids are deterministic — uuid5(case, type, label) — so the next
    search that finds a merged-away node would simply create it again. Every
    ingest therefore consults this table and folds such a finding into the
    node it was merged into. The row also keeps what the merged node was
    called, so the case can show it.
    """
    __tablename__ = "entity_aliases"

    alias_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), index=True, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    alias_type: Mapped[str] = mapped_column(String(30), nullable=False)
    alias_label: Mapped[str] = mapped_column(Text, nullable=False)
    merged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    merged_by: Mapped[str | None] = mapped_column(String(100))
