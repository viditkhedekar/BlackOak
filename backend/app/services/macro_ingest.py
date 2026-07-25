"""Macro-series ingest: FRED rate/curve/inflation series + VIX from yfinance.

Series are few and independent, so each is isolated in its own try/except and the run
records what it got. These feed the regime classifier in R2 (docs/ROADMAP.md).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.macro import MacroRepository
from app.domain.macro import MacroPoint
from app.services.job_tracking import track_job
from app.services.ports import MacroDataProvider


class VixProvider(Protocol):
    def fetch_vix(self, start: date, end: date) -> list[MacroPoint]: ...

log = structlog.get_logger()

# FRED series that carry the regime signal: fed funds rate, 10y-2y spread, CPI.
FRED_SERIES = ("FEDFUNDS", "T10Y2Y", "CPIAUCSL")


@dataclass
class MacroReport:
    series_written: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    @property
    def total_points(self) -> int:
        return sum(self.series_written.values())


async def ingest_macro(
    session: AsyncSession,
    fred: MacroDataProvider,
    vix_fetcher: VixProvider,
    start: date,
    end: date,
    job_name: str = "ingest_macro",
) -> MacroReport:
    async with track_job(session, job_name) as ctx:
        repo = MacroRepository(session)
        report = MacroReport()

        for series_id in FRED_SERIES:
            try:
                points = await asyncio.to_thread(fred.fetch_series, series_id, start, end)
                report.series_written[series_id] = await repo.upsert_points(points)
            except Exception:
                report.failed.append(series_id)
                log.exception("macro.series_failed", series=series_id)

        try:
            vix_points = await asyncio.to_thread(vix_fetcher.fetch_vix, start, end)
            report.series_written["VIX"] = await repo.upsert_points(vix_points)
        except Exception:
            report.failed.append("VIX")
            log.exception("macro.series_failed", series="VIX")

        ctx.records_processed = report.total_points
        ctx.meta = {"series_written": report.series_written, "failed": report.failed}
        return report
