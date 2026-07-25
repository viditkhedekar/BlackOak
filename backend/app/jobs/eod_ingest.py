"""EOD price ingest job — the 16:30 ET nightly refresh (docs/ARCHITECTURE.md §12).

Fetches a short trailing window (to self-heal any missed session) for the full
universe and the benchmarks, but only on actual trading days.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.domain.calendar import is_trading_day
from app.services.benchmarks import ingest_benchmarks
from app.services.ingest import ingest_prices
from app.services.providers import get_market_data_provider
from app.services.scoring import score_universe_job

log = structlog.get_logger()

# Re-fetch a few sessions back so a skipped run heals itself on the next one.
LOOKBACK_DAYS = 5


async def run_eod_ingest() -> None:
    # The cron fires on weekdays; skip market holidays, which are still weekdays.
    target = datetime.now(UTC).date()
    if not is_trading_day(target):
        log.info("eod_ingest.skip_non_trading_day", day=str(target))
        return

    settings = get_settings()
    provider = get_market_data_provider(settings)
    start = target - timedelta(days=LOOKBACK_DAYS)

    factory = get_session_factory()
    async with factory() as session:
        await ingest_benchmarks(session, provider, start, target)
    async with factory() as session:
        report = await ingest_prices(
            session, provider, start, target, symbols=None, job_name="eod_ingest"
        )
    # Rescore the universe on the fresh prices (fundamentals refresh runs nightly at 02:00).
    async with factory() as session:
        rows = await score_universe_job(session)
    log.info(
        "eod_ingest.done",
        target=str(target),
        symbols=report.requested,
        bars=report.bars_written,
        failed=len(report.failed),
        scores=rows,
    )
