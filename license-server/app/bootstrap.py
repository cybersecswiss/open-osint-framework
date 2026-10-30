"""Schema bootstrap before uvicorn forks workers."""
import asyncio
import logging

from sqlalchemy import text

from app.models import Base, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("license-server.bootstrap")

# Idempotent additive migrations for columns added after a table already
# exists (create_all never ALTERs an existing table). Safe to re-run.
ADHOC_MIGRATIONS = [
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS enabled_modules VARCHAR[]",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS contacts JSONB",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN DEFAULT FALSE",
    # Alert delivery. Added as one batch on purpose: this
    # service has no Alembic, so every boot replays the whole list, and a
    # column added on its own later is a second round-trip for nothing.
    # Encrypted at rest: the ciphertext no longer fits VARCHAR(128).
    "ALTER TABLE licenses ALTER COLUMN idp_backend_secret TYPE TEXT",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS notify_email_enabled BOOLEAN DEFAULT FALSE",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_host VARCHAR(255)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_port INTEGER DEFAULT 587",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_security VARCHAR(20) DEFAULT 'starttls'",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_username VARCHAR(255)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_password TEXT",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_from VARCHAR(255)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS smtp_verify_tls BOOLEAN DEFAULT TRUE",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS notify_webhook_enabled BOOLEAN DEFAULT FALSE",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(500)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS webhook_secret TEXT",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS notify_events VARCHAR[]",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS notify_last_ok_at TIMESTAMP",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS notify_last_error TEXT",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS notify_last_attempt_at TIMESTAMP",
    # Tenant defaults the tenant admin sets.
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS default_language VARCHAR(5)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS require_search_purpose BOOLEAN DEFAULT FALSE",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS default_playbook VARCHAR(50)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS report_classification VARCHAR(80)",
    "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS disabled_modules VARCHAR[]",
]


async def main() -> None:
    log.info("Bootstrapping license-server ORM tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in ADHOC_MIGRATIONS:
            await conn.execute(text(stmt))
    await engine.dispose()
    log.info("Bootstrap done")


if __name__ == "__main__":
    asyncio.run(main())
