"""Event-driven daily backtester (ADR-0008).

Walks the trading calendar; on each session builds a DataWindow (data <= t), computes
signals, classifies the regime, fuses scores, then evaluates exits before entries — all
through the SAME pure functions the live engine will use. Execution is at the session's
raw close with the cost model applied; stops/targets fill at their trigger price. Marks
to market for the equity curve. Daily cadence is a simplification of the 30-min live loop
that keeps a multi-year run tractable; the decision logic is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import structlog

from app.backtest.cost_model import fill_price
from app.backtest.data_window import BacktestData, DataWindow
from app.backtest.portfolio import SimPortfolio, Trade
from app.domain.decision import SymbolCycleData, plan_cycle
from app.domain.regime import (
    build_features,
    classify_raw,
    confirmed_regime,
)
from app.domain.rules import PositionState
from app.domain.signals import compute_signals
from app.domain.stats import sma
from app.domain.strategy import StrategyCompany, fuse_scores

log = structlog.get_logger()

WARMUP_BARS = 200  # need 200 closes for the long MA / breadth


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    start: date
    end: date
    initial_cash: float = 100_000.0
    config_version: str = "2.0.0"


@dataclass(frozen=True, slots=True)
class EquityPoint:
    day: date
    equity: float
    cash: float
    regime: str
    positions: int


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    regime_days: dict[str, int] = field(default_factory=dict)


def run_backtest(data: BacktestData, config: BacktestConfig) -> BacktestResult:
    calendar = [d for d in data.trading_dates() if config.start <= d <= config.end]
    portfolio = SimPortfolio(cash=config.initial_cash)
    result = BacktestResult(config=config)

    prev_confirmed: str | None = None
    raw_history: list[str] = []
    symbols = list(data.series)

    for i, as_of in enumerate(calendar):
        if i < WARMUP_BARS:
            continue
        window = DataWindow(data, as_of)

        # --- signals + fusion --------------------------------------------------
        companies: list[StrategyCompany] = []
        signals_by_symbol: dict[str, dict[str, dict[str, float | None]]] = {}
        above_200 = below_200 = 0
        for sym in symbols:
            inputs = window.signal_inputs(sym)
            if inputs is None or len(inputs.closes) < WARMUP_BARS:
                continue
            sig = compute_signals(inputs)
            signals_by_symbol[sym] = sig
            companies.append(StrategyCompany(sym, inputs.sector, sig))
            ma200 = sma(inputs.closes, 200)
            if ma200 is not None:
                if inputs.closes[-1] > ma200:
                    above_200 += 1
                else:
                    below_200 += 1

        if not companies:
            continue
        breadth = above_200 / (above_200 + below_200) if (above_200 + below_200) else None

        # --- regime ------------------------------------------------------------
        features = build_features(
            window.vix_series(), window.t10y2y(), window.spy_closes(), breadth
        )
        today_raw, _, _ = classify_raw(features)
        raw_history.append(today_raw)
        regime = confirmed_regime(raw_history[-4:], prev_confirmed)
        prev_confirmed = regime
        result.regime_days[regime] = result.regime_days.get(regime, 0) + 1

        scores = {s.symbol: s for s in fuse_scores(companies, regime)}

        # Build the per-symbol cycle snapshot the pure planner consumes.
        cycle_data: dict[str, SymbolCycleData] = {}
        marks: dict[str, float] = {}
        for sym in {*signals_by_symbol, *portfolio.positions}:
            bar = window.bar(sym)
            score = scores.get(sym)
            if bar is None or score is None:
                continue
            marks[sym] = bar.close
            symsig = signals_by_symbol.get(sym)
            inputs = window.signal_inputs(sym)
            if symsig is None or inputs is None:
                continue
            atr_pct = symsig["technical"].get("atr_pct")
            cycle_data[sym] = SymbolCycleData(
                symbol=sym, sector=inputs.sector,
                bar_open=bar.open, bar_high=bar.high, bar_low=bar.low, bar_close=bar.close,
                closes=inputs.closes, signals=symsig, score=score,
                atr=(atr_pct * bar.close) if atr_pct and atr_pct > 0 else None,
            )

        equity = portfolio.equity(marks)
        sector_notional = _sector_notional(portfolio, data.sectors, marks)
        plan = plan_cycle(
            cycle_data, portfolio.positions, equity, portfolio.cash,
            sector_notional, entries_today=0, n_scored=len(companies),
        )
        _execute_plan(plan, portfolio, cycle_data, as_of)

        equity = portfolio.equity(marks)
        result.equity_curve.append(
            EquityPoint(as_of, equity, portfolio.cash, regime, len(portfolio.positions))
        )

    result.trades = portfolio.trades
    return result


def _sector_notional(
    portfolio: SimPortfolio, sectors: dict[str, str], marks: dict[str, float]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym, pos in portfolio.positions.items():
        sector = sectors.get(sym, "Unknown")
        out[sector] = out.get(sector, 0.0) + pos.shares * marks.get(sym, pos.entry_price)
    return out


def _execute_plan(plan, portfolio, cycle_data, as_of) -> None:  # type: ignore[no-untyped-def]
    # Exits first (frees cash), then entries — the plan is already in that order.
    for intent in plan.exits:
        d = cycle_data[intent.symbol]
        action = intent.action
        if action.fraction > 0:
            vr = d.signals.get("technical", {}).get("volume_spike")
            price = fill_price(action.exit_price, "sell", vr)
            portfolio.sell(intent.symbol, as_of, action.fraction, price, action.reason)
        if intent.symbol in portfolio.positions:
            held = portfolio.positions[intent.symbol]
            held.stop_price = action.new_stop
            held.highest_close = action.new_highest_close
            held.reversal_days = action.reversal_days

    for entry in plan.entries:
        d = cycle_data[entry.symbol]
        vr = d.signals.get("technical", {}).get("volume_spike")
        price = fill_price(entry.ref_price, "buy", vr)
        state = PositionState(
            symbol=entry.symbol, entry_price=price, shares=entry.shares, atr_at_entry=entry.atr,
            stop_price=entry.stop_price, target_price=entry.target_price,
            entry_composite=entry.entry_composite,
            entry_fundamentals_score=entry.entry_fundamentals_score,
            highest_close=entry.ref_price,
        )
        portfolio.buy(entry.symbol, as_of, entry.shares, price, state)

