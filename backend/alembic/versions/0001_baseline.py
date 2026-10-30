"""baseline — schema as of 2026-07-25

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-25

This revision is deliberately a NO-OP.

Until now the backend had no migration path at all: `app/bootstrap.py` ran
`Base.metadata.create_all` plus a hand-maintained list of
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` statements, and docs/operations.en.md told
whoever changed a model to go run raw SQL in psql. That works exactly once
per developer and not at all across customer installations.

Rather than reverse-engineer the existing schema into a revision (which
would risk diverging from what is actually deployed), this marks the
current state as the starting point:

  * fresh install  → bootstrap creates the tables, then stamps this id
  * existing DB    → bootstrap stamps this id without touching anything

From here on, every schema change is a new revision:

    docker compose exec -T api alembic revision -m "add xyz"
    # edit the generated file, then
    bash scripts/rebuild.sh api        # entrypoint runs `alembic upgrade head`

The `ADHOC_MIGRATIONS` list in bootstrap.py stays for now because existing
deployments rely on it being idempotent on every boot; new columns belong
in a revision, not in that list.
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
