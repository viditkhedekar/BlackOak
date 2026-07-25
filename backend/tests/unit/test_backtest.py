"""Backtester integrity: DataWindow no-lookahead, PIT fundamentals lag, determinism.

These are the R3 gate's correctness locks (ADR-0008). They use a synthetic BacktestData
so they are fast and fully deterministic — no DB, no network.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from app.backtest.cost_model import fill_price
from app.backtest.data_window import BacktestData, DataWindow, SymbolSeries
from app.backtest.engine import BacktestConfig, run_backtest
from app.domain.factors import FundamentalSnapshot


def _series(n: int, start_price: float = 100.0) -> SymbolSeries:
    d0 = date(2020, 1, 1)
    dates = [d0 + timedelta(days=i) for i in range(n)]
    closes = [start_price + i * 0.5 for i in range(n)]
    return SymbolSeries(
        dates=dates,
        opens=[c - 0.2 for c in closes],
        highs=[c + 0.5 for c in closes],
        lows=[c - 0.5 for c in closes],
        closes=closes,
        volumes=[1000.0] * n,
        raw_closes=closes,
    )


def _data(n: int = 300) -> BacktestData:
    s = _series(n)
    return BacktestData(
        sectors={"AAA": "Tech"},
        series={"AAA": s},
        spy_dates=s.dates,
        spy_closes=[100.0 + i * 0.25 for i in range(n)],
        vix_dates=s.dates,
        vix_values=[15.0] * n,
        t10y2y_dates=s.dates,
        t10y2y_values=[0.5] * n,
    )


def test_datawindow_hides_future_bars() -> None:
    data = _data(300)
    mid = data.series["AAA"].dates[150]
    window = DataWindow(data, mid)
    inputs = window.signal_inputs("AAA")
    assert inputs is not None
    # Only bars up to and including the as-of date are visible.
    assert len(inputs.closes) == 151
    assert inputs.closes[-1] == data.series["AAA"].closes[150]


def test_datawindow_fundamentals_pit_lag() -> None:
    data = _data(300)
    s = data.series["AAA"]
    fiscal = s.dates[100]
    s.fundamentals = [(fiscal, FundamentalSnapshot(fiscal_year=2020, revenue=1.0))]

    # 44 days after fiscal end: still withheld.
    w_early = DataWindow(data, fiscal + timedelta(days=44))
    assert w_early.signal_inputs("AAA").annual == []  # type: ignore[union-attr]
    # 45 days after: now visible.
    w_ok = DataWindow(data, fiscal + timedelta(days=45))
    assert len(w_ok.signal_inputs("AAA").annual) == 1  # type: ignore[union-attr]


def test_no_lookahead_mutating_future_leaves_decision_unchanged() -> None:
    """Mutating bars strictly AFTER the as-of date must not change the window at t."""
    data = _data(300)
    as_of = data.series["AAA"].dates[150]

    before = list(DataWindow(data, as_of).signal_inputs("AAA").closes)  # type: ignore[union-attr]
    # Corrupt every future bar.
    s = data.series["AAA"]
    for i in range(151, len(s.closes)):
        s.closes[i] = 9_999.0
        s.highs[i] = 9_999.0
    after = list(DataWindow(data, as_of).signal_inputs("AAA").closes)  # type: ignore[union-attr]
    assert before == after


def test_backtest_deterministic() -> None:
    data1 = _data(300)
    data2 = _data(300)
    config = BacktestConfig(
        start=date(2020, 1, 1), end=date(2020, 12, 31), initial_cash=100_000
    )
    r1 = run_backtest(data1, config)
    r2 = run_backtest(data2, config)
    assert [p.equity for p in r1.equity_curve] == [p.equity for p in r2.equity_curve]
    assert [(t.symbol, t.side, t.shares) for t in r1.trades] == [
        (t.symbol, t.side, t.shares) for t in r2.trades
    ]


def test_backtest_runs_and_conserves_value_roughly() -> None:
    # A single steadily-rising name: engine should run, and equity stay finite/positive.
    data = _data(300)
    config = BacktestConfig(
        start=date(2020, 1, 1), end=date(2020, 12, 31), initial_cash=100_000
    )
    result = run_backtest(data, config)
    assert result.equity_curve  # produced points past warmup
    assert all(p.equity > 0 for p in result.equity_curve)


def test_cost_model_pushes_against_trade() -> None:
    assert fill_price(100.0, "buy") > 100.0
    assert fill_price(100.0, "sell") < 100.0
    # A volume spike adds impact drag on top.
    assert fill_price(100.0, "buy", volume_ratio=3.0) > fill_price(100.0, "buy")
    assert math.isclose(fill_price(100.0, "buy") - 100.0, 100.0 * 7 / 10_000, rel_tol=1e-9)
