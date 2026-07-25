"""Fundamentals ingest — per-symbol isolation, idempotent upsert, job_runs bracketing.

yfinance fundamentals are slow and informally rate-limited, so the worker runs this on
rotating nightly slices rather than the whole universe at once (docs/ARCHITECTURE.md §12).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.db.repositories.estimates import EstimatesRepository
from app.db.repositories.fundamentals import FundamentalsRepository
from app.services.job_tracking import track_job
from app.services.ports import FundamentalsProvider

log = structlog.get_logger()

FAILURE_ABORT_RATIO = 0.30  # fundamentals are flakier than prices; a looser gate.


@dataclass
class FundamentalsReport:
    requested: int = 0
    succeeded: int = 0
    failed: list[str] = field(default_factory=list)
    records_written: int = 0
    estimates_written: int = 0

    @property
    def failure_ratio(self) -> float:
        return len(self.failed) / self.requested if self.requested else 0.0


async def ingest_fundamentals(
    session: AsyncSession,
    provider: FundamentalsProvider,
    symbols: list[str] | None = None,
    job_name: str = "ingest_fundamentals",
) -> FundamentalsReport:
    async with track_job(session, job_name) as ctx:
        companies = CompanyRepository(session)
        fundamentals = FundamentalsRepository(session)
        estimates = EstimatesRepository(session)

        if symbols is None:
            targets = await companies.active_symbols()
        else:
            targets = []
            for sym in symbols:
                cid = await companies.get_id_by_symbol(sym)
                if cid is not None:
                    targets.append((cid, sym.upper()))

        report = FundamentalsReport(requested=len(targets))
        for company_id, symbol in targets:
            try:
                records = await asyncio.to_thread(
                    provider.fetch_annual_fundamentals, symbol
                )
                written = await fundamentals.upsert_records(
                    company_id, records, source=provider.name
                )
                report.records_written += written
                # Forward estimates share the fetch loop; a missing estimate is not a
                # symbol failure (it's the weakest data), so isolate it separately.
                try:
                    estimate = await asyncio.to_thread(provider.fetch_estimates, symbol)
                    if estimate is not None:
                        report.estimates_written += await estimates.upsert(
                            company_id, estimate, source=provider.name
                        )
                except Exception:
                    log.warning("estimates.symbol_failed", symbol=symbol, exc_info=True)
                report.succeeded += 1
            except Exception:
                report.failed.append(symbol)
                log.exception("fundamentals.symbol_failed", symbol=symbol)

        ctx.records_processed = report.records_written
        ctx.meta = {
            "requested": report.requested,
            "succeeded": report.succeeded,
            "failed": report.failed,
            "records_written": report.records_written,
            "estimates_written": report.estimates_written,
            "provider": provider.name,
        }
        if report.requested and report.failure_ratio > FAILURE_ABORT_RATIO:
            raise RuntimeError(
                f"fundamentals failure ratio {report.failure_ratio:.0%} exceeds "
                f"{FAILURE_ABORT_RATIO:.0%}"
            )
        return report
