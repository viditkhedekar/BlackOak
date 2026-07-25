"""Tests for pure sizing (sizing.py) and buy/sell rules (rules.py)."""

from __future__ import annotations

import math

from app.domain.rules import (
    MAX_POSITIONS,
    BuyContext,
    PositionState,
    evaluate_buy,
    evaluate_sell,
)
from app.domain.sizing import (
    MAX_POSITION_PCT,
    RISK_BUDGET_PCT,
    STOP_ATR_MULT,
    size_position,
)

# --- sizing ---------------------------------------------------------------

def test_size_risk_budget_binds_for_volatile_name() -> None:
    # High ATR → risk budget limits size below the 8% cap.
    s = size_position(equity=100_000, price=100, atr=5, cash_available=100_000)
    assert s is not None
    # risk_amount ≈ 0.75% of equity
    assert math.isclose(s.risk_amount, RISK_BUDGET_PCT * 100_000, rel_tol=1e-9)
    # stop is 2.5 ATR below entry
    assert math.isclose(s.stop_price, 100 - STOP_ATR_MULT * 5, rel_tol=1e-9)
    assert s.notional < MAX_POSITION_PCT * 100_000 + 1


def test_size_position_cap_binds_for_calm_name() -> None:
    # Tiny ATR → risk budget would allow a huge position, so the 8% cap binds.
    s = size_position(equity=100_000, price=100, atr=0.1, cash_available=100_000)
    assert s is not None
    assert math.isclose(s.notional, MAX_POSITION_PCT * 100_000, rel_tol=1e-6)


def test_size_none_when_dust_or_bad_inputs() -> None:
    assert size_position(equity=100_000, price=100, atr=5, cash_available=10) is None  # dust
    assert size_position(equity=0, price=100, atr=5, cash_available=100) is None
    assert size_position(equity=100_000, price=0, atr=5, cash_available=100) is None


# --- buy gate -------------------------------------------------------------

def _buy_ctx(**over: object) -> BuyContext:
    base = dict(
        composite=85.0, rank=3, rank_threshold=50, data_completeness=0.9,
        price_above_50dma=True, fresh_breakout=True, macd_bullish=False,
        days_to_earnings=30, positions_held=5, sector_weight=0.1, entries_today=0,
        cash_available=50_000, already_held=False,
    )
    base.update(over)
    return BuyContext(**base)  # type: ignore[arg-type]


def test_buy_passes_all_gates() -> None:
    ok, reason = evaluate_buy(_buy_ctx())
    assert ok and reason == "buy"


def test_buy_rejections() -> None:
    assert evaluate_buy(_buy_ctx(composite=65))[1] == "composite_below_min"
    assert evaluate_buy(_buy_ctx(rank=80))[1] == "not_top_decile"
    assert evaluate_buy(_buy_ctx(data_completeness=0.5))[1] == "insufficient_data"
    assert evaluate_buy(_buy_ctx(price_above_50dma=False))[1] == "below_50dma"
    assert evaluate_buy(_buy_ctx(fresh_breakout=False, macd_bullish=False))[1] == (
        "no_technical_trigger"
    )
    assert evaluate_buy(_buy_ctx(days_to_earnings=3))[1] == "earnings_proximity"
    assert evaluate_buy(_buy_ctx(positions_held=MAX_POSITIONS))[1] == "max_positions"
    assert evaluate_buy(_buy_ctx(sector_weight=0.30))[1] == "sector_cap"
    assert evaluate_buy(_buy_ctx(entries_today=3))[1] == "daily_entry_cap"
    assert evaluate_buy(_buy_ctx(already_held=True))[1] == "already_held"


# --- sell rules -----------------------------------------------------------

def _pos(**over: object) -> PositionState:
    base = dict(
        symbol="X", entry_price=100.0, shares=10.0, atr_at_entry=4.0,
        stop_price=90.0, target_price=112.0, entry_composite=80.0,
        entry_fundamentals_score=70.0, took_partial=False, highest_close=100.0,
        reversal_days=0,
    )
    base.update(over)
    return PositionState(**base)  # type: ignore[arg-type]


def _sell(pos: PositionState, o: float, h: float, low: float, c: float, **kw: object):
    base = dict(
        composite=75.0, fundamentals_score=68.0, momentum_score=60.0,
        interest_coverage=8.0, price_below_50dma=False, macd_bearish=False,
    )
    base.update(kw)
    return evaluate_sell(pos, o, h, low, c, **base)  # type: ignore[arg-type]


def test_sell_stop_hit() -> None:
    a = _sell(_pos(), o=95, h=96, low=89, c=91)  # low pierces 90 stop
    assert a.fraction == 1.0 and a.reason == "stop_loss"
    assert a.exit_price == 90.0


def test_sell_stop_gap_exits_at_open() -> None:
    a = _sell(_pos(), o=85, h=86, low=84, c=85)  # gaps below the stop
    assert a.reason == "stop_gap" and a.exit_price == 85.0


def test_sell_target_trims_half_and_moves_breakeven() -> None:
    a = _sell(_pos(), o=105, h=113, low=104, c=112)  # tags 112 target
    assert a.fraction == 0.5 and a.reason == "target_partial"
    assert a.new_stop == 100.0  # breakeven


def test_sell_fundamentals_deterioration() -> None:
    a = _sell(_pos(), o=101, h=102, low=99, c=100, fundamentals_score=40.0)  # drop > 20
    assert a.fraction == 1.0 and a.reason == "fundamentals_deteriorated"


def test_sell_trend_reversal_needs_two_days() -> None:
    kw = dict(price_below_50dma=True, macd_bearish=True, momentum_score=20.0)
    first = _sell(_pos(reversal_days=0), o=101, h=102, low=99, c=100, **kw)
    assert first.fraction == 0.0 and first.reversal_days == 1
    second = _sell(_pos(reversal_days=1), o=101, h=102, low=99, c=100, **kw)
    assert second.fraction == 1.0 and second.reason == "trend_reversal"


def test_hold_advances_trailing_stop() -> None:
    # Partial already taken (so the target rule is skipped) and no target tag this bar.
    # Close well past +1R (entry 100, risk 10 → +1R at 110); chandelier = high - 3*ATR.
    a = _sell(_pos(took_partial=True, highest_close=118), o=115, h=119, low=114, c=118)
    assert a.fraction == 0.0 and a.reason == "hold"
    assert a.new_stop >= 100.0  # at least breakeven
    assert a.new_stop == max(90.0, 100.0, 118 - 3 * 4.0)  # chandelier from highest close
