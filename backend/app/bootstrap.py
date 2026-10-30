"""
One-shot startup: ensure ORM tables exist. Runs in a single process
before uvicorn forks workers, so we don't get the create_all race
that hits when N workers all try to bootstrap simultaneously.

Idempotent: create_all is a no-op when tables already exist. Alembic
migrations remain the production-grade path; this is the safety net
for fresh installs.

ADHOC_MIGRATIONS handles columns added to existing tables after the
first install. `create_all` does NOT re-add columns to existing
tables, so we run these `ADD COLUMN IF NOT EXISTS` statements every
boot — idempotent, cheap, no alembic step needed.
"""
import asyncio
import logging

from sqlalchemy import text

from app.database import Base, engine
from app.models import audit, case, entity, monitoring, news, search  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("osint.bootstrap")


ADHOC_MIGRATIONS: list[str] = [
    # Per-tool progress for the search-form polling loop
    "ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS tool_progress JSONB DEFAULT '[]'::jsonb",
    # Persisted entity/edge counts because pushed-to-agent
    # rows aren't visible from the framework's local DB (where the
    # GET /search/{id} counter used to look)
    "ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS entities_count INTEGER DEFAULT 0",
    "ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS edges_count    INTEGER DEFAULT 0",
    # Persist the original selector on monitoring configs so
    # scheduled re-scans reproduce the real search instead of a
    # placeholder query that matched no module manifest.
    "ALTER TABLE monitoring_configs ADD COLUMN IF NOT EXISTS query      VARCHAR(500)",
    "ALTER TABLE monitoring_configs ADD COLUMN IF NOT EXISTS query_type VARCHAR(50)",
    "ALTER TABLE monitoring_configs ADD COLUMN IF NOT EXISTS modules    VARCHAR[] DEFAULT '{}'",
    # Heartbeat for the stale-job reaper. Searches run as
    # in-process background tasks, so a container restart used to strand
    # them on status='running' forever, with the UI polling indefinitely. Every progress
    # update now stamps this column and the reaper fails anything that has
    # gone quiet for too long.
    "ALTER TABLE search_jobs ADD COLUMN IF NOT EXISTS last_progress_at TIMESTAMP",
]

# Each runs in its OWN autocommit connection with try/except: a failure
# (e.g. the DB role can't CREATE EXTENSION) must NOT abort the boot or
# poison the shared transaction above — the news search degrades to a
# plain LIKE scan, which is correct, just unindexed.
BEST_EFFORT_MIGRATIONS: list[str] = [
    # Fast substring-AND search over the harvested news cache.
    # pg_trgm is a "trusted" extension since PG13, so the DB owner can
    # create it without superuser; if not, we fall back to plain LIKE.
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS ix_news_articles_search_trgm "
    "ON news_articles USING gin (search_text gin_trgm_ops)",
    # Enforce append-only on the audit chain at the DATABASE
    # level. The hash chain proves nothing on its own if rows can simply be
    # rewritten and re-chained; nothing in the application ever updates or
    # deletes an audit row (case purge does not touch it), so a trigger that
    # refuses both is free. Keyed hashing (services/audit) covers the case
    # where someone drops the trigger first: they still cannot forge entries
    # without the audit key, which is not in the database.
    """CREATE OR REPLACE FUNCTION osint_audit_append_only() RETURNS trigger AS $$
       BEGIN
         RAISE EXCEPTION 'audit_log is append-only (attempted %)', TG_OP;
       END;
       $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log",
    """CREATE TRIGGER audit_log_append_only
       BEFORE UPDATE OR DELETE ON audit_log
       FOR EACH ROW EXECUTE FUNCTION osint_audit_append_only()""",
]


# The revision that represents "the schema as it was before alembic was
# wired up". A database that already has tables but no alembic_version row
# is stamped with this, so `alembic upgrade head` afterwards applies only
# what is genuinely new.
BASELINE_REVISION = "0001_baseline"


def _head_revision() -> str:
    """The newest revision in alembic/versions — what create_all() matches."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()


async def _stamp_baseline_if_needed(fresh: bool = False) -> None:
    """Give a pre-alembic database its version row, once.

    Doing this here rather than in entrypoint.sh keeps it in the same
    single-process step that already owns schema creation, so two uvicorn
    workers can't race on it.
    """
    async with engine.begin() as conn:
        exists = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
        if exists:
            return
        # A FRESH database was just created by create_all() from the current
        # models, i.e. it already has every column the later revisions add.
        # Stamping the baseline would make `alembic upgrade head` re-add them
        # and fail ("column … already exists") — which is exactly what a
        # first installation hit. Fresh → head; pre-alembic DB → baseline.
        rev = _head_revision() if fresh else BASELINE_REVISION
        log.info("no alembic_version table — stamping %s (%s)", rev, "fresh install" if fresh else "pre-alembic DB")
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        ))
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": rev},
        )


async def main() -> None:
    log.info("Bootstrapping ORM tables")
    async with engine.begin() as conn:
        fresh = not await conn.scalar(text("SELECT to_regclass('public.cases')"))
        await conn.run_sync(Base.metadata.create_all)
        for stmt in ADHOC_MIGRATIONS:
            log.info("apply migration: %s", stmt)
            await conn.execute(text(stmt))
    # Best-effort extras — each isolated so one failure can't roll back
    # the schema above or block boot.
    for stmt in BEST_EFFORT_MIGRATIONS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
            log.info("best-effort migration ok: %s", stmt[:60])
        except Exception as e:  # noqa: BLE001
            log.warning("best-effort migration skipped (%s): %s", e, stmt[:60])
    await _stamp_baseline_if_needed(fresh)
    await engine.dispose()
    log.info("Bootstrap done")


if __name__ == "__main__":
    asyncio.run(main())
