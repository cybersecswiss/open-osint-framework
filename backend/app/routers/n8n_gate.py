"""Unauthenticated gate for nginx ``auth_request``: is external n8n access on?

Returns 204 (allow) or 403 (deny). No auth by design — nginx cannot forward
the operator's platform JWT on a subrequest, and this endpoint leaks only
the on/off state of the operator toggle. The authoritative toggle lives in
``/api/v1/platform/n8n-access`` (platform_admin only).
"""
from fastapi import APIRouter, Response

from app.services import n8n_access

router = APIRouter(tags=["n8n-gate"])


@router.get("/n8n-gate")
async def n8n_gate() -> Response:
    if await n8n_access.is_enabled():
        return Response(status_code=204)
    return Response(status_code=403)
