"""15-minute intraday bar poll (docs/ROADMAP.md R0).

Fires every 15 min during the trading day; fetches a short trailing window so a
skipped run self-heals on the next one. Skips non-trading days. This poll runs
independently of the 30-min decision cycle (R4) — bars are always fresh when the
engine wakes.

It also marks the equity curve. Portfolio value moves with the market, not only with
trades, so pinning the curve to the decision cycle left it at a handful of points a day
and blank whenever a cycle failed. A failed equity mark never fails the poll: bar
ingestion is what the engine depends on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.domain.calendar import is_trading_day
from app.services.intraday_ingest import ingest_intraday
from app.services.providers import get_broker, get_intraday_provider
from app.services.snapshots import POLL, record_live_snapshot

log = structlog.get_logger()

# Re-fetch the last ~2 hours so a missed poll heals itself; upserts dedupe the overlap.
LOOKBACK = timedelta(hours=2)


async def run_intraday_poll() -> None:
    now = datetime.now(UTC)
    if not is_trading_day(now.date()):
        log.info("intraday_poll.skip_non_trading_day", day=str(now.date()))
        return

    settings = get_settings()
    provider = get_intraday_provider(settings)

    factory = get_session_factory()
    async with factory() as session:
        report = await ingest_intraday(
            session, provider, now - LOOKBACK, now, interval="15Min", job_name="intraday_poll"
        )

    equity: float | None = None
    async with factory() as session:
        try:
            equity = await record_live_snapshot(session, get_broker(settings), now, POLL)
            await session.commit()
        except Exception:
            await session.rollback()
            log.warning("intraday_poll.snapshot_failed", exc_info=True)

    log.info(
        "intraday_poll.done",
        symbols=report.requested,
        bars=report.bars_written,
        failed=len(report.failed),
        equity=equity,
    )
