"""
Operator-global platform settings store (API keys + Telegram creds).
Internal-key only — the framework backend is the sole caller; it proxies
the Product-Owner console Settings tab and enforces platform_admin auth
on its side. This store is a dumb key/value bag: it never masks or
validates, that is the backend's job.
"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlatformSetting, get_db, settings

router = APIRouter(prefix="/api/v1/platform-settings", tags=["platform-settings"])


def verify_internal(x_internal_key: str = Header(..., alias="X-Internal-Key")):
    if not hmac.compare_digest(x_internal_key, settings.internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


class SettingsUpdate(BaseModel):
    values: dict[str, str]


@router.get("", dependencies=[Depends(verify_internal)])
async def get_settings(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    rows = (await db.execute(select(PlatformSetting))).scalars().all()
    return {r.skey: (r.svalue or "") for r in rows}


@router.put("", dependencies=[Depends(verify_internal)])
async def put_settings(payload: SettingsUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Upsert every key in `values`. An empty-string value clears that
    key (falls back to .env on the module side)."""
    for skey, svalue in payload.values.items():
        stmt = pg_insert(PlatformSetting).values(skey=skey, svalue=svalue or "")
        stmt = stmt.on_conflict_do_update(
            index_elements=["skey"], set_={"svalue": svalue or ""}
        )
        await db.execute(stmt)
    await db.commit()
    return {"updated": list(payload.values.keys())}
