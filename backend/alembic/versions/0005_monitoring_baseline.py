"""monitoring_configs: baseline_at

Revision ID: 0005_monitoring_baseline
Revises: 0004_case_phase
Create Date: 2026-08-30

The first run of a monitor establishes what is already there; it does not
alert on it.

Without this, a monitor created on a fresh case and run once produces
**hundreds or thousands of alerts** — one per entity and edge, i.e.
everything the search found. That is not
a monitoring result, it is the search result wearing a different hat, and
an inbox that receives it once learns to ignore the next one. A monitor
means "tell me what changes from here on".

Stored as a column rather than derived from "is there an earlier search
job for this case", because that derivation is fragile in exactly the way
that matters: purge an old job, or create the monitor on a case whose
history was cleaned, and the monitor silently re-baselines — it goes quiet
for one cycle and nobody can tell why. A column says plainly when the
baseline was taken.

NULL means "not baselined yet", which is the correct state for every
existing row: those monitors have never raised an alert (nothing ever
wrote one before this revision), so their next run is genuinely their first.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_monitoring_baseline"
down_revision = "0004_case_phase"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitoring_configs", sa.Column(
        "baseline_at", sa.DateTime(), nullable=True))
    op.add_column("monitoring_configs", sa.Column(
        "baseline_suppressed", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitoring_configs", "baseline_suppressed")
    op.drop_column("monitoring_configs", "baseline_at")
