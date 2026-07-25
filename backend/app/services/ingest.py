"""EOD price ingest: fetch → validate → upsert, with per-symbol failure isolation.

One bad ticker must never abort the run (docs/ARCHITECTURE.md §6). Every run is
bracketed in job_runs, and a run failing on more than FAILURE_ABORT_RATIO of its
symbols is marked failed so the pipeline alerting in Phase 7 can catch it.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.db.repositories.prices import PriceRepository
from app.domain.market_data import validate_bars
from app.services.job_tracking import track_job
from app.services.ports import MarketDataProvider

log = structlog.get_logger()

FAILURE_ABORT_RATIO = 0.20


@dataclass
class IngestReport:
    requested: int = 0
    succeeded: int = 0
    failed: list[str] = field(default_factory=list)
    bars_written: int = 0
    rows_rejected: int = 0
    rows_flagged: int = 0

    @property
    def failure_ratio(self) -> float:
        return len(self.failed) / self.requested if self.requested else 0.0


async def _ingest_symbol(
    provider: MarketDataProvider,
    prices: PriceRepository,
    company_id: uuid.UUID,
    symbol: str,
    start: date,
    end: date,
    report: IngestReport,
) -> None:
    # Provider clients are synchronous; keep the event loop free.
    raw = await asyncio.to_thread(provider.fetch_daily_bars, symbol, start, end)
    validated = validate_bars(symbol, raw)

    if validated.rejected:
        report.rows_rejected += len(validated.rejected)
        log.warning(
            "ingest.rows_rejected",
            symbol=symbol,
            count=len(validated.rejected),
            reasons=[r for _, r in validated.rejected[:5]],
        )
    if validated.flagged:
        report.rows_flagged += len(validated.flagged)
        log.warning(
            "ingest.rows_flagged",
            symbol=symbol,
            count=len(validated.flagged),
            samples=[r for _, r in validated.flagged[:5]],
        )

    written = await prices.upsert_bars(company_id, validated.valid, source=provider.name)
    report.bars_written += written
    report.succeeded += 1


async def ingest_prices(
    session: AsyncSession,
    provider: MarketDataProvider,
    start: date,
    end: date,
    symbols: list[str] | None = None,
    job_name: str = "ingest_prices",
) -> IngestReport:
    """Ingest daily bars for the given symbols (default: all active universe symbols)."""
    async with track_job(session, job_name) as ctx:
        companies = CompanyRepository(session)
        prices = PriceRepository(session)

        if symbols is None:
            targets = await companies.active_symbols()
        else:
            targets = []
            for sym in symbols:
                cid = await companies.get_id_by_symbol(sym)
                if cid is not None:
                    targets.append((cid, sym.upper()))

        report = IngestReport(requested=len(targets))
        for company_id, symbol in targets:
            try:
                await _ingest_symbol(
                    provider, prices, company_id, symbol, start, end, report
                )
            except Exception:
                report.failed.append(symbol)
                log.exception("ingest.symbol_failed", symbol=symbol)

        ctx.records_processed = report.bars_written
        ctx.meta = {
            "requested": report.requested,
            "succeeded": report.succeeded,
            "failed": report.failed,
            "bars_written": report.bars_written,
            "rows_rejected": report.rows_rejected,
            "rows_flagged": report.rows_flagged,
            "provider": provider.name,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

        if report.requested and report.failure_ratio > FAILURE_ABORT_RATIO:
            raise RuntimeError(
                f"ingest failure ratio {report.failure_ratio:.0%} exceeds "
                f"{FAILURE_ABORT_RATIO:.0%} ({len(report.failed)}/{report.requested} symbols)"
            )
        return report
