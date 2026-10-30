"""
License server entry point. Schema bootstrap runs in CMD before
workers fork (see Dockerfile).
"""
import logging

from fastapi import FastAPI

from app.routers.licenses import router as license_router
from app.routers.platform_settings import router as platform_settings_router
from app.routers.support import router as support_router
from app.routers.tenants import router as tenant_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("license-server.main")
log.info("Booting worker")

app = FastAPI(title="OSINT License Server", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(license_router)
app.include_router(tenant_router)
app.include_router(support_router)
app.include_router(platform_settings_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "license"}
