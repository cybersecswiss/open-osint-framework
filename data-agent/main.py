"""
Data agent entry point. Schema bootstrap runs in the container's CMD
(python -m app.bootstrap) before uvicorn forks workers, so we don't
race on create_all here.
"""
import logging
import os

from fastapi import FastAPI

from app.routers import activity, evidence, ingest, merge, query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("data-agent.main")
log.info("Booting worker")

app = FastAPI(
    title="OSINT Data Agent",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(ingest.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(activity.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(merge.router, prefix="/api")


# What this agent build can do. Read by the framework's self-test (and the
# update hint) to tell a customer that their agent is older than the
# framework expects — before a feature fails on them with a bare 404.
# Code-defined on purpose: version.json is written AFTER the image is built,
# so the copy inside the image always names the previous release.
API_LEVEL = "2026.09.29"
CAPABILITIES = ["ingest", "activity-log", "evidence", "entity-merge", "cross-case", "case-scoped-writes"]


@app.get("/health")
async def health():
    # Unauthenticated: nothing here is tenant data.
    return {"status": "ok", "service": "data-agent", "api_level": API_LEVEL,
            "version": os.environ.get("AGENT_VERSION") or None,
            "capabilities": CAPABILITIES}
