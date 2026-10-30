"""cases: restricted + members (need-to-know)

Revision ID: 0006_case_access
Revises: 0005_monitoring_baseline
Create Date: 2026-09-29

Until now every user of a tenant saw every case of that tenant. For an
investigating organisation that is often disqualifying: an internal investigation, a case against
a colleague, a protected witness.

`restricted = false` keeps today's behaviour for every existing case — the
migration changes nothing anyone can see. A restricted case is visible to its
creator, its assignee, its members and the tenant's admins
(`services/case_access.py`).

Members are usernames, the same identifier `created_by` and `assigned_to`
already hold. Metadata the operator already has in kind; no finding moves.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_case_access"
down_revision = "0005_monitoring_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column(
        "restricted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("cases", sa.Column(
        "members", postgresql.ARRAY(sa.String(length=100)), nullable=False,
        server_default=sa.text("'{}'::varchar[]")))


def downgrade() -> None:
    op.drop_column("cases", "members")
    op.drop_column("cases", "restricted")
