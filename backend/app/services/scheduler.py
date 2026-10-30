"""
In-process daily scheduler.

Why not n8n / external cron? Because we want auto-delete to "just work"
once a tenant configures it, without the operator having to import a
new n8n workflow on every fresh install. n8n cron remains an option
for operators who want one — they can hit
`POST /api/v1/maintenance/purge-old-cases` with the internal key
themselves.

Multi-worker safety: backend runs with `--workers 2`, so two
workers would otherwise both fire the purge each day. We use a Redis
SET NX EX as a daily mutex — first worker to grab the lock runs;
others see the lock and skip until it expires (~24h later).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.routers.maintenance import run_purge

log = logging.getLogger("osint.scheduler")

# 23.5 h: lock outlives one daily cycle so a duplicate worker can't
# re-fire the purge. After ~24 h the lock expires and the next cycle
# runs cleanly.
_LOCK_TTL_SECONDS = int(60 * 60 * 23.5)
_DAILY_INTERVAL = 60 * 60 * 24  # one cycle per day
_INITIAL_DELAY = 60 * 5  # don't fire on container boot — give 5 min slack


async def _try_run_purge() -> None:
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        # SET key value NX EX: only succeed if key didn't exist.
        # Worker PID in the value lets logs show which worker won the race.
        got_lock = await client.set(
            "osint:scheduler:purge:lock",
            f"worker-pid={os.getpid()}",
            nx=True,
            ex=_LOCK_TTL_SECONDS,
        )
        if not got_lock:
            log.debug("scheduler: another worker holds the daily-purge lock, skipping")
            return
        log.info("scheduler: acquired daily-purge lock, running")
        async with AsyncSessionLocal() as db:
            summary = await run_purge(db)
        total_deleted = sum(t.get("deleted", 0) for t in summary.get("tenants", {}).values())
        log.info("scheduler: daily-purge done — %d cases deleted across %d tenants",
                 total_deleted, len(summary.get("tenants", {})))
    except Exception:
        log.exception("scheduler: daily-purge failed")
    finally:
        await client.aclose()


async def daily_purge_loop() -> None:
    """Started by FastAPI lifespan. Runs forever; cancellation on
    shutdown is handled by the lifespan teardown."""
    log.info("scheduler: daily purge loop started (initial delay %ds, then every %dh)",
             _INITIAL_DELAY, _DAILY_INTERVAL // 3600)
    try:
        await asyncio.sleep(_INITIAL_DELAY)
        while True:
            await _try_run_purge()
            await asyncio.sleep(_DAILY_INTERVAL)
    except asyncio.CancelledError:
        log.info("scheduler: daily purge loop cancelled (shutdown)")
        raise


# --- News harvester ------------------------------------------------------
# Ticks often; each feed is only fetched when its own kind-interval is due
# (authority/police/cyber hourly, the rest every 30 min — enforced inside
# news_store.harvest_once). The lock TTL is shorter than the tick so it
# frees before the next tick; it exists only to stop BOTH `--workers 2`
# processes harvesting the same tick (double-fetching the feeds).
_HARVEST_TICK = 60 * 10          # check for due feeds every 10 min
_HARVEST_LOCK_TTL = 60 * 5       # < tick, so it never blocks the next one
_HARVEST_INITIAL_DELAY = 90      # let module-news finish booting first


async def _try_harvest() -> None:
    from app.services import news_store  # local import: avoids a cycle at boot
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got_lock = await client.set(
            "osint:news:harvest:lock", f"worker-pid={os.getpid()}",
            nx=True, ex=_HARVEST_LOCK_TTL,
        )
        if not got_lock:
            log.debug("scheduler: another worker holds the harvest lock, skipping")
            return
        async with AsyncSessionLocal() as db:
            summary = await news_store.harvest_once(db)
        if summary.get("due"):
            log.info("scheduler: news harvest — %s", summary)
    except Exception:
        log.exception("scheduler: news harvest failed")
    finally:
        await client.aclose()


# --- Stale search-job reaper --------------------------------------------
# Searches run as FastAPI background tasks inside the api process. Nothing
# hands them over on restart, so `bash scripts/rebuild.sh api` (or a crash,
# or an OOM kill) silently orphans every in-flight job: the row stays
# status='running' forever and the frontend polls it until the user gives
# up.
#
# Detection is heartbeat-based rather than "everything running at startup is
# dead", because with `--workers 2` a single worker can restart while its
# sibling is legitimately running a job — killing those would be worse than
# the bug. A tool call is capped at 300 s and every tool transition stamps
# the heartbeat, so silence this long means the owner is gone.
_STALE_AFTER = int(os.environ.get("SEARCH_JOB_STALE_MINUTES", "20")) * 60
_REAP_TICK = 60 * 5


async def reap_stale_jobs() -> int:
    """Fail every 'running' job whose heartbeat is older than _STALE_AFTER.
    Returns how many rows were reaped. Idempotent — safe to run from every
    worker concurrently (the WHERE clause makes a second run a no-op)."""
    from sqlalchemy import or_, update

    from app.models.search import SearchJob

    cutoff = datetime.utcnow() - timedelta(seconds=_STALE_AFTER)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(SearchJob)
            .where(
                SearchJob.status == "running",
                or_(
                    SearchJob.last_progress_at < cutoff,
                    # Rows from before the heartbeat column existed, and jobs
                    # that died before their first tool reported.
                    SearchJob.last_progress_at.is_(None), SearchJob.started_at < cutoff,
                ),
            )
            .values(
                status="failed",
                completed_at=datetime.utcnow(),
                error_message="Interrupted — the search process stopped "
                              "(api restart or crash). Please run the search again.",
            )
        )
        await db.commit()
    n = result.rowcount or 0
    if n:
        log.warning("scheduler: reaped %d stale search job(s)", n)
    return n


async def stale_job_reaper_loop() -> None:
    """Started by FastAPI lifespan. First pass runs almost immediately so a
    restart cleans up the jobs it just orphaned."""
    log.info("scheduler: stale-job reaper started (stale after %dmin, tick %dmin)",
             _STALE_AFTER // 60, _REAP_TICK // 60)
    try:
        await asyncio.sleep(30)
        while True:
            try:
                await reap_stale_jobs()
            except Exception:  # noqa: BLE001 — never let the loop die
                log.exception("scheduler: stale-job reap failed")
            await asyncio.sleep(_REAP_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: stale-job reaper cancelled (shutdown)")
        raise


# --- Audit-chain anchoring ----------------------------------------------
# Writes each tenant's chain head to a file outside Postgres. A rewritten
# audit table is internally consistent but no longer matches these, which
# is what /audit/verify reports as anchors_ok=false.
_ANCHOR_INTERVAL = int(os.environ.get("AUDIT_ANCHOR_MINUTES", "60")) * 60
_ANCHOR_LOCK_TTL = 60 * 5


async def _try_anchor() -> None:
    from app.services import audit as audit_service
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got_lock = await client.set("osint:audit:anchor:lock", f"pid={os.getpid()}",
                                    nx=True, ex=_ANCHOR_LOCK_TTL)
        if not got_lock:
            return
        n = await audit_service.anchor_chains()
        if n:
            log.info("scheduler: anchored %d audit chain(s)", n)
    except Exception:  # noqa: BLE001
        log.exception("scheduler: audit anchoring failed")
    finally:
        await client.aclose()


async def audit_anchor_loop() -> None:
    """Started by FastAPI lifespan."""
    log.info("scheduler: audit anchor loop started (every %dmin)", _ANCHOR_INTERVAL // 60)
    try:
        await asyncio.sleep(120)
        while True:
            await _try_anchor()
            await asyncio.sleep(_ANCHOR_INTERVAL)
    except asyncio.CancelledError:
        log.info("scheduler: audit anchor loop cancelled (shutdown)")
        raise


async def news_harvest_loop() -> None:
    """Started by FastAPI lifespan alongside the purge loop."""
    log.info("scheduler: news harvest loop started (initial delay %ds, tick %dmin)",
             _HARVEST_INITIAL_DELAY, _HARVEST_TICK // 60)
    try:
        await asyncio.sleep(_HARVEST_INITIAL_DELAY)
        while True:
            await _try_harvest()
            await asyncio.sleep(_HARVEST_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: news harvest loop cancelled (shutdown)")
        raise


# ── Telegram channel discovery ───────────────────────────────────────
# Threat-actor channels churn fast: they get banned, renamed and replaced
# within weeks. An operator who imports once has a stale list a month later
# and no way to notice, so the configured sources are re-scanned on a timer.
#
# Discovered channels arrive DISABLED — the scan grows the reference pool, it
# never changes what every username search actually costs. Widening the swept
# set stays a human decision.
_TG_SCAN_TICK = int(os.environ.get("TELEGRAM_SCAN_INTERVAL_MINUTES", "60")) * 60
_TG_SCAN_INITIAL_DELAY = 180


_TG_SCAN_LOCK_TTL = 60 * 10   # a scan walks several directory pages


async def _try_telegram_scan() -> None:
    """One scan per tick across all workers, not one per worker.

    This was the only network-touching loop without the lock its five
    neighbours hold, so both uvicorn workers scraped the same directory
    pages at the same moment, every hour — doubled outbound requests
    against third-party sites that have every reason to rate-limit or block
    us for it, and two concurrent passes racing to insert the same new
    channels.
    """
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got_lock = await client.set("osint:telegram:scan:lock", f"pid={os.getpid()}",
                                    nx=True, ex=_TG_SCAN_LOCK_TTL)
        if not got_lock:
            log.debug("scheduler: another worker holds the telegram-scan lock")
            return
        from app.services.telegram_channels import get_sources, harvest_sources
        if not [s for s in await get_sources(force=True) if s["enabled"]]:
            return          # nothing configured — don't hit the network
        res = await harvest_sources()
        if res.get("added"):
            log.info("scheduler: telegram scan — %s found, %s new (pool %s)",
                     res.get("found"), res.get("added"), res.get("total"))
    except Exception:  # noqa: BLE001 — a scan failure must not kill the loop
        log.exception("scheduler: telegram source scan failed")
    finally:
        await client.aclose()


async def telegram_scan_loop() -> None:
    """Started by FastAPI lifespan alongside the other loops."""
    log.info("scheduler: telegram source scan started (initial delay %ds, tick %dmin)",
             _TG_SCAN_INITIAL_DELAY, _TG_SCAN_TICK // 60)
    try:
        await asyncio.sleep(_TG_SCAN_INITIAL_DELAY)
        while True:
            await _try_telegram_scan()
            await asyncio.sleep(_TG_SCAN_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: telegram source scan cancelled (shutdown)")
        raise


# --- Forum reference indexes --------------------------------------------
# module-forums carries two lookup indexes (830k crime-forum handles, the
# link-base directory). Both had a refresh endpoint and neither was ever
# called: the /cache volume stayed empty and both remained the copies baked
# into the image, going stale by the day. A refresh button nobody presses is a stale index with extra steps.
#
# Ticks hourly and refreshes at most ONE index whose file is older than
# FORUM_INDEX_REFRESH_DAYS (7). The one-at-a-time rule is a memory guard,
# not tidiness: rebuilding the actor index holds the loaded copy and the new
# dict at once (~345 MB + ~350 MB) — enough to get that container OOM-killed.
_FORUM_IDX_TICK = int(os.environ.get("FORUM_INDEX_TICK_MINUTES", "60")) * 60
_FORUM_IDX_LOCK_TTL = 60 * 30     # a rebuild runs minutes, not seconds
# Later than the other loops: a rebuild is heavy and there is no reason for
# it to compete with the api's own startup or the first news harvest.
_FORUM_IDX_INITIAL_DELAY = 300


async def _try_forum_index_refresh() -> None:
    from app.services import forum_indexes
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got_lock = await client.set(
            "osint:forum-index:refresh:lock", f"worker-pid={os.getpid()}",
            nx=True, ex=_FORUM_IDX_LOCK_TTL,
        )
        if not got_lock:
            log.debug("scheduler: another worker holds the forum-index lock")
            return
        res = await forum_indexes.refresh_due()
        if res.get("triggered"):
            log.info("scheduler: forum index refresh — %s", res)
    except Exception:  # noqa: BLE001 — never let this kill the loop
        log.exception("scheduler: forum index refresh failed")
    finally:
        await client.aclose()


async def forum_index_loop() -> None:
    """Started by FastAPI lifespan alongside the other loops."""
    log.info("scheduler: forum index refresh started (initial delay %ds, tick %dmin)",
             _FORUM_IDX_INITIAL_DELAY, _FORUM_IDX_TICK // 60)
    try:
        await asyncio.sleep(_FORUM_IDX_INITIAL_DELAY)
        while True:
            await _try_forum_index_refresh()
            await asyncio.sleep(_FORUM_IDX_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: forum index refresh cancelled (shutdown)")
        raise


# --- Monitoring rescan ---------------------------------------------------
#
# ⚠️ This replaces the n8n `scheduled-rescan` workflow, which **could not
# work**. That workflow made two calls with the internal
# key: `GET /monitoring/pending-scans`, which accepts it, and then
# `POST /search`, which does not — it hangs off `get_current_user` and
# answers an internal-key request with HTTP 403.
#
# The damage was not the failed call. `pending-scans` advances `last_scan`
# and `next_scan` **before returning**, deliberately, so a double-firing cron
# cannot hand out the same config twice. With the second call failing, that
# safeguard turned into a lie: the schedule moved on, no search ran, and the
# UI told the investigator "last checked 5 minutes ago". A tool that claims
# to be watching something and is not is worse than one that says nothing.
#
# Running it here instead of in n8n fixes three things at once:
#   * no new auth path — nothing has to accept a search without a user;
#   * the audit entry gets an honest actor (`scheduler`) instead of none;
#   * it works on a fresh install with no workflow import, which is exactly
#     why the auto-delete purge is not in n8n either.
#
# And the ordering is reversed on purpose: the search is started FIRST and
# the schedule advances only for configs that actually got one.
_MON_TICK = 60 * 5
_MON_LOCK_TTL = 60 * 4          # < tick, so it frees before the next one
_MON_INITIAL_DELAY = 120        # let the modules finish booting
# A cap per tick. Twenty due configs firing at once would be twenty parallel
# module fan-outs; the rest simply come round on the next tick.
_MON_MAX_PER_TICK = int(os.environ.get("MONITORING_MAX_PER_TICK", "5") or 5)


async def _rescan_then_alert(
    job_id, config_id, case_id, tenant: str,
    query: str, query_type: str, modules: list[str],
) -> None:
    """Run the scheduled search, then raise alerts for what it added.

    Awaiting the search rather than firing both as independent tasks is the
    whole point: the alert compares the case against the job's `started_at`,
    so it must not run until the pushes are done. Started as one task, the
    two would race and the alert would usually see an empty delta — the
    quietest possible failure, and one no test that stubs the search would
    catch.

    Failures here never touch the search: the job has already completed and
    been recorded. An alert that could not be raised is logged and the run
    stands.
    """
    from app.routers.search import _run_search
    from app.services import alerting

    try:
        await _run_search(job_id, case_id, tenant, query, query_type, modules)
    except Exception:
        log.exception("scheduler: rescan job=%s failed", job_id)
        return

    try:
        async with AsyncSessionLocal() as db:
            summary = await alerting.raise_alerts_for_job(config_id, job_id, db)
        if summary.get("alerts"):
            log.info("scheduler: config=%s raised %d alert(s)", config_id, summary["alerts"])
    except Exception:
        log.exception("scheduler: alerting for config=%s failed", config_id)


async def run_due_monitorings() -> dict:
    """Start a search for every monitoring config that is due."""
    from app.models.monitoring import MonitoringConfig
    from app.models.case import Case
    from app.models.search import SearchJob
    from app.services import audit

    now = datetime.utcnow()
    started, skipped = [], []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(MonitoringConfig).where(
                MonitoringConfig.is_active.is_(True),
                MonitoringConfig.next_scan <= now,
            ).order_by(MonitoringConfig.next_scan).limit(_MON_MAX_PER_TICK)
        )).scalars().all()

        for cfg in rows:
            query = (cfg.query or "").strip()
            if not query:
                # Configs created before `query` was persisted cannot be
                # reproduced. Say so once per tick rather than firing a
                # placeholder search that matches no module.
                skipped.append({"id": str(cfg.id), "reason": "no stored selector"})
                continue
            case = await db.scalar(select(Case).where(
                Case.id == cfg.case_id, Case.tenant == cfg.tenant))
            if case is None:
                skipped.append({"id": str(cfg.id), "reason": "case gone"})
                continue

            # A module the customer has since switched off (or the licence
            # dropped) must not run just because an old watch names it.
            from app.services.tenant_registry import get_usable_modules
            usable = await get_usable_modules(cfg.tenant)
            modules = [m for m in (cfg.modules or []) if usable is None or m in usable]
            if cfg.modules and not modules:
                skipped.append({"id": str(cfg.id), "reason": "all modules disabled"})
                continue

            job = SearchJob(
                tenant=cfg.tenant, case_id=cfg.case_id, query=query,
                query_type=cfg.query_type or "keyword",
                modules_used=modules, status="running",
                # NOT NULL, and the honest answer: nobody typed this. A job
                # list that attributes an automatic rescan to the last human
                # who touched the config would be a small lie in a table an
                # investigator reads to reconstruct what happened.
                created_by="scheduler",
            )
            db.add(job)
            await db.flush()
            job_id = job.id

            # Only now does the schedule move. If anything above raised, the
            # config stays due and is retried on the next tick — the opposite
            # of the old order, where the clock advanced first.
            cfg.last_scan = now
            cfg.next_scan = now + timedelta(hours=cfg.interval_hours or 24)
            await db.commit()

            asyncio.create_task(_rescan_then_alert(
                job_id, cfg.id, cfg.case_id, cfg.tenant, query,
                cfg.query_type or "keyword", modules,
            ))
            # The customer's record of an unattended search. The purpose is
            # the one stated when the watch was created (monitoring.create,
            # same monitoring_id) — best effort, a rescan is not blocked.
            from app.services.activity import record_activity
            await record_activity(
                cfg.tenant, "monitoring.rescan", user_name="scheduler",
                case_id=cfg.case_id,
                details={"monitoring_id": str(cfg.id), "job_id": str(job_id),
                         "query": query, "query_type": cfg.query_type,
                         "modules": cfg.modules})
            await audit.log_action(
                cfg.tenant, "monitoring.rescan",
                user={"username": "scheduler", "user_id": "scheduler"},
                target_type="case", target_id=cfg.case_id,
                details={"monitoring_id": str(cfg.id), "job_id": str(job_id),
                         "query_type": cfg.query_type, "modules": cfg.modules},
            )
            started.append(str(cfg.id))

    return {"started": started, "skipped": skipped}


# --- Licence expiry warnings -----------------------------------------
#
# Replaces the n8n workflow `License Expiry Monitor`, for the same three
# reasons the monitoring rescan moved out of n8n:
#
#   * the n8n workflows are NOT imported on a fresh install, so on a new
#     server the expiry warning simply would not exist — and nothing would
#     say so, which is the failure mode that matters here: a licence that
#     lapses unnoticed takes a customer offline;
#   * it removes the last place where n8n needs the internal key;
#   * the action gets an honest actor.
#
# Once a day, and the job itself decides which tenants cross a threshold
# today — so a 30-day window produces one mail at 30 days, not thirty.
_EXPIRY_TICK = 60 * 60 * 24
_EXPIRY_LOCK_TTL = int(60 * 60 * 23.5)
_EXPIRY_INITIAL_DELAY = 60 * 10


async def _try_license_expiry() -> None:
    from app.services import operator_notify

    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got = await client.set("osint:license-expiry:lock", f"worker-pid={os.getpid()}",
                               nx=True, ex=_EXPIRY_LOCK_TTL)
        if not got:
            return
        summary = await operator_notify.run_license_expiry_check()
        if summary.get("warned") or summary.get("skipped") or summary.get("error"):
            log.info("scheduler: licence expiry — %s", summary)
    except Exception:
        log.exception("scheduler: licence expiry check failed")
    finally:
        await client.aclose()


async def license_expiry_loop() -> None:
    """Started by FastAPI lifespan alongside the other loops."""
    log.info("scheduler: licence expiry loop started (delay %ds, then daily)",
             _EXPIRY_INITIAL_DELAY)
    try:
        await asyncio.sleep(_EXPIRY_INITIAL_DELAY)
        while True:
            await _try_license_expiry()
            await asyncio.sleep(_EXPIRY_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: licence expiry loop cancelled (shutdown)")
        raise


# --- Fallback reconciliation ------------------------------------------
#
# An obvious idea is to "schedule a periodic flush of the framework-local
# entities/edges tables — local persistence is unbounded; it only fills on
# agent-unreachable fallback, but a web_intel scan can write 20k+ rows".
#
# ⚠️ A flush would be DATA LOSS, not housekeeping. Those rows exist
# precisely because the push to the customer failed, so they are the ONLY
# copy of that finding — the agent never received it. Deleting them on a
# timer would quietly destroy exactly the investigative work the fallback
# path was written to save, and nobody would ever know which rows went.
#
# So this delivers instead of deletes: retry the push, and remove locally
# only what the customer's store has actually accepted. Unbounded growth
# stops for the right reason, and the sovereignty rule is served rather
# than bent — case data ends up where it belongs.
#
# What is NOT retried: an auth failure. The same rule as everywhere else
# on this path (services/agent_client.py) — a rejected key is a
# misconfiguration, and treating it as "agent busy" is how operator-side
# copies of customer data become permanent.
_RECON_TICK = 60 * 30
_RECON_LOCK_TTL = 60 * 25
_RECON_INITIAL_DELAY = 60 * 8
_RECON_BATCH = int(os.environ.get("RECONCILE_BATCH", "2000") or 2000)


async def reconcile_local_fallback() -> dict:
    """Push framework-local fallback rows to the agent; delete what lands."""
    from sqlalchemy import delete as sqla_delete
    from app.models.case import Case
    from app.models.entity import Edge, Entity
    from app.routers.search import _agent_payload
    from app.services.agent_client import (
        AgentAuthError, AgentUnavailable, push_to_agent,
    )
    from app.services.tenant_registry import AgentKeyUnavailable, TenantNotConfigured

    out: dict[str, Any] = {"cases": 0, "entities": 0, "edges": 0, "skipped": []}
    async with AsyncSessionLocal() as db:
        # Group by case: the ingest is case-scoped, and a case is the unit
        # the customer's store understands.
        rows = (await db.execute(
            select(Entity.tenant, Entity.case_id, func.count())
            .group_by(Entity.tenant, Entity.case_id)
        )).all()

        for tenant, case_id, _count in rows:
            entities = (await db.execute(
                select(Entity).where(Entity.case_id == case_id,
                                     Entity.tenant == tenant).limit(_RECON_BATCH)
            )).scalars().all()
            if not entities:
                continue
            ids = {e.id for e in entities}
            # Only edges whose BOTH endpoints are in this batch: the agent
            # skips dangling edges, and sending one whose partner is still
            # here would drop it silently on the far side.
            edges = [
                g for g in (await db.execute(
                    select(Edge).where(Edge.case_id == case_id, Edge.tenant == tenant)
                )).scalars().all()
                if g.from_entity in ids and g.to_entity in ids
            ]
            case = await db.scalar(select(Case).where(Case.id == case_id))

            try:
                await push_to_agent(
                    tenant, "/api/ingest",
                    _agent_payload(case_id, "reconcile", entities, edges, case),
                )
            except AgentAuthError as exc:
                # Loud, and never a reason to delete anything.
                log.error("reconcile: tenant=%s case=%s — agent REJECTED the key: %s",
                          tenant, case_id, exc)
                out["skipped"].append({"case": str(case_id), "reason": "auth"})
                continue
            except (AgentUnavailable, TenantNotConfigured, AgentKeyUnavailable) as exc:
                log.info("reconcile: tenant=%s case=%s — not deliverable yet (%s)",
                         tenant, case_id, type(exc).__name__)
                out["skipped"].append({"case": str(case_id), "reason": "unreachable"})
                continue
            except Exception:
                log.exception("reconcile: tenant=%s case=%s failed", tenant, case_id)
                out["skipped"].append({"case": str(case_id), "reason": "error"})
                continue

            # Accepted. Delete edges first — they reference the entities.
            await db.execute(sqla_delete(Edge).where(
                Edge.case_id == case_id, Edge.tenant == tenant,
                Edge.id.in_([g.id for g in edges]),
            ))
            await db.execute(sqla_delete(Entity).where(Entity.id.in_(ids)))
            await db.commit()
            out["cases"] += 1
            out["entities"] += len(entities)
            out["edges"] += len(edges)
            log.info("reconcile: tenant=%s case=%s — %d entities, %d edges delivered "
                     "and removed from the operator DB",
                     tenant, case_id, len(entities), len(edges))
    return out


async def _try_reconcile() -> None:
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got = await client.set("osint:reconcile:lock", f"worker-pid={os.getpid()}",
                               nx=True, ex=_RECON_LOCK_TTL)
        if not got:
            return
        summary = await reconcile_local_fallback()
        if summary["entities"] or summary["skipped"]:
            log.info("scheduler: fallback reconciliation — %s", summary)
    except Exception:
        log.exception("scheduler: fallback reconciliation failed")
    finally:
        await client.aclose()


async def reconcile_loop() -> None:
    """Started by FastAPI lifespan alongside the other loops."""
    log.info("scheduler: fallback reconciliation loop started (delay %ds, tick %dmin)",
             _RECON_INITIAL_DELAY, _RECON_TICK // 60)
    try:
        await asyncio.sleep(_RECON_INITIAL_DELAY)
        while True:
            await _try_reconcile()
            await asyncio.sleep(_RECON_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: fallback reconciliation loop cancelled (shutdown)")
        raise


async def _try_monitoring() -> None:
    client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    try:
        got = await client.set("osint:monitoring:lock", f"worker-pid={os.getpid()}",
                               nx=True, ex=_MON_LOCK_TTL)
        if not got:
            return
        summary = await run_due_monitorings()
        if summary["started"] or summary["skipped"]:
            log.info("scheduler: monitoring rescan — %s", summary)
    except Exception:
        log.exception("scheduler: monitoring rescan failed")
    finally:
        await client.aclose()


async def monitoring_rescan_loop() -> None:
    """Started by FastAPI lifespan alongside the other loops."""
    log.info("scheduler: monitoring rescan loop started (delay %ds, tick %dmin, max %d/tick)",
             _MON_INITIAL_DELAY, _MON_TICK // 60, _MON_MAX_PER_TICK)
    try:
        await asyncio.sleep(_MON_INITIAL_DELAY)
        while True:
            await _try_monitoring()
            await asyncio.sleep(_MON_TICK)
    except asyncio.CancelledError:
        log.info("scheduler: monitoring rescan loop cancelled (shutdown)")
        raise
