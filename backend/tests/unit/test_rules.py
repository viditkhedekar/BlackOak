"""Tests for pure sizing (sizing.py) and buy/sell rules (rules.py)."""

from __future__ import annotations

import math

from app.domain.rules import (
    CANDIDATE_POOL_MAX_PCT,
    CANDIDATE_POOL_MULT,
    GATE_HARD,
    GATE_PORTFOLIO,
    GATE_SCORE,
    MAX_ENTRIES_PER_DAY,
    MAX_POSITIONS,
    BuyContext,
    PositionState,
    candidate_pool_size,
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
    # High ATR → the risk budget limits size below the max-position cap.
    s = size_position(equity=100_000, price=100, atr=10, cash_available=100_000)
    assert s is not None
    assert math.isclose(s.risk_amount, RISK_BUDGET_PCT * 100_000, rel_tol=1e-9)
    # stop is 2.5 ATR below entry
    assert math.isclose(s.stop_price, 100 - STOP_ATR_MULT * 10, rel_tol=1e-9)
    assert s.notional < MAX_POSITION_PCT * 100_000 + 1


def test_size_position_cap_binds_for_calm_name() -> None:
    # Tiny ATR → the risk budget would allow a huge position, so the position cap binds.
    s = size_position(equity=100_000, price=100, atr=0.1, cash_available=100_000)
    assert s is not None
    assert math.isclose(s.notional, MAX_POSITION_PCT * 100_000, rel_tol=1e-6)


def test_size_none_when_dust_or_bad_inputs() -> None:
    assert size_position(equity=100_000, price=100, atr=5, cash_available=10) is None  # dust
    assert size_position(equity=0, price=100, atr=5, cash_available=100) is None
    assert size_position(equity=100_000, price=0, atr=5, cash_available=100) is None


def test_sizing_leaves_room_for_a_full_book() -> None:
    """MAX_POSITION_PCT and MAX_POSITIONS must agree, or cash binds before the book fills.

    At the old 0.08 x 20 the book exhausted equity after ~12 names and every candidate
    after that skipped on insufficient_cash, so the stated position limit was fiction."""
    assert MAX_POSITION_PCT * MAX_POSITIONS >= 1.0, (
        f"{MAX_POSITIONS} positions at {MAX_POSITION_PCT:.1%} each cannot be funded"
    )


def test_a_full_book_is_actually_fundable() -> None:
    """Walk the sizing function down a book of typical names and confirm it fills."""
    equity, cash, funded = 100_000.0, 100_000.0, 0
    while funded < MAX_POSITIONS:
        s = size_position(equity=equity, price=100.0, atr=2.0, cash_available=cash)
        if s is None:
            break
        cash -= s.notional
        funded += 1
    assert funded == MAX_POSITIONS, f"cash ran out after {funded} positions"


def test_candidate_pool_scales_with_the_book_and_the_universe() -> None:
    # Large universe: the pool tracks the book (2x MAX_POSITIONS).
    assert candidate_pool_size(500) == math.ceil(CANDIDATE_POOL_MULT * MAX_POSITIONS)
    # Small universe: never let in more than a fraction of what was scored.
    assert candidate_pool_size(25) == math.floor(CANDIDATE_POOL_MAX_PCT * 25)
    # Degenerate inputs still admit at least one name.
    assert candidate_pool_size(0) == 1
    assert candidate_pool_size(1) == 1


# --- buy gate -------------------------------------------------------------

def _buy_ctx(**over: object) -> BuyContext:
    # composite is the raw mean-of-percentiles (clusters near 50); composite_percentile is
    # the gated unit. A raw 85 is unreachable in practice, which is why the old baseline
    # here never caught the calibration bug — see docs and test_strategy.py.
    base = dict(
        composite=61.0, composite_percentile=92.0, rank=3, rank_threshold=50,
        in_candidate_pool=True, sector_pool_full=False,
        data_completeness=0.9, weight_covered=1.0,
        price_above_50dma=True, fresh_breakout=True, macd_bullish=False,
        days_to_earnings=30, positions_held=5, sector_weight=0.1, entries_today=0,
        cash_available=50_000, already_held=False,
    )
    base.update(over)
    return BuyContext(**base)  # type: ignore[arg-type]


def test_buy_passes_all_gates() -> None:
    v = evaluate_buy(_buy_ctx())
    assert v.passed and v.reason == "buy"


def test_buy_rejections() -> None:
    cases = {
        "composite_below_min": _buy_ctx(composite_percentile=65),
        "outside_candidate_pool": _buy_ctx(rank=80, in_candidate_pool=False),
        "sector_pool_cap": _buy_ctx(sector_pool_full=True),
        "insufficient_data": _buy_ctx(data_completeness=0.2),
        "below_50dma": _buy_ctx(price_above_50dma=False),
        "no_technical_trigger": _buy_ctx(fresh_breakout=False, macd_bullish=False),
        "earnings_proximity": _buy_ctx(days_to_earnings=3),
        "max_positions": _buy_ctx(positions_held=MAX_POSITIONS),
        "sector_cap": _buy_ctx(sector_weight=0.30),
        "daily_entry_cap": _buy_ctx(entries_today=MAX_ENTRIES_PER_DAY),
        "already_held": _buy_ctx(already_held=True),
        "insufficient_cash": _buy_ctx(cash_available=0.0),
    }
    for expected, ctx in cases.items():
        v = evaluate_buy(ctx)
        assert not v.passed and v.reason == expected


def test_unscored_name_is_insufficient_data_not_below_min() -> None:
    """A name the engine could not score is missing data, not weakly scored.

    Reporting composite_below_min here blamed a threshold the name never reached, which
    is what made the journal read as one uniform failure."""
    assert evaluate_buy(_buy_ctx(composite=None, composite_percentile=None)).reason == (
        "insufficient_data"
    )


def test_scattered_missing_metrics_do_not_block_a_name() -> None:
    """Less brittle: gaps spread across families cost nothing, because each family still
    scores and the composite renormalizes over the survivors."""
    v = evaluate_buy(_buy_ctx(data_completeness=0.62, weight_covered=1.0))
    assert v.passed, v.reason


def test_name_missing_whole_families_is_held_out() -> None:
    """A bank with no valuation or fundamentals input is scored on price action alone.
    That is genuinely insufficient data however strong its momentum looks."""
    v = evaluate_buy(_buy_ctx(data_completeness=1.0, weight_covered=0.65))
    assert not v.passed and v.reason == "insufficient_data"
    assert v.detail["missing"] == "families"
    assert v.detail["weight_covered"] == 0.65


def test_every_rejection_is_classified_by_gate_kind() -> None:
    """The journal must say whether a hard rule vetoed the name or its score fell short."""
    expected_kind = {
        "composite_below_min": GATE_SCORE,
        "outside_candidate_pool": GATE_SCORE,
        "insufficient_data": GATE_HARD,
        "below_50dma": GATE_HARD,
        "no_technical_trigger": GATE_HARD,
        "earnings_proximity": GATE_HARD,
        "max_positions": GATE_PORTFOLIO,
        "sector_cap": GATE_PORTFOLIO,
        "daily_entry_cap": GATE_PORTFOLIO,
        "insufficient_cash": GATE_PORTFOLIO,
        "already_held": GATE_PORTFOLIO,
    }
    overrides: dict[str, dict[str, object]] = {
        "composite_below_min": {"composite_percentile": 65},
        "outside_candidate_pool": {"rank": 80},
        "insufficient_data": {"data_completeness": 0.2},
        "below_50dma": {"price_above_50dma": False},
        "no_technical_trigger": {"fresh_breakout": False, "macd_bullish": False},
        "earnings_proximity": {"days_to_earnings": 3},
        "max_positions": {"positions_held": MAX_POSITIONS},
        "sector_cap": {"sector_weight": 0.30},
        "daily_entry_cap": {"entries_today": MAX_ENTRIES_PER_DAY},
        "insufficient_cash": {"cash_available": 0.0},
        "already_held": {"already_held": True},
    }
    for reason, kind in expected_kind.items():
        v = evaluate_buy(_buy_ctx(**overrides[reason]))
        assert v.reason == reason
        assert v.gate_kind == kind, f"{reason} classified as {v.gate_kind}"


def test_rejection_detail_carries_the_deciding_numbers() -> None:
    v = evaluate_buy(_buy_ctx(composite_percentile=65))
    assert v.detail["composite_percentile"] == 65
    assert v.detail["min_composite_percentile"] == 70.0
    assert v.detail["shortfall"] == 5.0
    assert v.detail["rank"] == 3
    assert v.detail["rank_threshold"] == 50


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
        composite_percentile=75.0, fundamentals_score=68.0, momentum_score=60.0,
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


def test_sell_on_weak_composite_percentile() -> None:
    """COMPOSITE_EXIT is on the percentile scale, so a bottom-quartile name actually exits.

    On the raw composite scale the old threshold of 40 was a -1.7 sigma event that never
    fired, which is why positions only ever left via stops."""
    a = _sell(_pos(), o=101, h=102, low=99, c=100, composite_percentile=15.0)
    assert a.fraction == 1.0 and a.reason == "fundamentals_deteriorated"
    # A merely mediocre name is not an exit.
    b = _sell(_pos(), o=101, h=102, low=99, c=100, composite_percentile=45.0)
    assert b.fraction == 0.0 and b.reason == "hold"


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
