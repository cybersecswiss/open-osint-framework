from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import engine

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


@router.get("/api/v1/health/deep")
async def health_deep() -> dict:
    """Verifies dependencies the backend actually needs to function:
    Postgres (data) and Redis (the daily-purge scheduler lock). An empty
    check set or any failing check yields 'degraded'."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = f"fail: {e}"

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            await client.ping()
            checks["redis"] = "ok"
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"fail: {e}"

    healthy = bool(checks) and all(v == "ok" for v in checks.values())
    return {"status": "ok" if healthy else "degraded", "checks": checks}
