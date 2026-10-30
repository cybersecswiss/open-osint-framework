"""Writes to the CUSTOMER's activity log (agent `POST /api/activity`).

The customer, as data controller, must be able to answer "who looked this up,
and why?". That record lives in their store, with the selector in clear text
and the stated purpose; the operator's own audit keeps only a fingerprint and
the fact that a purpose was given.

`required=True` makes an unwritable record an error the caller must honour
(the action does not happen). Otherwise it is logged and the action proceeds —
a tenant that has not asked for the record should not lose searches to a
store that is briefly down.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.services.agent_client import AgentAuthError, AgentUnavailable, push_to_agent
from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

log = logging.getLogger("osint.activity")


class ActivityLogUnavailable(Exception):
    """A required activity record could not be written."""


async def record_activity(
    tenant: str,
    action: str,
    *,
    user_name: Optional[str],
    case_id: Optional[uuid.UUID | str],
    details: dict[str, Any],
    ip: Optional[str] = None,
    required: bool = False,
) -> bool:
    try:
        await push_to_agent(tenant, "/api/activity", {
            "action": action, "user_name": user_name,
            "case_id": str(case_id) if case_id else None,
            "ip_address": ip, "details": details,
        })
        return True
    except AgentAuthError:
        # Never "unavailable" — see services/agent_client.py.
        raise
    except (AgentUnavailable, AgentKeyUnavailable, TenantNotConfigured) as e:
        if required:
            raise ActivityLogUnavailable(str(e)) from e
        log.warning("activity %s for %s not recorded at the customer: %s", action, tenant, e)
        return False
