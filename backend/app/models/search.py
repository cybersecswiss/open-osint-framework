import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SearchJob(Base):
    __tablename__ = "search_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id")
    )
    created_by: Mapped[str] = mapped_column(String(100))
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    query_type: Mapped[str] = mapped_column(String(30), nullable=False)
    modules_used: Mapped[list | None] = mapped_column(ARRAY(String))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Per-tool progress: list of {tool, module, status, findings, edges,
    # errors, duration_seconds}. Filled incrementally by the orchestrator
    # so the frontend's polling loop can render a live tool-by-tool
    # status table instead of a blank progress bar.
    tool_progress: Mapped[list | None] = mapped_column(JSONB, default=list)
    # Snapshot of how many graph elements this single job actually
    # produced. Persisted at job completion because the canonical
    # entities/edges live on the customer agent, so we can't reliably
    # count from the framework's local DB after a successful push.
    entities_count: Mapped[int | None] = mapped_column(default=0)
    edges_count: Mapped[int | None] = mapped_column(default=0)
    # Heartbeat, stamped on every tool-progress update. A search runs as an
    # in-process background task, so nothing survives an api restart — this
    # is how the reaper (services/scheduler.reap_stale_jobs) tells "still
    # working" apart from "the process that owned this job is gone".
    # NULL on rows written before this column existed; the reaper falls back to
    # started_at for those.
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime)
