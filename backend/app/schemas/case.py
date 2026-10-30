from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

# The stages of an investigation, in the order they usually happen —
# "usually", because they are not enforced and jumping back is normal work,
# not an error. Stored as a stable key so the UI language never changes what
# is in the case.
CASE_PHASES = ("new", "collecting", "analysing", "reporting")


MAX_MEMBERS = 50


def _clean_members(v: list[str] | None) -> list[str] | None:
    if v is None:
        return None
    out: list[str] = []
    for m in v:
        m = (m or "").strip()
        if m and m not in out:
            out.append(m[:100])
    if len(out) > MAX_MEMBERS:
        raise ValueError(f"at most {MAX_MEMBERS} members")
    return out


def _known_template(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    from app.services.playbooks import PLAYBOOK_KEYS
    if v not in PLAYBOOK_KEYS:
        raise ValueError("unknown case template")
    return v


class CaseCreate(BaseModel):
    title: str
    description: str | None = None
    priority: str = "normal"
    # Need-to-know: a restricted case is visible to its
    # creator, assignee, members and the tenant's admins only.
    restricted: bool = False
    members: list[str] = []
    template: str | None = None

    @field_validator("members")
    @classmethod
    def _members(cls, v: list[str]) -> list[str]:
        return _clean_members(v) or []

    @field_validator("template")
    @classmethod
    def _template(cls, v: str | None) -> str | None:
        return _known_template(v)


class CaseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    phase: str | None = None
    restricted: bool | None = None
    members: list[str] | None = None
    template: str | None = None

    @field_validator("template")
    @classmethod
    def _template(cls, v: str | None) -> str | None:
        return _known_template(v)

    @field_validator("members")
    @classmethod
    def _members(cls, v: list[str] | None) -> list[str] | None:
        return _clean_members(v)

    @field_validator("phase")
    @classmethod
    def _known_phase(cls, v: str | None) -> str | None:
        # Rejected rather than silently corrected: an unknown phase means the
        # caller and the server disagree about the workflow, and quietly
        # storing "analysing" for a typo would hide that.
        if v is not None and v not in CASE_PHASES:
            raise ValueError(f"phase must be one of {', '.join(CASE_PHASES)}")
        return v


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_number: str
    title: str
    description: str | None
    status: str
    phase: str = "new"
    priority: str
    created_by: str
    assigned_to: str | None
    restricted: bool = False
    members: list[str] = []
    template: str | None = None
    created_at: datetime
    updated_at: datetime
