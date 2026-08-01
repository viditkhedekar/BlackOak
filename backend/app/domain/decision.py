"""Pure cycle planner — the single decision brain (ADR-0008).

Given a market snapshot and a portfolio view, decide WHAT to do (exit/entry intents) and
why. It never mutates a portfolio, touches a broker, or applies costs — those differ
between the backtester (SimPortfolio) and the live engine (BrokerClient), which both call
this and then execute the returned intents. Sizing and running-cash accounting use mid
prices; execution cost is applied identically downstream, so the *decisions* are byte-for-
byte identical in both worlds. That equality is the R4 parity gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.rules import (
    GATE_KIND_BY_REASON,
    BuyContext,
    PositionState,
    SellAction,
    build_candidate_pool,
    candidate_pool_size,
    evaluate_buy,
    evaluate_sell,
)
from app.domain.sizing import size_position
from app.domain.stats import sma
from app.domain.strategy import StrategyScore


@dataclass(frozen=True, slots=True)
class SymbolCycleData:
    symbol: str
    sector: str
    bar_open: float
    bar_high: float
    bar_low: float
    bar_close: float
    closes: list[float]  # adjusted closes up to and including this cycle
    signals: dict[str, dict[str, float | None]]
    score: StrategyScore
    atr: float | None  # price units


@dataclass(frozen=True, slots=True)
class ExitIntent:
    symbol: str
    action: SellAction


@dataclass(frozen=True, slots=True)
class EntryIntent:
    symbol: str
    shares: float
    ref_price: float  # mid (this cycle's close); execution applies cost to it
    stop_price: float
    target_price: float
    atr: float
    entry_composite: float | None
    entry_fundamentals_score: float | None
    sector: str


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """Why one candidate was passed over, with the numbers behind the call."""

    symbol: str
    reason: str
    gate_kind: str  # score_threshold | hard_rule | portfolio_limit
    rank: int | None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CyclePlan:
    exits: list[ExitIntent] = field(default_factory=list)
    entries: list[EntryIntent] = field(default_factory=list)
    skips: list[SkipRecord] = field(default_factory=list)
    rank_threshold: int = 0  # top-decile cutoff this cycle; journal uses it for triage


def _flags(data: SymbolCycleData) -> dict[str, bool]:
    ma50 = sma(data.closes, 50)
    price = data.closes[-1] if data.closes else data.bar_close
    macd_hist = data.signals.get("technical", {}).get("macd_hist")
    breakout = data.signals.get("momentum", {}).get("breakout_strength")
    return {
        "price_above_50dma": ma50 is not None and price > ma50,
        "price_below_50dma": ma50 is not None and price < ma50,
        "macd_bullish": macd_hist is not None and macd_hist > 0,
        "macd_bearish": macd_hist is not None and macd_hist < 0,
        "fresh_breakout": breakout is not None and breakout > 0,
    }


def plan_exits(
    positions: dict[str, PositionState], data: dict[str, SymbolCycleData]
) -> list[ExitIntent]:
    """One intent per held position that has a bar this cycle. Holds are included too so
    the executor can advance the trailing stop from the returned SellAction."""
    intents: list[ExitIntent] = []
    for sym in list(positions):
        d = data.get(sym)
        if d is None:
            continue
        pos = positions[sym]
        flags = _flags(d)
        score = d.score
        action = evaluate_sell(
            pos,
            bar_open=d.bar_open, bar_high=d.bar_high, bar_low=d.bar_low, bar_close=d.bar_close,
            composite_percentile=score.composite_percentile,
            fundamentals_score=score.families.get("fundamentals"),
            momentum_score=score.families.get("momentum"),
            interest_coverage=d.signals.get("fundamentals", {}).get("interest_coverage"),
            price_below_50dma=flags["price_below_50dma"],
            macd_bearish=flags["macd_bearish"],
        )
        intents.append(ExitIntent(symbol=sym, action=action))
    return intents


def plan_entries(
    data: dict[str, SymbolCycleData],
    equity: float,
    cash: float,
    held_symbols: set[str],
    sector_notional: dict[str, float],
    entries_today: int,
    n_scored: int,
) -> tuple[list[EntryIntent], list[SkipRecord], int]:
    """Plan new entries in composite-rank order, funding the strongest first. Returns
    (entries, skips, rank_threshold) where skips carry the gate reason and its evidence
    for the decision journal."""
    rank_threshold = candidate_pool_size(n_scored)
    # Unranked names are kept as candidates (sorted last) so they are journaled as
    # insufficient_data rather than vanishing from the audit trail.
    candidates = sorted(data.values(), key=lambda d: d.score.rank or 10**9)
    # The pool is sector-capped before any gate runs, so a single crowded sector cannot
    # take the whole thing and crowd out better-diversified names further down the rank.
    pool, capped_out = build_candidate_pool(
        [(d.symbol, d.sector) for d in candidates if d.score.rank is not None],
        rank_threshold,
    )
    entries: list[EntryIntent] = []
    skips: list[SkipRecord] = []
    running_cash = cash
    running_sector = dict(sector_notional)
    planned = 0

    for d in candidates:
        sym = d.symbol
        if sym in held_symbols:
            continue
        flags = _flags(d)
        sector_weight = (running_sector.get(d.sector, 0.0) / equity) if equity > 0 else 0.0
        ctx = BuyContext(
            composite=d.score.composite,
            composite_percentile=d.score.composite_percentile,
            rank=d.score.rank,
            rank_threshold=rank_threshold,
            in_candidate_pool=sym in pool,
            sector_pool_full=sym in capped_out,
            data_completeness=d.score.data_completeness,
            weight_covered=d.score.weight_covered,
            price_above_50dma=flags["price_above_50dma"],
            fresh_breakout=flags["fresh_breakout"],
            macd_bullish=flags["macd_bullish"],
            days_to_earnings=None,
            positions_held=len(held_symbols) + planned,
            sector_weight=sector_weight,
            entries_today=entries_today + planned,
            cash_available=running_cash,
            already_held=False,
        )
        verdict = evaluate_buy(ctx)
        if not verdict.passed:
            skips.append(
                SkipRecord(sym, verdict.reason, verdict.gate_kind, d.score.rank, verdict.detail)
            )
            continue
        if d.atr is None or d.atr <= 0:
            skips.append(
                SkipRecord(sym, "no_atr", GATE_KIND_BY_REASON["no_atr"], d.score.rank,
                           {**verdict.detail, "atr": d.atr})
            )
            continue
        size = size_position(equity, d.bar_close, d.atr, running_cash)
        if size is None:
            skips.append(
                SkipRecord(sym, "size_too_small", GATE_KIND_BY_REASON["size_too_small"],
                           d.score.rank, {**verdict.detail, "cash_available": running_cash})
            )
            continue
        entries.append(
            EntryIntent(
                symbol=sym, shares=size.shares, ref_price=d.bar_close,
                stop_price=size.stop_price, target_price=size.target_price, atr=d.atr,
                entry_composite=d.score.composite,
                entry_fundamentals_score=d.score.families.get("fundamentals"),
                sector=d.sector,
            )
        )
        running_cash -= size.notional
        running_sector[d.sector] = running_sector.get(d.sector, 0.0) + size.notional
        planned += 1

    return entries, skips, rank_threshold


def plan_cycle(
    data: dict[str, SymbolCycleData],
    positions: dict[str, PositionState],
    equity: float,
    cash: float,
    sector_notional: dict[str, float],
    entries_today: int,
    n_scored: int,
) -> CyclePlan:
    exits = plan_exits(positions, data)
    entries, skips, rank_threshold = plan_entries(
        data, equity, cash, set(positions), sector_notional, entries_today, n_scored
    )
    return CyclePlan(
        exits=exits, entries=entries, skips=skips, rank_threshold=rank_threshold
    )
