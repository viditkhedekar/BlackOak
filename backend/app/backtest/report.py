"""Backtest performance metrics — measured against SPY and equal-weight RSP.

Benchmarks are buy-and-hold over the identical date range. rf is 0 for simplicity (a
constant would shift Sharpe/Sortino uniformly). Cost drag is the modelled execution cost
as a fraction of starting equity — surfaced explicitly so results are never flattered.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from statistics import fmean

from app.backtest.cost_model import HALF_SPREAD_BPS, SLIPPAGE_BPS
from app.backtest.engine import BacktestResult
from app.domain.stats import (
    annualized_vol,
    beta,
    cagr,
    daily_returns,
    downside_deviation,
    max_drawdown,
)

_YEAR = 252


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    name: str
    total_return: float | None
    beta: float | None
    alpha_annual: float | None
    excess_return: float | None  # strategy total return minus benchmark's


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    start: date
    end: date
    trading_days: int
    final_equity: float
    total_return: float | None
    cagr: float | None
    volatility: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float | None
    trades: int
    win_rate: float | None
    profit_factor: float | None
    cost_drag: float
    regime_days: dict[str, int]
    benchmarks: list[BenchmarkComparison]

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d


def _sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    vol = annualized_vol(returns)
    if not vol:
        return None
    return fmean(returns) * _YEAR / vol


def _sortino(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    dd = downside_deviation(returns)
    if not dd:
        return None
    return fmean(returns) * _YEAR / dd


def _benchmark(
    name: str,
    strat_returns: list[float],
    strat_total: float | None,
    bench_closes: list[float],
) -> BenchmarkComparison:
    bench_returns = daily_returns(bench_closes)
    total = (
        bench_closes[-1] / bench_closes[0] - 1.0
        if len(bench_closes) >= 2 and bench_closes[0] > 0
        else None
    )
    b = beta(strat_returns, bench_returns)
    alpha = None
    if b is not None and bench_returns and strat_returns:
        n = min(len(strat_returns), len(bench_returns))
        alpha = (fmean(strat_returns[-n:]) - b * fmean(bench_returns[-n:])) * _YEAR
    excess = (
        strat_total - total if strat_total is not None and total is not None else None
    )
    return BenchmarkComparison(name, total, b, alpha, excess)


def build_metrics(
    result: BacktestResult,
    spy_closes_aligned: list[float],
    rsp_closes_aligned: list[float],
) -> BacktestMetrics:
    curve = result.equity_curve
    equities = [p.equity for p in curve]
    returns = daily_returns(equities)
    initial = result.config.initial_cash
    final = equities[-1] if equities else initial
    total_return = final / initial - 1.0 if initial > 0 else None
    years = len(curve) / _YEAR if curve else 0.0

    sells = [t for t in result.trades if t.side == "sell"]
    wins = [t for t in sells if t.realized_pnl > 0]
    gross_profit = sum(t.realized_pnl for t in wins)
    gross_loss = -sum(t.realized_pnl for t in sells if t.realized_pnl < 0)
    win_rate = len(wins) / len(sells) if sells else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    traded_notional = sum(t.shares * t.price for t in result.trades)
    cost_drag = (SLIPPAGE_BPS + HALF_SPREAD_BPS) / 10_000.0 * traded_notional / initial

    return BacktestMetrics(
        start=result.config.start,
        end=result.config.end,
        trading_days=len(curve),
        final_equity=round(final, 2),
        total_return=total_return,
        cagr=cagr(initial, final, years) if years > 0 else None,
        volatility=annualized_vol(returns),
        sharpe=_sharpe(returns),
        sortino=_sortino(returns),
        max_drawdown=max_drawdown(equities),
        trades=len(result.trades),
        win_rate=win_rate,
        profit_factor=profit_factor,
        cost_drag=round(cost_drag, 6),
        regime_days=result.regime_days,
        benchmarks=[
            _benchmark("SPY", returns, total_return, spy_closes_aligned),
            _benchmark("RSP", returns, total_return, rsp_closes_aligned),
        ],
    )
