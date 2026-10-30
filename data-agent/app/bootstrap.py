"""Schema bootstrap before uvicorn forks workers."""
import asyncio
import logging

from sqlalchemy import text

from app.database import Base, engine
from app.models import AuditLog, Case, Edge, Entity, EntityAlias, Evidence  # noqa: F401  (registers tables)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("data-agent.bootstrap")

# Lightweight ad-hoc migrations. The agent doesn't carry alembic, so when a
# column is added we apply it here on every boot. ADD COLUMN IF NOT EXISTS
# is idempotent — safe to run on every container start.
ADHOC_MIGRATIONS: list[str] = [
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS is_relevant BOOLEAN",
    # Everything that used to fall off the framework→agent
    # boundary. Applied in ONE batch on purpose: each of these is a schema
    # change on a server the operator has no admin access to, so they are
    # expensive to ship one at a time.
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS url TEXT",
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS notes TEXT",
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS last_verified TIMESTAMP",
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS observed_at TIMESTAMP",
    "ALTER TABLE edges ADD COLUMN IF NOT EXISTS source VARCHAR(50)",
    "ALTER TABLE edges ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb",
    # Evaluability. `corroborated_by` records every
    # tool that independently reported the same node/edge; `admiralty` is the
    # NATO source-reliability + information-credibility pair derived from it.
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS corroborated_by TEXT[]",
    "ALTER TABLE entities ADD COLUMN IF NOT EXISTS admiralty VARCHAR(2)",
    "ALTER TABLE edges ADD COLUMN IF NOT EXISTS corroborated_by TEXT[]",
    # How the investigator ARRANGED the case map: node positions
    # and the groups they drew. This is their work, not a finding, and it
    # belongs in the case file for the same reason `notes` does: a colleague
    # opening the case must see the case as it was laid out, and the operator
    # must not be the one holding it.
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS layout JSONB NOT NULL DEFAULT '{}'::jsonb",
    # Which stage of the investigation this case is in. Mirrored
    # for the same reason as `status`: an organisation holding these cases without
    # the operator should see which were mid-collection and which were being
    # written up.
    "ALTER TABLE cases ADD COLUMN IF NOT EXISTS phase VARCHAR(20) NOT NULL DEFAULT 'new'",
    # The organisation's own activity log. Without it the data controller
    # has no record of who searched what; the only log would sit with the
    # operator, and there only as a fingerprint.
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS case_id UUID",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_case_id ON audit_log (case_id)",
    # Cross-case matches ("this selector is also in case X")
    # compare on type + case-folded label across all cases.
    "CREATE INDEX IF NOT EXISTS ix_entities_type_lower_label ON entities (entity_type, lower(label))",
]


async def main() -> None:
    log.info("Bootstrapping data agent ORM tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in ADHOC_MIGRATIONS:
            log.info("apply migration: %s", stmt)
            await conn.execute(text(stmt))
    await engine.dispose()
    log.info("Bootstrap done")


if __name__ == "__main__":
    asyncio.run(main())
