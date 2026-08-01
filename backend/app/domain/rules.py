"""Pure buy/sell decision rules (docs/ROADMAP.md §Buy/Sell — the strategy contract).

Both the backtester and (in R4) the live engine call these; neither contains strategy
logic of its own (ADR-0008). Functions take precomputed context and return a decision +
a machine-readable reason for the decision journal. No I/O, no clock, no DB.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.domain.sizing import STOP_ATR_MULT, TRAIL_ATR_MULT
from app.domain.strategy import (
    MIN_COMPOSITE_PERCENTILE,
    MIN_DATA_COMPLETENESS,
    MIN_WEIGHT_COVERAGE,
)

# Portfolio limits. MAX_POSITIONS is only reachable if sizing leaves room for it — see
# MAX_POSITION_PCT in sizing.py, which must be <= 1 / MAX_POSITIONS or cash binds first.
MAX_POSITIONS = 40
MAX_ENTRIES_PER_DAY = 8
MAX_SECTOR_PCT = 0.25
EARNINGS_BLACKOUT_DAYS = 5

# How many top-ranked names are eligible to buy each cycle. Scaled to the book rather
# than fixed at a decile: a pool barely larger than the position limit makes the strategy
# churn as ranks wobble around the cutoff, so aim for a multiple of MAX_POSITIONS while
# never letting more than a fraction of the universe in.
CANDIDATE_POOL_MULT = 2.0
CANDIDATE_POOL_MAX_PCT = 0.20

# No sector may take more than this share of the candidate pool. MAX_SECTOR_PCT caps the
# *portfolio*, but by then the damage is done: the pool it draws from was itself skewed.
# Measured before this cap, Financials held 31% of the top 80 against 15% of the universe
# (2.07x) while Information Technology held 1 of 80 against 15% (0.08x) — a sector bet
# the strategy never intended to place.
MAX_SECTOR_POOL_PCT = 0.20

# Sell thresholds. COMPOSITE_EXIT is on the composite *percentile* scale (bottom quartile
# of the cross-section), matching the entry gate. It previously read 40 on the raw
# composite scale, which is a -1.7 sigma event and so effectively never fired.
FUND_SCORE_DROP = 20.0
COMPOSITE_EXIT = 25.0
MIN_INTEREST_COVERAGE = 2.0
MOMENTUM_WEAK = 30.0
TREND_CONFIRM_DAYS = 2

# Why a name was rejected — the journal separates "the score wasn't good enough" from
# "a rule vetoed it" from "the book had no room", because those need different responses.
GATE_SCORE = "score_threshold"
GATE_HARD = "hard_rule"
GATE_PORTFOLIO = "portfolio_limit"

GATE_KIND_BY_REASON: dict[str, str] = {
    "composite_below_min": GATE_SCORE,
    "outside_candidate_pool": GATE_SCORE,
    "insufficient_data": GATE_HARD,
    "below_50dma": GATE_HARD,
    "no_technical_trigger": GATE_HARD,
    "earnings_proximity": GATE_HARD,
    "no_atr": GATE_HARD,
    "sector_pool_cap": GATE_PORTFOLIO,
    "already_held": GATE_PORTFOLIO,
    "max_positions": GATE_PORTFOLIO,
    "sector_cap": GATE_PORTFOLIO,
    "daily_entry_cap": GATE_PORTFOLIO,
    "insufficient_cash": GATE_PORTFOLIO,
    "size_too_small": GATE_PORTFOLIO,
}


def sector_pool_cap(pool_size: int) -> int:
    """Max names one sector may contribute to the candidate pool (at least 1)."""
    return max(1, math.floor(MAX_SECTOR_POOL_PCT * pool_size))


def build_candidate_pool(
    ranked: list[tuple[str, str]], pool_size: int
) -> tuple[set[str], set[str]]:
    """Sector-capped top-N. ``ranked`` is [(symbol, sector)] best-ranked first.

    Two passes. The first walks in rank order admitting names until the pool is full,
    skipping any whose sector already holds its cap, so a crowded sector yields its
    surplus slots to the next-best name elsewhere instead of colonising the pool.

    The second pass matters just as much: if the cap left the pool short — few sectors
    represented, or a genuinely narrow market — the remaining slots are refilled in rank
    order *ignoring* the cap. Diversification is a preference between comparable
    candidates, not a reason to shrink the opportunity set; a hard cap would quietly
    reintroduce the over-filtering this pool is meant to avoid.

    Returns (pool, capped_out). ``capped_out`` are names a sector cap displaced and the
    top-up did not rescue, which the journal reports differently from ranking too low.
    """
    cap = sector_pool_cap(pool_size)
    pool: list[str] = []
    deferred: list[str] = []
    per_sector: dict[str, int] = {}
    for symbol, sector in ranked:
        if len(pool) >= pool_size:
            break
        if per_sector.get(sector, 0) >= cap:
            deferred.append(symbol)
            continue
        pool.append(symbol)
        per_sector[sector] = per_sector.get(sector, 0) + 1

    # Top up from the deferred names (still in rank order), then from anything left.
    if len(pool) < pool_size:
        seen = set(pool)
        for symbol in [*deferred, *(s for s, _ in ranked)]:
            if len(pool) >= pool_size:
                break
            if symbol not in seen:
                pool.append(symbol)
                seen.add(symbol)

    return set(pool), {s for s in deferred if s not in pool}


def candidate_pool_size(n_scored: int) -> int:
    """How many top-ranked names may be considered for entry this cycle (inclusive)."""
    if n_scored <= 0:
        return 1
    by_book = math.ceil(CANDIDATE_POOL_MULT * MAX_POSITIONS)
    by_universe = math.floor(CANDIDATE_POOL_MAX_PCT * n_scored)
    return max(1, min(by_book, by_universe))


@dataclass(frozen=True, slots=True)
class BuyContext:
    composite: float | None  # raw weighted mean of family percentiles (journal only)
    composite_percentile: float | None  # the gated unit — see domain/strategy.py
    rank: int | None
    rank_threshold: int  # top-decile cutoff (inclusive)
    in_candidate_pool: bool  # survived the sector-capped top-N selection
    sector_pool_full: bool  # excluded because its sector already filled its pool quota
    data_completeness: float
    weight_covered: float  # regime weight of the families that actually scored
    price_above_50dma: bool
    fresh_breakout: bool  # breakout_strength > 0
    macd_bullish: bool  # macd_hist > 0
    days_to_earnings: int | None
    positions_held: int
    sector_weight: float  # current portfolio weight in this name's sector
    entries_today: int
    cash_available: float
    already_held: bool


@dataclass(frozen=True, slots=True)
class BuyEvaluation:
    """The verdict plus everything the decision journal needs to explain it."""

    passed: bool
    reason: str
    gate_kind: str
    detail: dict[str, Any] = field(default_factory=dict)


def evaluate_buy(ctx: BuyContext) -> BuyEvaluation:
    """All gates must pass. The reason is journaled either way."""
    detail: dict[str, Any] = {
        "composite": ctx.composite,
        "composite_percentile": ctx.composite_percentile,
        "min_composite_percentile": MIN_COMPOSITE_PERCENTILE,
        "rank": ctx.rank,
        "rank_threshold": ctx.rank_threshold,
        "data_completeness": round(ctx.data_completeness, 4),
        "min_data_completeness": MIN_DATA_COMPLETENESS,
        "weight_covered": round(ctx.weight_covered, 4),
        "min_weight_coverage": MIN_WEIGHT_COVERAGE,
    }

    def reject(reason: str, **extra: Any) -> BuyEvaluation:
        return BuyEvaluation(
            passed=False,
            reason=reason,
            gate_kind=GATE_KIND_BY_REASON[reason],
            detail={**detail, **extra},
        )

    if ctx.already_held:
        return reject("already_held")
    # A name the engine could not score at all is missing data, not weakly scored — say
    # so rather than blaming the composite threshold it never reached.
    if ctx.composite is None or ctx.composite_percentile is None:
        return reject("insufficient_data", missing="unscored")
    # Too much of the strategy's weight went unevaluated — e.g. a bank with no valuation
    # or fundamentals input at all, scored on price action alone.
    if ctx.weight_covered < MIN_WEIGHT_COVERAGE:
        return reject("insufficient_data", missing="families")
    if ctx.data_completeness < MIN_DATA_COMPLETENESS:
        return reject("insufficient_data", missing="metrics")
    if ctx.composite_percentile < MIN_COMPOSITE_PERCENTILE:
        return reject(
            "composite_below_min",
            shortfall=round(MIN_COMPOSITE_PERCENTILE - ctx.composite_percentile, 3),
        )
    if ctx.sector_pool_full:
        return reject("sector_pool_cap", sector_cap=sector_pool_cap(ctx.rank_threshold))
    if ctx.rank is None or ctx.rank > ctx.rank_threshold or not ctx.in_candidate_pool:
        return reject("outside_candidate_pool")
    if not ctx.price_above_50dma:
        return reject("below_50dma")
    if not (ctx.fresh_breakout or ctx.macd_bullish):
        return reject("no_technical_trigger")
    if ctx.days_to_earnings is not None and ctx.days_to_earnings <= EARNINGS_BLACKOUT_DAYS:
        return reject("earnings_proximity", days_to_earnings=ctx.days_to_earnings)
    if ctx.positions_held >= MAX_POSITIONS:
        return reject("max_positions", positions_held=ctx.positions_held)
    if ctx.sector_weight >= MAX_SECTOR_PCT:
        return reject("sector_cap", sector_weight=round(ctx.sector_weight, 4))
    if ctx.entries_today >= MAX_ENTRIES_PER_DAY:
        return reject("daily_entry_cap", entries_today=ctx.entries_today)
    if ctx.cash_available <= 0:
        return reject("insufficient_cash", cash_available=ctx.cash_available)
    return BuyEvaluation(passed=True, reason="buy", gate_kind="", detail=detail)


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
    composite_percentile: float | None,
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
    weak_composite = composite_percentile is not None and composite_percentile < COMPOSITE_EXIT
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
