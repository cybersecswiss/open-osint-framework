"""cases: template (offence-type playbook the case was opened with)

Revision ID: 0007_case_template
Revises: 0006_case_access
Create Date: 2026-09-29

Nullable: existing cases have none, and "no template" is a real state — most
cases do not start from a known offence type.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_case_template"
down_revision = "0006_case_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("template", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "template")
