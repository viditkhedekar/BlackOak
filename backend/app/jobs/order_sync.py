"""Open-order status poll (docs/ARCHITECTURE.md §12).

Runs on the hour through the session, and once after the close to catch fills that landed
late in the day. Skips non-trading days.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.domain.calendar import is_trading_day
from app.services.order_sync import sync_open_orders
from app.services.providers import get_broker

log = structlog.get_logger()


async def run_order_sync() -> None:
    if not is_trading_day(datetime.now(UTC).date()):
        return

    broker = get_broker(get_settings())
    factory = get_session_factory()
    async with factory() as session:
        report = await sync_open_orders(session, broker)
        await session.commit()
    log.info(
        "order_sync_job.done",
        checked=report.checked,
        advanced=report.advanced,
        filled=report.filled,
    )
