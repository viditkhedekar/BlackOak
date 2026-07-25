"""Load a BacktestData snapshot from the DB (the I/O boundary for the pure engine).

Pulls daily bars, fundamentals (with fiscal dates for the PIT lag), SPY/RSP closes, and
the VIX / yield-curve macro series. Fundamentals keep their fiscal_date so the DataWindow
can withhold them until 45 days after period end.
"""

from __future__ import annotations

from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest.data_window import BacktestData, SymbolSeries
from app.db.repositories.companies import CompanyRepository
from app.db.repositories.fundamentals import FundamentalsRepository
from app.db.repositories.macro import MacroRepository
from app.db.repositories.prices import PriceRepository
from app.domain.factors import FundamentalSnapshot

log = structlog.get_logger()


def _f(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


async def load_backtest_data(session: AsyncSession, universe: str = "SP500") -> BacktestData:
    companies = CompanyRepository(session)
    prices = PriceRepository(session)
    funds_repo = FundamentalsRepository(session)
    macro = MacroRepository(session)

    sectors: dict[str, str] = {}
    series: dict[str, SymbolSeries] = {}

    for company_id, symbol in await companies.active_symbols(universe):
        px = await prices.get_series(company_id, None, None)
        if not px:
            continue
        company = await companies.get_by_symbol(symbol)
        sectors[symbol] = (company.sector if company else None) or "Unknown"

        funds = await funds_repo.get_annual(company_id)
        fundamentals = [
            (
                f.fiscal_date,
                FundamentalSnapshot(
                    fiscal_year=f.fiscal_date.year,
                    revenue=_f(f.revenue), gross_profit=_f(f.gross_profit),
                    ebitda=_f(f.ebitda), ebit=_f(f.ebit),
                    operating_income=_f(f.operating_income), net_income=_f(f.net_income),
                    eps_diluted=_f(f.eps_diluted), interest_expense=_f(f.interest_expense),
                    total_assets=_f(f.total_assets), current_assets=_f(f.current_assets),
                    current_liabilities=_f(f.current_liabilities), total_debt=_f(f.total_debt),
                    cash=_f(f.cash), equity=_f(f.equity), shares_out=_f(f.shares_out),
                    operating_cf=_f(f.operating_cf), capex=_f(f.capex),
                ),
            )
            for f in funds
        ]
        series[symbol] = SymbolSeries(
            dates=[p.date for p in px],
            opens=[float(p.open) for p in px],
            highs=[float(p.high) for p in px],
            lows=[float(p.low) for p in px],
            closes=[float(p.adj_close) for p in px],
            volumes=[float(p.volume) for p in px],
            raw_closes=[float(p.close) for p in px],
            fundamentals=fundamentals,
        )

    async def _etf_closes(symbol: str) -> tuple[list[date], list[float]]:
        cid = await companies.get_id_by_symbol(symbol)
        if cid is None:
            return [], []
        rows = await prices.get_series(cid, None, None)
        return [r.date for r in rows], [float(r.adj_close) for r in rows]

    spy_dates, spy_closes = await _etf_closes("SPY")
    vix = await macro.get_series("VIX")
    t10y2y = await macro.get_series("T10Y2Y")

    log.info(
        "backtest.loaded",
        symbols=len(series),
        spy_bars=len(spy_closes),
        vix_points=len(vix),
    )
    return BacktestData(
        sectors=sectors,
        series=series,
        spy_dates=spy_dates,
        spy_closes=spy_closes,
        vix_dates=[p.date for p in vix],
        vix_values=[float(p.value) for p in vix],
        t10y2y_dates=[p.date for p in t10y2y],
        t10y2y_values=[float(p.value) for p in t10y2y],
    )
