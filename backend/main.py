"""
OOF — FastAPI entry point.

Lifespan handler creates ORM tables via `Base.metadata.create_all` as a
safety net for clean installs that haven't run alembic yet. Production
uses alembic migrations; create_all is idempotent and won't conflict.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, agent_proxy, ai, audit, cases, evidence, health, maintenance, monitoring, n8n_gate, oidc, platform, reports, search, support, telegram, news
from app.services.osint_orchestrator import refresh_manifests
from app.services.scheduler import (
    audit_anchor_loop,
    daily_purge_loop,
    forum_index_loop,
    license_expiry_loop,
    monitoring_rescan_loop,
    news_harvest_loop,
    reconcile_loop,
    stale_job_reaper_loop,
    telegram_scan_loop,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# ...and then say it again, explicitly, for our own namespace.
#
# `basicConfig()` is a NO-OP once the root logger already has handlers, and
# uvicorn installs its handlers BEFORE it imports this module. The line above
# therefore never took effect: every `log.info()` in the backend was silently
# discarded and only WARNING and above ever reached the container log. That
# hid, among others, `"incremental push skipped (...) — persisting locally"` —
# the moment investigation data lands in the OPERATOR's database instead of
# the customer's, which is the single event an operator most needs to see.
# Setting our own logger tree keeps uvicorn's handlers and formatting.
logging.getLogger("osint").setLevel(logging.INFO)
log = logging.getLogger("osint.main")
log.info("Booting worker")

# Schema bootstrap runs in entrypoint.sh before workers fork — see
# app/bootstrap.py. Don't repeat it here, otherwise N workers each
# attempt create_all in parallel.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-delete — daily background loop that purges
    # closed cases past the per-tenant frist. Multi-worker-safe via a
    # Redis SET-NX lock (see app/services/scheduler.py).
    purge_task = asyncio.create_task(daily_purge_loop())
    # Background news harvester — polls the RSS feeds on a schedule and
    # caches articles in the framework DB so analyst searches read the DB
    # instead of live-hitting (and getting blocked by) authority feeds.
    harvest_task = asyncio.create_task(news_harvest_loop())
    # Fails search jobs whose owning process died (api restart / crash).
    # Without it they stay 'running' forever and the UI polls them for good.
    reaper_task = asyncio.create_task(stale_job_reaper_loop())
    # Replaces the n8n scheduled-rescan workflow, which could not
    # authenticate against /search — see scheduler.py.
    monitoring_task = asyncio.create_task(monitoring_rescan_loop())
    tg_scan_task = asyncio.create_task(telegram_scan_loop())
    # Keeps the two forum reference indexes (830k crime-forum handles, the
    # link-base directory) from going stale. Both had a refresh endpoint
    # nobody ever called, so they stayed the copies baked into the image.
    # Refreshes at most ONE index per tick; see the
    # memory note in scheduler.py.
    forum_idx_task = asyncio.create_task(forum_index_loop())
    # Anchors the audit chain heads outside Postgres so a wholesale
    # rewrite of audit_log becomes detectable.
    anchor_task = asyncio.create_task(audit_anchor_loop())
    # Delivers framework-local fallback rows to the customer's agent once it
    # is reachable again, and deletes locally only what was accepted. A
    # periodic FLUSH of those tables would be data loss: those rows exist because the push failed, so they
    # are the only copy. See scheduler.py.
    reconcile_task = asyncio.create_task(reconcile_loop())
    # Warns customers before their licence lapses. Replaces the n8n
    # `License Expiry Monitor`, which a fresh install never imports — see
    # services/operator_notify.py.
    expiry_task = asyncio.create_task(license_expiry_loop())
    # Pull each module's /manifest once at boot; the orchestrator and
    # the /api/v1/search/modules endpoint read from this cache.
    # Failures are non-fatal — modules that come online later are
    # picked up via POST /api/v1/search/modules/refresh.
    try:
        await refresh_manifests()
    except Exception:  # noqa: BLE001
        log.exception("initial module-manifest refresh failed")
    try:
        yield
    finally:
        for task in (purge_task, harvest_task, reaper_task, monitoring_task, anchor_task,
                     tg_scan_task, forum_idx_task, reconcile_task, expiry_task):
            task.cancel()
        for task in (purge_task, harvest_task, reaper_task, anchor_task, tg_scan_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="OOF API",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url=None,
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# CORS — restricted to the known frontend origins. With
# allow_credentials=True the spec forbids a "*" origin anyway, so we
# enumerate them explicitly and only allow the methods/headers the SPA
# actually sends.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"https://{settings.public_host}:{settings.public_https_port}",
        f"http://{settings.public_host}:{settings.public_http_port}",
        "https://localhost",
        "https://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Internal-Key"],
)

app.include_router(health.router)
app.include_router(cases.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(monitoring.router, prefix="/api/v1")
app.include_router(agent_proxy.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(oidc.router, prefix="/api/v1")
app.include_router(maintenance.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(telegram.router, prefix="/api/v1")
app.include_router(support.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(platform.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")
app.include_router(evidence.router, prefix="/api/v1")
# Unauthenticated: nginx auth_request gate for the public /n8n/ route.
app.include_router(n8n_gate.router, prefix="/api/v1")
