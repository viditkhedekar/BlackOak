"""Unit tests for the five signal families: exact computations + missing-data handling."""

from __future__ import annotations

import math

from app.domain.factors import FundamentalSnapshot
from app.domain.signals import (
    SIGNAL_FAMILIES,
    EstimateValues,
    SignalInputs,
    compute_signals,
    data_completeness,
)


def _snap(year: int, **kw: float) -> FundamentalSnapshot:
    return FundamentalSnapshot(fiscal_year=year, **kw)


def _rising_series(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * i for i in range(n)]


def _full_inputs() -> SignalInputs:
    closes = _rising_series(260)
    return SignalInputs(
        symbol="TEST",
        sector="Information Technology",
        closes=closes,
        highs=[c + 1 for c in closes],
        lows=[c - 1 for c in closes],
        volumes=[1000.0] * 259 + [3000.0],
        opens=[c - 0.5 for c in closes],
        current_price=closes[-1],
        market_closes=_rising_series(260, step=0.5),
        annual=[
            _snap(2022, revenue=100, ebit=20, operating_income=18, net_income=15,
                  eps_diluted=1.0, gross_profit=40, equity=100, total_debt=50,
                  interest_expense=5, ebitda=25, shares_out=10, total_assets=200),
            _snap(2023, revenue=120, ebit=26, operating_income=24, net_income=18,
                  eps_diluted=1.3, gross_profit=52, equity=110, total_debt=48,
                  interest_expense=5, ebitda=30, shares_out=10, total_assets=210),
            _snap(2024, revenue=150, ebit=33, operating_income=30, net_income=22,
                  eps_diluted=1.7, gross_profit=66, equity=120, total_debt=45,
                  interest_expense=5, ebitda=38, shares_out=10, total_assets=220),
        ],
        estimates=EstimateValues(forward_pe=18.0, peg=1.5, forward_eps=2.0),
        days_to_earnings=12,
    )


def test_all_families_present_and_complete() -> None:
    signals = compute_signals(_full_inputs())
    assert set(signals) == set(SIGNAL_FAMILIES)
    # With full data every catalogued metric except the portfolio-aware correlation
    # (no holdings supplied) should be present.
    completeness = data_completeness(signals)
    assert completeness > 0.9


def test_valuation_math() -> None:
    signals = compute_signals(_full_inputs())
    val = signals["valuation"]
    # market_cap = price 359 * shares 10 = 3590; EV = 3590 + 45 - 0 (no cash) = 3635
    # ev/ebitda = 3635 / 38
    assert val["ev_ebitda"] is not None
    assert math.isclose(val["ev_ebitda"], 3635.0 / 38.0, rel_tol=1e-9)
    assert val["forward_pe"] == 18.0
    assert val["peg"] == 1.5
    # price/book = 3590 / 120
    assert math.isclose(val["price_to_book"], 3590.0 / 120.0, rel_tol=1e-9)


def test_fundamentals_math() -> None:
    f = compute_signals(_full_inputs())["fundamentals"]
    # revenue 3y span (2 steps): CAGR(100 -> 150 over 2y) = (1.5)**0.5 - 1
    assert math.isclose(f["revenue_growth_3y"], 1.5**0.5 - 1.0, rel_tol=1e-9)
    # latest gross margin = 66/150; operating margin = 30/150
    assert math.isclose(f["gross_margin"], 66.0 / 150.0, rel_tol=1e-9)
    assert math.isclose(f["operating_margin"], 30.0 / 150.0, rel_tol=1e-9)
    # roic = ebit 33 / (debt 45 + equity 120); roe = 22/120
    assert math.isclose(f["roic"], 33.0 / 165.0, rel_tol=1e-9)
    assert math.isclose(f["roe"], 22.0 / 120.0, rel_tol=1e-9)
    assert math.isclose(f["interest_coverage"], 33.0 / 5.0, rel_tol=1e-9)


def test_momentum_uptrend() -> None:
    m = compute_signals(_full_inputs())["momentum"]
    assert m["ma_stack"] == 3.0  # price above all three MAs in a steady rise
    assert m["pct_above_200dma"] is not None and m["pct_above_200dma"] > 0
    assert m["rs_vs_spy"] is not None  # stock rises faster than the 0.5-step market


def test_technical_volume_spike() -> None:
    t = compute_signals(_full_inputs())["technical"]
    # last volume 3000 over prior-20 avg 1000 → 3.0
    assert math.isclose(t["volume_spike"], 3.0, rel_tol=1e-9)
    assert t["rsi_14"] == 100.0  # monotonic rise
    assert t["sr_position"] is not None


def test_risk_family_and_missing_holdings() -> None:
    r = compute_signals(_full_inputs())["risk"]
    assert r["days_to_earnings"] == 12.0
    assert r["max_drawdown_1y"] is not None
    # No holdings supplied → correlation is None and renormalizes out.
    assert r["corr_to_holdings"] is None


def test_missing_fundamentals_renormalizes() -> None:
    closes = _rising_series(260)
    bare = SignalInputs(
        symbol="BARE", sector="Energy", closes=closes,
        highs=[c + 1 for c in closes], lows=[c - 1 for c in closes],
        volumes=[1000.0] * 260, opens=[c for c in closes], current_price=closes[-1],
        market_closes=_rising_series(260, step=0.5),
    )
    signals = compute_signals(bare)
    # No fundamentals/estimates → those families are all None, but price families fill in.
    assert all(v is None for v in signals["valuation"].values())
    assert all(v is None for v in signals["fundamentals"].values())
    assert signals["momentum"]["ma_stack"] == 3.0
    assert 0.0 < data_completeness(signals) < 0.6
