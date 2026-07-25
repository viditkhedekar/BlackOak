"""Intraday bar ingest: one batched provider call, then per-symbol validate → upsert.

Unlike the daily pipeline (one request per symbol), the intraday provider is batched
— a single call returns all 500+ symbols — so the fetch is one network round-trip and
the per-symbol isolation happens on the validate/write side. One bad symbol's bars never
abort the run; a run failing on more than FAILURE_ABORT_RATIO of symbols is marked failed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.db.repositories.intraday import IntradayRepository
from app.domain.market_data import validate_intraday_bars
from app.services.job_tracking import track_job
from app.services.ports import IntradayBarsProvider

log = structlog.get_logger()

FAILURE_ABORT_RATIO = 0.20
# Alpaca caps symbols per bars request; chunk the universe to stay under it.
FETCH_CHUNK = 200
# Which universes trade intraday: the S&P 500 plus SPY and the sector ETFs.
INTRADAY_UNIVERSES = ["SP500", "ETF"]


@dataclass
class IntradayReport:
    requested: int = 0
    succeeded: int = 0
    failed: list[str] = field(default_factory=list)
    bars_written: int = 0
    rows_rejected: int = 0

    @property
    def failure_ratio(self) -> float:
        return len(self.failed) / self.requested if self.requested else 0.0


async def ingest_intraday(
    session: AsyncSession,
    provider: IntradayBarsProvider,
    start: datetime,
    end: datetime,
    interval: str = "15Min",
    symbols: list[str] | None = None,
    job_name: str = "ingest_intraday",
) -> IntradayReport:
    async with track_job(session, job_name) as ctx:
        companies = CompanyRepository(session)
        intraday = IntradayRepository(session)

        if symbols is None:
            targets = await companies.active_symbols_in(INTRADAY_UNIVERSES)
        else:
            targets = []
            for sym in symbols:
                cid = await companies.get_id_by_symbol(sym)
                if cid is not None:
                    targets.append((cid, sym.upper()))

        id_by_symbol = {sym: cid for cid, sym in targets}
        report = IntradayReport(requested=len(targets))

        for i in range(0, len(targets), FETCH_CHUNK):
            chunk = [sym for _, sym in targets[i : i + FETCH_CHUNK]]
            try:
                fetched = await asyncio.to_thread(
                    provider.fetch_intraday_bars, chunk, start, end, interval
                )
            except Exception:
                # A whole-chunk transport failure counts every symbol in it as failed,
                # but other chunks still run — the batch boundary is the isolation unit.
                report.failed.extend(chunk)
                log.exception("intraday.chunk_failed", size=len(chunk))
                continue

            for symbol in chunk:
                try:
                    validated = validate_intraday_bars(symbol, fetched.get(symbol, []))
                    if validated.rejected:
                        report.rows_rejected += len(validated.rejected)
                    written = await intraday.upsert_bars(
                        id_by_symbol[symbol], validated.valid, source=provider.name,
                        interval=interval,
                    )
                    report.bars_written += written
                    report.succeeded += 1
                except Exception:
                    report.failed.append(symbol)
                    log.exception("intraday.symbol_failed", symbol=symbol)

        ctx.records_processed = report.bars_written
        ctx.meta = {
            "requested": report.requested,
            "succeeded": report.succeeded,
            "failed": report.failed,
            "bars_written": report.bars_written,
            "rows_rejected": report.rows_rejected,
            "provider": provider.name,
            "interval": interval,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

        if report.requested and report.failure_ratio > FAILURE_ABORT_RATIO:
            raise RuntimeError(
                f"intraday ingest failure ratio {report.failure_ratio:.0%} exceeds "
                f"{FAILURE_ABORT_RATIO:.0%} ({len(report.failed)}/{report.requested})"
            )
        return report
