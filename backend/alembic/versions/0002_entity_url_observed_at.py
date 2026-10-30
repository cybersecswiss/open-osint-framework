"""entities: url + observed_at

Revision ID: 0002_entity_url_observed_at
Revises: 0001_baseline
Create Date: 2026-07-25

Two columns that used to fall off the framework→agent boundary.

`Finding.url` is set by ~55 places across the runners and was then dropped
by `graph_builder.build_graph()`, which only ever read entity_type, label,
data and confidence. For an investigator the source URL is the citation —
without it a hit is an assertion. Some runners compensated by writing the
URL into `data` as well, which is why some stored entities have one and
others do not.

`observed_at` is `Finding.found_at` — when the SOURCE said it. It is kept
separate from `found_at` (when we wrote the row) rather than overwriting it,
so the rows written before this revision keep their existing meaning instead
of silently changing it. For fast-moving sources — leak sites, Telegram,
pastes — `observed_at` is the evidentiary timestamp.

The matching columns on the customer agent live in
`data-agent/app/bootstrap.py` (that side has no alembic; its migrations are
idempotent ADD COLUMN IF NOT EXISTS statements applied on every boot).
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_entity_url_observed_at"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("url", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("observed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("entities", "observed_at")
    op.drop_column("entities", "url")
