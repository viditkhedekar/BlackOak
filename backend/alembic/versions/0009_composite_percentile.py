"""strategy_scores.composite_percentile

The raw composite is a mean of percentiles and clusters near 50, so it cannot be compared
against an absolute 0-100 threshold. This column stores the composite ranked across the
universe, which is the unit the entry/exit gates use.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-26 11:20:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0009'
down_revision: str | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'strategy_scores',
        sa.Column('composite_percentile', sa.Numeric(precision=6, scale=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('strategy_scores', 'composite_percentile')
