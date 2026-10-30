import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Case(Base):
    __tablename__ = "cases"
    # Case numbers are generated per tenant, so a global UNIQUE(case_number)
    # would not fit. Composite unique reconciles both: each tenant
    # gets a fresh YYYY-001 sequence, and there's still a uniqueness
    # guarantee globally per (tenant, case_number).
    __table_args__ = (
        UniqueConstraint("tenant", "case_number", name="uq_cases_tenant_case_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    # Where the investigator is in their work — orientation, not a gate.
    #
    # Separate from `status` on purpose: status answers "is this case still
    # ours" (open/closed), phase answers "what am I doing right now". Never
    # advanced automatically. A phase that moves itself asserts something
    # about the state of an investigation that only the person doing it
    # knows, and in a case file a wrong such assertion is worse than none.
    phase: Mapped[str] = mapped_column(String(20), default="new")
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    created_by: Mapped[str] = mapped_column(String(100))
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    # Need-to-know (services/case_access.py). A restricted case is
    # visible to its creator, assignee, members and the tenant's admins only.
    # Offence-type template (a playbook key) the case was opened with — sets
    # the search preset, report outline and typical next tools.
    template: Mapped[str | None] = mapped_column(String(50))
    restricted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    members: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default=text("'{}'::varchar[]"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime)
