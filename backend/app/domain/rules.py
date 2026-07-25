"""Pure buy/sell decision rules (docs/ROADMAP.md §Buy/Sell — the strategy contract).

Both the backtester and (in R4) the live engine call these; neither contains strategy
logic of its own (ADR-0008). Functions take precomputed context and return a decision +
a machine-readable reason for the decision journal. No I/O, no clock, no DB.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.sizing import STOP_ATR_MULT, TRAIL_ATR_MULT
from app.domain.strategy import MIN_COMPOSITE, MIN_DATA_COMPLETENESS

# Portfolio limits.
MAX_POSITIONS = 20
MAX_ENTRIES_PER_DAY = 3
MAX_SECTOR_PCT = 0.25
EARNINGS_BLACKOUT_DAYS = 5

# Sell thresholds.
FUND_SCORE_DROP = 20.0
COMPOSITE_EXIT = 40.0
MIN_INTEREST_COVERAGE = 2.0
MOMENTUM_WEAK = 30.0
TREND_CONFIRM_DAYS = 2


@dataclass(frozen=True, slots=True)
class BuyContext:
    composite: float | None
    rank: int | None
    rank_threshold: int  # top-decile cutoff (inclusive)
    data_completeness: float
    price_above_50dma: bool
    fresh_breakout: bool  # breakout_strength > 0
    macd_bullish: bool  # macd_hist > 0
    days_to_earnings: int | None
    positions_held: int
    sector_weight: float  # current portfolio weight in this name's sector
    entries_today: int
    cash_available: float
    already_held: bool


def evaluate_buy(ctx: BuyContext) -> tuple[bool, str]:
    """All gates must pass. Returns (should_buy, reason) — reason is logged either way."""
    if ctx.already_held:
        return False, "already_held"
    if ctx.composite is None or ctx.composite < MIN_COMPOSITE:
        return False, "composite_below_min"
    if ctx.rank is None or ctx.rank > ctx.rank_threshold:
        return False, "not_top_decile"
    if ctx.data_completeness < MIN_DATA_COMPLETENESS:
        return False, "insufficient_data"
    if not ctx.price_above_50dma:
        return False, "below_50dma"
    if not (ctx.fresh_breakout or ctx.macd_bullish):
        return False, "no_technical_trigger"
    if ctx.days_to_earnings is not None and ctx.days_to_earnings <= EARNINGS_BLACKOUT_DAYS:
        return False, "earnings_proximity"
    if ctx.positions_held >= MAX_POSITIONS:
        return False, "max_positions"
    if ctx.sector_weight >= MAX_SECTOR_PCT:
        return False, "sector_cap"
    if ctx.entries_today >= MAX_ENTRIES_PER_DAY:
        return False, "daily_entry_cap"
    if ctx.cash_available <= 0:
        return False, "insufficient_cash"
    return True, "buy"


@dataclass(slots=True)
class PositionState:
    symbol: str
    entry_price: float
    shares: float
    atr_at_entry: float
    stop_price: float
    target_price: float
    entry_composite: float | None
    entry_fundamentals_score: float | None
    took_partial: bool = False
    highest_close: float = 0.0
    reversal_days: int = 0


@dataclass(frozen=True, slots=True)
class SellAction:
    fraction: float  # 0.0 hold, 0.5 trim, 1.0 exit
    reason: str
    exit_price: float
    new_stop: float
    new_highest_close: float
    reversal_days: int


def _trailing_stop(pos: PositionState, close: float) -> float:
    """Raise-only trailing stop: breakeven after +1R, then a chandelier (high - 3*ATR)."""
    initial_risk = STOP_ATR_MULT * pos.atr_at_entry
    stop = pos.stop_price
    highest = max(pos.highest_close, close)
    if close >= pos.entry_price + initial_risk:  # past +1R
        stop = max(stop, pos.entry_price)  # lock in breakeven
        stop = max(stop, highest - TRAIL_ATR_MULT * pos.atr_at_entry)  # chandelier
    return stop


def evaluate_sell(
    pos: PositionState,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    composite: float | None,
    fundamentals_score: float | None,
    momentum_score: float | None,
    interest_coverage: float | None,
    price_below_50dma: bool,
    macd_bearish: bool,
) -> SellAction:
    """Priority-ordered: stop → target → fundamentals → trend. First hit wins.

    Bar OHLC is the session being evaluated. A gap through the stop exits at the open."""
    highest = max(pos.highest_close, bar_close)

    # 1) Stop loss (raise-only trail already baked into pos.stop_price at prior close).
    if bar_low <= pos.stop_price:
        exit_price = min(bar_open, pos.stop_price) if bar_open < pos.stop_price else pos.stop_price
        reason = "stop_gap" if bar_open < pos.stop_price else "stop_loss"
        return SellAction(1.0, reason, exit_price, pos.stop_price, highest, 0)

    # 2) Target: trim half once, move stop to breakeven, let the rest trail.
    if not pos.took_partial and bar_high >= pos.target_price:
        return SellAction(0.5, "target_partial", pos.target_price,
                          max(pos.stop_price, pos.entry_price), highest, 0)

    # 3) Fundamentals deteriorated (evaluated on fresh nightly scores).
    dropped = (
        pos.entry_fundamentals_score is not None
        and fundamentals_score is not None
        and pos.entry_fundamentals_score - fundamentals_score > FUND_SCORE_DROP
    )
    weak_composite = composite is not None and composite < COMPOSITE_EXIT
    weak_coverage = interest_coverage is not None and interest_coverage < MIN_INTEREST_COVERAGE
    if dropped or weak_composite or weak_coverage:
        return SellAction(1.0, "fundamentals_deteriorated", bar_close, pos.stop_price, highest, 0)

    # 4) Trend reversal, confirmed over consecutive sessions.
    reversal_now = (
        price_below_50dma
        and macd_bearish
        and momentum_score is not None
        and momentum_score < MOMENTUM_WEAK
    )
    if reversal_now:
        days = pos.reversal_days + 1
        if days >= TREND_CONFIRM_DAYS:
            return SellAction(1.0, "trend_reversal", bar_close, pos.stop_price, highest, 0)
        return SellAction(0.0, "hold", bar_close, _trailing_stop(pos, bar_close), highest, days)

    # 5) Hold — advance the trailing stop, reset the reversal counter.
    return SellAction(0.0, "hold", bar_close, _trailing_stop(pos, bar_close), highest, 0)
