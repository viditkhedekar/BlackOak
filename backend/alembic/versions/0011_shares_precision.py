"""widen shares/qty columns to 9dp to match Alpaca's fractional-share precision

Alpaca reports fractional-share quantities with up to 9 decimal places. positions.shares,
orders.qty, and executions.fill_qty were Numeric(18,6), so reconciling a broker quantity
like 28.156361547 rounded UP to 28.156362 on store. A later full-exit sell then requested
more than the broker actually held ("insufficient qty available for order") and the whole
decision cycle aborted mid-loop, leaving every position after the failed one unmanaged for
that cycle. Numeric(18,9) stores the broker's own precision exactly, so a full-exit sell
(shares * 1.0) can never exceed what reconciliation just read from the broker.

backtest_trades.shares is simulator output, not broker truth, and is untouched.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-16 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '0011'
down_revision: str | None = '0010'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_COLUMNS = [
    ('positions', 'shares'),
    ('orders', 'qty'),
    ('executions', 'fill_qty'),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Numeric(18, 9),
            existing_type=sa.Numeric(18, 6),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Numeric(18, 6),
            existing_type=sa.Numeric(18, 9),
            existing_nullable=False,
        )
