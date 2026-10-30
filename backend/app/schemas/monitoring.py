from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MonitoringCreate(BaseModel):
    entity_id: UUID
    case_id: UUID
    interval_hours: int = 24
    # Selector reproduced on each scheduled rescan. Optional for
    # backwards compatibility; when omitted the scheduler falls back to
    # a best-effort default module set.
    query: str | None = None
    query_type: str | None = None
    modules: list[str] = []
    # Empty = every available trigger. The old six-value vocabulary is
    # still accepted and translated (services/alerting.LEGACY_TRIGGER_MAP);
    # the default is empty rather than three names, two of which named
    # things this pipeline cannot detect. GET /monitoring/triggers is the
    # authoritative list.
    alert_on: list[str] = []
    alert_email: str | None = None
    alert_webhook: str | None = None
    # Why this selector is watched. Same rule as a search: mandatory when the
    # tenant requires it, recorded only at the customer, never stored here.
    purpose: str | None = Field(default=None, max_length=500)


class MonitoringUpdate(BaseModel):
    """Partial update. All fields optional;
    omitted fields are left untouched."""
    is_active: bool | None = None
    interval_hours: int | None = None
    query: str | None = None
    query_type: str | None = None
    modules: list[str] | None = None
    alert_on: list[str] | None = None
    alert_email: str | None = None
    alert_webhook: str | None = None


class MonitoringResponse(BaseModel):
    """
    The create/list endpoints return SQLAlchemy ORM rows directly;
    FastAPI cannot serialize those without a schema. This response model
    is a pure addition so the endpoint code works as written.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_id: UUID
    case_id: UUID
    is_active: bool
    interval_hours: int
    query: str | None
    query_type: str | None
    modules: list[str]
    alert_on: list[str]
    alert_email: str | None
    alert_webhook: str | None
    last_scan: datetime | None
    next_scan: datetime | None
    # When the first run recorded the starting state, and how much it
    # covered. NULL means this monitor has not run yet — its first cycle
    # will be quiet on purpose, and the UI needs to be able to say so.
    baseline_at: datetime | None = None
    baseline_suppressed: int | None = None
    created_by: str
    created_at: datetime
