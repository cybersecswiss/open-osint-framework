"""Tamper-evident, per-tenant audit log (framework-side).

Every mutating investigative action (search, commit, AI run/apply, entity
edit/delete, case create/update/delete, report export, monitoring changes)
appends one row here via ``services.audit.log_action``. Rows form a per-tenant
sha256 hash chain (``entry_hash`` = sha256 of the canonical entry incl. the
previous entry's hash), so any later insertion, deletion or edit breaks the
chain and is detectable via ``GET /api/v1/audit/verify``.

Framework-side (not the agent) because this is where the *operator identity*
(from the JWT) and the case/search context are known — the agent only ever
sees a tool source, not the investigator. Scoped per tenant like every other
metadata table.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(150))
    user_name: Mapped[str | None] = mapped_column(String(150))
    # e.g. search.run, entities.commit, ai.link, ai.apply, entity.delete,
    # entity.rename, case.create, case.update, case.delete, report.export,
    # monitoring.create/update/delete.
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
