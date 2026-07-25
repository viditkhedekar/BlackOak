"""Scoring service — assemble DB inputs → compute factors → score → persist.

Runs the pure engine (domain/factors + domain/scoring) over the whole universe and
writes one research_scores row per company per risk profile, with the raw factor
values captured in `inputs` so every score is reproducible (docs/SCHEMA.md §7).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, PriceDaily
from app.db.repositories.benchmarks import BenchmarkRepository
from app.db.repositories.companies import CompanyRepository
from app.db.repositories.fundamentals import FundamentalsRepository
from app.db.repositories.prices import PriceRepository
from app.db.repositories.scores import ScoreRepository
from app.domain.factors import FactorInputs, FundamentalSnapshot, compute_factors
from app.domain.scoring import (
    ENGINE_VERSION,
    PROFILE_WEIGHTS,
    CompanyFactors,
    score_universe,
)
from app.domain.stats import daily_returns
from app.services.job_tracking import track_job

log = structlog.get_logger()

_FUND_FIELDS = (
    "revenue", "gross_profit", "ebitda", "net_income", "eps_diluted", "interest_expense",
    "total_assets", "current_assets", "current_liabilities", "total_debt", "cash",
    "equity", "shares_out", "operating_cf", "capex",
)


def _f(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _snapshot(row: object) -> FundamentalSnapshot:
    fiscal_date: date = row.fiscal_date  # type: ignore[attr-defined]
    return FundamentalSnapshot(
        fiscal_year=fiscal_date.year,
        **{field: _f(getattr(row, field)) for field in _FUND_FIELDS},
    )


async def _latest_price_date(session: AsyncSession) -> date | None:
    result = await session.execute(select(func.max(PriceDaily.date)))
    return result.scalar_one_or_none()


async def _benchmark_returns(session: AsyncSession) -> list[float]:
    benchmarks = BenchmarkRepository(session)
    spy_id = await benchmarks.get_id_by_symbol("SPY")
    if spy_id is None:
        return []
    series = await benchmarks.get_series(spy_id, None, None)
    return daily_returns([float(p.adj_close) for p in series])


async def score_universe_job(
    session: AsyncSession, job_name: str = "score_universe"
) -> int:
    """Compute and persist research scores for the whole active universe."""
    async with track_job(session, job_name) as ctx:
        as_of = await _latest_price_date(session)
        if as_of is None:
            log.warning("scoring.no_prices")
            ctx.meta = {"scored": 0, "reason": "no_prices"}
            return 0

        companies = CompanyRepository(session)
        prices = PriceRepository(session)
        fundamentals = FundamentalsRepository(session)
        scores_repo = ScoreRepository(session)

        market_returns = await _benchmark_returns(session)
        active = await companies.active_symbols()

        # Build factor inputs and compute raw factors for each company.
        company_factors: list[CompanyFactors] = []
        sectors: dict[str, str] = {}
        for company_id, symbol in active:
            company = await session.get(Company, company_id)
            sector = (company.sector if company and company.sector else "Unknown")
            sectors[symbol] = sector

            price_rows = await prices.get_series(company_id, None, None)
            closes = [float(p.adj_close) for p in price_rows]
            fund_rows = await fundamentals.get_annual(company_id)
            inputs = FactorInputs(
                symbol=symbol,
                sector=sector,
                prices=closes,
                current_price=closes[-1] if closes else None,
                market_returns=market_returns,
                annual=[_snapshot(r) for r in fund_rows],
            )
            company_factors.append(
                CompanyFactors(symbol=symbol, sector=sector, factors=compute_factors(inputs))
            )

        symbol_to_id = {sym: cid for cid, sym in active}
        rows: list[dict[str, object]] = []
        for profile in PROFILE_WEIGHTS:
            for cs in score_universe(company_factors, profile):
                rows.append(
                    {
                        "company_id": symbol_to_id[cs.symbol],
                        "as_of_date": as_of,
                        "profile": profile,
                        **{cat: cs.categories[cat] for cat in cs.categories},
                        "composite": cs.composite,
                        "data_completeness": cs.data_completeness,
                        "engine_version": ENGINE_VERSION,
                        "inputs": {
                            name: {"raw": d.raw, "score": d.score}
                            for name, d in cs.factor_details.items()
                        },
                    }
                )

        written = await scores_repo.upsert_scores(rows)
        ctx.records_processed = written
        ctx.meta = {
            "as_of": as_of.isoformat(),
            "companies": len(company_factors),
            "profiles": list(PROFILE_WEIGHTS),
            "rows": written,
            "engine_version": ENGINE_VERSION,
        }
        return written
