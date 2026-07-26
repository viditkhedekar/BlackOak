"""30-minute autonomous decision cycle (docs/ROADMAP.md R4; ADR-0007).

Fires every 30 min during regular trading hours. Reconciles, decides, journals, and
executes paper orders — fully hands-off. Skips non-trading days.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.domain.calendar import is_trading_day
from app.services.decision_engine import run_decision_cycle
from app.services.providers import get_broker

log = structlog.get_logger()


async def run_intraday_cycle() -> None:
    if not is_trading_day(datetime.now(UTC).date()):
        return

    settings = get_settings()
    broker = get_broker(settings)
    factory = get_session_factory()
    async with factory() as session:
        report = await run_decision_cycle(session, broker)
    log.info(
        "intraday_cycle.done",
        cycle_id=str(report.cycle_id),
        regime=report.regime,
        buys=report.buys,
        sells=report.sells,
        holds=report.holds,
        skips=report.skips,
        halted=report.halted,
    )
