"""portfolio_snapshots.source + nullable cycle-only columns

The equity curve now takes points from three places: the decision cycle (which knows the
regime and the post-trade book), the 15-minute intraday poll (which knows the broker's
account and positions but not a fresh regime), and a one-off backfill from the broker's own
portfolio history (which knows equity and nothing else). ``source`` records which, so the
dashboard can read the latest *live* row for cash/regime without a reconstructed point
shadowing it, and cash/positions/regime go nullable rather than being fabricated.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-15 10:05:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0010'
down_revision: str | None = '0009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every existing row came from a decision cycle; the default backfills them as such.
    op.add_column(
        'portfolio_snapshots',
        sa.Column(
            'source', sa.String(length=16), nullable=False, server_default='cycle'
        ),
    )
    op.alter_column('portfolio_snapshots', 'cash', nullable=True)
    op.alter_column('portfolio_snapshots', 'positions', nullable=True)
    op.alter_column('portfolio_snapshots', 'regime', nullable=True)


def downgrade() -> None:
    # A backfilled row has no cash/positions/regime to restore, so it cannot survive a
    # downgrade to NOT NULL columns.
    op.execute("DELETE FROM portfolio_snapshots WHERE source <> 'cycle'")
    op.execute("UPDATE portfolio_snapshots SET cash = 0 WHERE cash IS NULL")
    op.execute("UPDATE portfolio_snapshots SET positions = 0 WHERE positions IS NULL")
    op.execute("UPDATE portfolio_snapshots SET regime = 'unknown' WHERE regime IS NULL")
    op.alter_column('portfolio_snapshots', 'regime', nullable=False)
    op.alter_column('portfolio_snapshots', 'positions', nullable=False)
    op.alter_column('portfolio_snapshots', 'cash', nullable=False)
    op.drop_column('portfolio_snapshots', 'source')
