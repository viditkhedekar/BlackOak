"""Nightly 02:00 ET maintenance (docs/ARCHITECTURE.md §12).

Refreshes a rotating slice of fundamentals (yfinance is slow/rate-limited, so the full
universe is covered over several nights) and then rescores. Runs every day — fundamentals
don't move on weekends, but rotating coverage costs nothing to keep going.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from app.core.config import get_settings
from app.db.repositories.intraday import IntradayRepository
from app.db.session import get_session_factory
from app.services.fundamentals_ingest import ingest_fundamentals
from app.services.providers import get_fundamentals_provider
from app.services.scoring import score_universe_job

log = structlog.get_logger()

# Keep ~120 days of intraday bars — enough for the longest intraday indicator window
# with headroom; older history lives in prices_daily.
INTRADAY_RETENTION = timedelta(days=120)


async def run_nightly() -> None:
    settings = get_settings()
    provider = get_fundamentals_provider(settings)
    factory = get_session_factory()

    async with factory() as session:
        fund = await ingest_fundamentals(session, provider)
    async with factory() as session:
        rows = await score_universe_job(session)
    async with factory() as session:
        cutoff = datetime.now(UTC) - INTRADAY_RETENTION
        pruned = await IntradayRepository(session).prune_before(cutoff)
        await session.commit()

    log.info(
        "nightly.done",
        fundamentals_written=fund.records_written,
        fundamentals_failed=len(fund.failed),
        scores=rows,
        intraday_pruned=pruned,
    )
