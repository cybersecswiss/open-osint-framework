import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import License, get_db, settings

router = APIRouter(prefix="/api/v1/license", tags=["license"])


def verify_internal(x_internal_key: str = Header(..., alias="X-Internal-Key")):
    if not hmac.compare_digest(x_internal_key, settings.internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


class LicenseCreate(BaseModel):
    tenant: str
    contact_email: str
    valid_days: int = 365


@router.post("/create")
async def create_license(
    payload: LicenseCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(verify_internal),
):
    # Reject duplicate tenant up front so the caller gets a clean 409
    # instead of a 500 from the unique-constraint violation.
    existing = await db.scalar(select(License).where(License.tenant == payload.tenant))
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"License for tenant '{payload.tenant}' already exists",
        )

    license_key = secrets.token_urlsafe(48)
    agent_api_key = secrets.token_urlsafe(48)
    lic = License(
        tenant=payload.tenant,
        license_key=license_key,
        agent_api_key=agent_api_key,
        contact_email=payload.contact_email,
        valid_until=datetime.utcnow() + timedelta(days=payload.valid_days),
    )
    db.add(lic)
    await db.commit()
    return {
        "tenant": payload.tenant,
        "license_key": license_key,
        "agent_api_key": agent_api_key,
        "valid_until": lic.valid_until.isoformat(),
    }


@router.get("/validate")
async def validate_license(
    x_license_key: str = Header(..., alias="X-License-Key"),
    db: AsyncSession = Depends(get_db),
):
    lic = await db.scalar(select(License).where(License.license_key == x_license_key))
    if not lic or not lic.is_active or lic.valid_until < datetime.utcnow():
        return {"valid": False}
    return {
        "valid": True,
        "tenant": lic.tenant,
        "valid_until": lic.valid_until.isoformat(),
    }


@router.get("/agent-key")
async def get_agent_key(
    x_license_key: str = Header(..., alias="X-License-Key"),
    db: AsyncSession = Depends(get_db),
):
    lic = await db.scalar(select(License).where(License.license_key == x_license_key))
    if not lic or not lic.is_active or lic.valid_until < datetime.utcnow():
        # Same expiry check as /validate — an expired license must not
        # keep handing out the agent key.
        raise HTTPException(status_code=403, detail="Invalid or expired license")
    return {"api_key": lic.agent_api_key}
