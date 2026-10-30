import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MonitoringConfig(Base):
    """
    entity_id was originally a FK to the framework's local
    `entities` table. Entity storage now lives in the customer's
    data agent, so the framework no longer holds those rows. We keep
    entity_id and case_id as plain UUID columns — the framework owns
    monitoring metadata, the agent owns the entities themselves.
    """
    __tablename__ = "monitoring_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    # The selector to re-run on each scheduled scan. Persisted at create
    # time so the rescan reproduces the original search instead of a
    # placeholder query that matches no module manifest. Nullable for
    # rows created before this column existed.
    query: Mapped[str | None] = mapped_column(String(500))
    query_type: Mapped[str | None] = mapped_column(String(50))
    modules: Mapped[list] = mapped_column(ARRAY(String), default=list)
    alert_on: Mapped[list] = mapped_column(ARRAY(String), default=list)
    alert_email: Mapped[str | None] = mapped_column(String(255))
    alert_webhook: Mapped[str | None] = mapped_column(String(500))
    # When this monitor's first run established what was already there.
    # NULL = never run. See alembic 0005: the first run does not alert,
    # because everything a fresh search finds would otherwise arrive as a
    # change (easily a thousand alerts from one run).
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime)
    # How much that baseline covered. Kept so the UI can say "baseline:
    # N findings on <date>" instead of leaving a silent first cycle
    # looking like a broken monitor.
    baseline_suppressed: Mapped[int | None] = mapped_column(Integer)
    last_scan: Mapped[datetime | None] = mapped_column(DateTime)
    next_scan: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Alert(Base):
    """Same architectural rule as MonitoringConfig — entity/case live in the agent."""
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    monitoring_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("monitoring_configs.id")
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
