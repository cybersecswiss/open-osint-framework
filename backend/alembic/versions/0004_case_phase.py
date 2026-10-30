"""cases: phase

Revision ID: 0004_case_phase
Revises: 0003_corroboration_admiralty
Create Date: 2026-07-27

Where the investigator is in their work: new → collecting → analysing →
reporting. Orientation, not a gate.

Separate from `status` on purpose. `status` answers "is this case still
ours" (open/closed) and is an administrative fact; `phase` answers "what am
I doing right now" and is a note about the work. Folding the two together
would have meant either an administrative field that moves for workflow
reasons, or a workflow field that cannot be used because closing a case
resets it.

Server-side default 'new' so every existing case is valid the moment the
column exists — a nullable phase would mean "unknown", and there is no such
state: a case that was never touched is simply new.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_case_phase"
down_revision = "0003_corroboration_admiralty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column(
        "phase", sa.String(length=20), nullable=False, server_default="new"))


def downgrade() -> None:
    op.drop_column("cases", "phase")
