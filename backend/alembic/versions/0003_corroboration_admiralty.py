"""entities/edges: corroborated_by + admiralty

Revision ID: 0003_corroboration_admiralty
Revises: 0002_entity_url_observed_at
Create Date: 2026-07-25

Two columns that turn "we collected thousands of things" into something an analyst
can rank.

`corroborated_by` — every tool that independently reported the same entity
(or the same relation). Dedup in `graph_builder` keyed on canonical identity,
so the first finding won and every later one was silently discarded by
`ON CONFLICT DO NOTHING`. That threw away the single most valuable signal in
the whole system: three unrelated sources returning the same address is a far
stronger statement than one source returning it, and there was no way to see
it.

`admiralty` — the NATO source-reliability / information-credibility pair,
e.g. "B2". A single float confidence was never comparable across tools (0.8
from Sherlock is an HTTP 200 on a profile page; 0.8 from LeakCheck is a hit in
a verified breach). Source reliability is declared per tool in the module
manifests; information credibility is derived per finding from corroboration
and confidence. See `modules/base/schemas.py` for the scale and
`backend/app/services/graph_builder.py` for the derivation.

A stored array rather than a JSON key inside `data`: merging two lists on
conflict is a one-line `array(select distinct unnest(...))` on a real column
and JSON surgery otherwise, and "how many independent sources say this" is a
first-class property of a finding, not metadata.

Matching agent columns live in `data-agent/app/bootstrap.py` (that side has
no alembic by design).
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_corroboration_admiralty"
down_revision = "0002_entity_url_observed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("corroborated_by", sa.ARRAY(sa.String()), nullable=True))
    op.add_column("entities", sa.Column("admiralty", sa.String(length=2), nullable=True))
    op.add_column("edges", sa.Column("corroborated_by", sa.ARRAY(sa.String()), nullable=True))


def downgrade() -> None:
    op.drop_column("edges", "corroborated_by")
    op.drop_column("entities", "admiralty")
    op.drop_column("entities", "corroborated_by")
