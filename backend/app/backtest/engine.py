"""Event-driven daily backtester (ADR-0008).

Walks the trading calendar; on each session builds a DataWindow (data <= t), computes
signals, classifies the regime, fuses scores, then evaluates exits before entries — all
through the SAME pure functions the live engine will use. Execution is at the session's
raw close with the cost model applied; stops/targets fill at their trigger price. Marks
to market for the equity curve. Daily cadence is a simplification of the 30-min live loop
that keeps a multi-year run tractable; the decision logic is identical.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import structlog

from app.backtest.cost_model import fill_price
from app.backtest.data_window import BacktestData, DataWindow
from app.backtest.portfolio import SimPortfolio, Trade
from app.domain.regime import (
    build_features,
    classify_raw,
    confirmed_regime,
)
from app.domain.rules import (
    BuyContext,
    PositionState,
    evaluate_buy,
    evaluate_sell,
)
from app.domain.signals import compute_signals
from app.domain.sizing import size_position
from app.domain.stats import sma
from app.domain.strategy import TOP_DECILE, StrategyCompany, fuse_scores

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

        # Marks for equity / sector weights: this session's raw close.
        marks: dict[str, float] = {}
        for sym in list(portfolio.positions) + [c.symbol for c in companies]:
            bar = window.bar(sym)
            if bar is not None:
                marks[sym] = bar.close

        _evaluate_exits(window, portfolio, scores, signals_by_symbol, as_of)
        _evaluate_entries(
            window, portfolio, scores, signals_by_symbol, marks, data.sectors, as_of, len(companies)
        )

        equity = portfolio.equity(marks)
        result.equity_curve.append(
            EquityPoint(as_of, equity, portfolio.cash, regime, len(portfolio.positions))
        )

    result.trades = portfolio.trades
    return result


def _tech_flags(sig: dict[str, dict[str, float | None]], closes: list[float]) -> dict[str, object]:
    ma50 = sma(closes, 50)
    price = closes[-1]
    macd_hist = sig["technical"].get("macd_hist")
    breakout = sig["momentum"].get("breakout_strength")
    return {
        "price_above_50dma": ma50 is not None and price > ma50,
        "price_below_50dma": ma50 is not None and price < ma50,
        "macd_bullish": macd_hist is not None and macd_hist > 0,
        "macd_bearish": macd_hist is not None and macd_hist < 0,
        "fresh_breakout": breakout is not None and breakout > 0,
    }


def _evaluate_exits(window, portfolio, scores, signals_by_symbol, as_of) -> None:  # type: ignore[no-untyped-def]
    for sym in list(portfolio.positions):
        pos = portfolio.positions[sym]
        bar = window.bar(sym)
        if bar is None:
            continue
        sig = signals_by_symbol.get(sym)
        score = scores.get(sym)
        inputs = window.signal_inputs(sym)
        flags = _tech_flags(sig, inputs.closes) if sig and inputs else {}
        action = evaluate_sell(
            pos,
            bar_open=bar.open, bar_high=bar.high, bar_low=bar.low, bar_close=bar.close,
            composite=score.composite if score else None,
            fundamentals_score=score.families.get("fundamentals") if score else None,
            momentum_score=score.families.get("momentum") if score else None,
            interest_coverage=(sig or {}).get("fundamentals", {}).get("interest_coverage"),
            price_below_50dma=bool(flags.get("price_below_50dma")),
            macd_bearish=bool(flags.get("macd_bearish")),
        )
        if action.fraction > 0:
            vr = (sig or {}).get("technical", {}).get("volume_spike") if sig else None
            price = fill_price(action.exit_price, "sell", vr)
            portfolio.sell(sym, as_of, action.fraction, price, action.reason)
        # Persist updated trail state on holds/partials.
        if sym in portfolio.positions:
            held = portfolio.positions[sym]
            held.stop_price = action.new_stop
            held.highest_close = action.new_highest_close
            held.reversal_days = action.reversal_days


def _evaluate_entries(  # type: ignore[no-untyped-def]
    window, portfolio, scores, signals_by_symbol, marks, sectors, as_of, n_scored
) -> None:
    rank_threshold = max(1, math.ceil(TOP_DECILE * n_scored))
    entries_today = 0
    candidates = sorted(
        (s for s in scores.values() if s.composite is not None and s.rank is not None),
        key=lambda s: s.rank or 10**9,
    )
    for score in candidates:
        sym = score.symbol
        if sym in portfolio.positions:
            continue
        sig = signals_by_symbol.get(sym)
        inputs = window.signal_inputs(sym)
        bar = window.bar(sym)
        if sig is None or inputs is None or bar is None:
            continue
        flags = _tech_flags(sig, inputs.closes)
        equity = portfolio.equity(marks)
        ctx = BuyContext(
            composite=score.composite,
            rank=score.rank,
            rank_threshold=rank_threshold,
            data_completeness=score.data_completeness,
            price_above_50dma=bool(flags["price_above_50dma"]),
            fresh_breakout=bool(flags["fresh_breakout"]),
            macd_bullish=bool(flags["macd_bullish"]),
            days_to_earnings=None,
            positions_held=len(portfolio.positions),
            sector_weight=portfolio.sector_weight(
                sectors.get(sym, "Unknown"), sectors, marks
            ),
            entries_today=entries_today,
            cash_available=portfolio.cash,
            already_held=False,
        )
        ok, _reason = evaluate_buy(ctx)
        if not ok:
            continue
        atr_pct = sig["technical"].get("atr_pct")
        if atr_pct is None or atr_pct <= 0:
            continue
        atr = atr_pct * bar.close
        size = size_position(equity, bar.close, atr, portfolio.cash)
        if size is None:
            continue
        price = fill_price(bar.close, "buy", sig["technical"].get("volume_spike"))
        state = PositionState(
            symbol=sym, entry_price=price, shares=size.shares, atr_at_entry=atr,
            stop_price=size.stop_price, target_price=size.target_price,
            entry_composite=score.composite,
            entry_fundamentals_score=score.families.get("fundamentals"),
            highest_close=bar.close,
        )
        portfolio.buy(sym, as_of, size.shares, price, state)
        entries_today += 1
