"""The autonomous decision cycle (docs/ROADMAP.md R4).

Each cycle: reconcile from broker truth → build the universe snapshot (signals + regime +
fused scores, the SAME code the backtester uses) → check fuses → call the shared
``plan_cycle`` → **journal every decision (buy/sell/hold/skip/blocked) with evidence
BEFORE acting** → execute exits then entries via the broker → snapshot the portfolio.

Journaling-before-acting (ADR-0008) means the dashboard can always explain a trade, and a
crash between journal and execution is recoverable: re-running the cycle is idempotent
(deterministic client_order_id) and reconciliation repairs the mirror.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Fundamental
from app.db.repositories.companies import CompanyRepository
from app.db.repositories.estimates import EstimatesRepository
from app.db.repositories.fundamentals import FundamentalsRepository
from app.db.repositories.macro import MacroRepository
from app.db.repositories.prices import PriceRepository
from app.db.repositories.strategy import RegimeRepository
from app.db.repositories.trading import (
    PortfolioSnapshotRepository,
    PositionRepository,
    ThesisRepository,
    TradeDecisionRepository,
)
from app.domain.decision import CyclePlan, SymbolCycleData, plan_cycle
from app.domain.factors import FundamentalSnapshot
from app.domain.regime import DMA_LONG, build_features, classify_raw, resolve
from app.domain.rules import PositionState
from app.domain.signals import EstimateValues, SignalInputs, compute_signals
from app.domain.stats import sma
from app.domain.strategy import WEIGHTS_BY_REGIME, StrategyCompany, fuse_scores
from app.services.execution import place_order
from app.services.job_tracking import track_job
from app.services.ports import BrokerClient
from app.services.reconciliation import reconcile_positions

log = structlog.get_logger()

STALENESS_MAX_DAYS = 4  # halt if the latest bar is older than this
DAILY_LOSS_HALT = -0.03  # no new entries once the day is down this much


@dataclass
class CycleReport:
    cycle_id: uuid.UUID
    regime: str
    n_scored: int
    buys: int
    sells: int
    holds: int
    skips: int
    halted: bool
    halt_reason: str | None


def _f(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


def _snap(f: Fundamental) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        fiscal_year=f.fiscal_date.year,
        revenue=_f(f.revenue), gross_profit=_f(f.gross_profit), ebitda=_f(f.ebitda),
        ebit=_f(f.ebit), operating_income=_f(f.operating_income), net_income=_f(f.net_income),
        eps_diluted=_f(f.eps_diluted), interest_expense=_f(f.interest_expense),
        total_assets=_f(f.total_assets), current_assets=_f(f.current_assets),
        current_liabilities=_f(f.current_liabilities), total_debt=_f(f.total_debt),
        cash=_f(f.cash), equity=_f(f.equity), shares_out=_f(f.shares_out),
        operating_cf=_f(f.operating_cf), capex=_f(f.capex),
    )


async def run_decision_cycle(session: AsyncSession, broker: BrokerClient) -> CycleReport:
    async with track_job(session, "decision_cycle") as ctx:
        cycle_id = uuid.uuid4()
        now = datetime.now(UTC)

        # 1) Reconcile the local mirror from broker truth before deciding.
        await reconcile_positions(session, broker)

        # 2) Build the universe snapshot (same signals + regime + fusion as the backtester).
        cycle_data, regime_label, _weights, n_scored, latest_date = await _build_snapshot(session)

        # 3) Broker account + open positions (with their entry theses).
        import asyncio

        account = await asyncio.to_thread(broker.get_account)
        positions, sector_notional = await _load_positions(session, cycle_data)

        # 4) Fuses.
        halt_reason = _fuse_check(latest_date, now.date())
        entries_locked = False
        if halt_reason is None:
            entries_locked = await _daily_loss_locked(session, account.equity, now)

        # 5) Decide.
        plan = plan_cycle(
            cycle_data, positions, account.equity, account.cash, sector_notional,
            entries_today=0, n_scored=n_scored,
        )

        # 6) Journal BEFORE acting — including holds, skips, and the fuse block.
        rows = _decision_rows(cycle_id, now, regime_label, plan, cycle_data, halt_reason,
                              entries_locked)
        await TradeDecisionRepository(session).record_many(rows)
        await session.flush()

        buys = sells = holds = skips = 0
        holds = sum(1 for e in plan.exits if e.action.fraction == 0)
        skips = len(plan.skips)

        if halt_reason is not None:
            await _write_snapshot(session, now, account, regime_label, positions)
            ctx.meta = {"cycle_id": str(cycle_id), "halted": True, "reason": halt_reason}
            return CycleReport(cycle_id, regime_label, n_scored, 0, 0, holds, skips,
                              True, halt_reason)

        # 7) Execute exits first (free cash), then entries (unless locked).
        thesis_repo = ThesisRepository(session)
        for intent in plan.exits:
            if intent.action.fraction > 0:
                await place_order(session, broker, cycle_id, intent.symbol, "sell",
                                  positions[intent.symbol].shares * intent.action.fraction,
                                  intent.action.reason)
                sells += 1
                if intent.action.fraction >= 1.0:
                    await thesis_repo.delete_symbol(intent.symbol)
            else:  # hold → persist advanced trail state
                await _update_thesis_trail(thesis_repo, intent)

        if not entries_locked:
            for entry in plan.entries:
                await place_order(session, broker, cycle_id, entry.symbol, "buy",
                                  entry.shares, "entry")
                await thesis_repo.upsert(_thesis_row(entry))
                buys += 1

        # 8) Re-reconcile so the mirror reflects the fills, then snapshot.
        await reconcile_positions(session, broker)
        account = await asyncio.to_thread(broker.get_account)
        await _write_snapshot(session, now, account, regime_label, positions)

        ctx.records_processed = buys + sells
        ctx.meta = {
            "cycle_id": str(cycle_id), "regime": regime_label,
            "buys": buys, "sells": sells, "holds": holds, "skips": skips,
        }
        return CycleReport(cycle_id, regime_label, n_scored, buys, sells, holds, skips,
                          False, None)


async def _build_snapshot(
    session: AsyncSession,
) -> tuple[dict[str, SymbolCycleData], str, dict[str, float], int, date | None]:
    companies_repo = CompanyRepository(session)
    prices_repo = PriceRepository(session)
    funds_repo = FundamentalsRepository(session)
    est_repo = EstimatesRepository(session)
    macro_repo = MacroRepository(session)
    regime_repo = RegimeRepository(session)

    spy = await companies_repo.get_by_symbol("SPY")
    spy_px = await prices_repo.get_series(spy.id, None, None) if spy else []
    spy_closes = [float(p.adj_close) for p in spy_px]

    targets = await companies_repo.active_symbols("SP500")
    companies: list[StrategyCompany] = []
    signals_by_symbol: dict[str, dict[str, dict[str, float | None]]] = {}
    latest_bar: dict[str, object] = {}
    inputs_by_symbol: dict[str, SignalInputs] = {}
    above = below = 0

    for company_id, symbol in targets:
        company = await companies_repo.get_by_symbol(symbol)
        px = await prices_repo.get_series(company_id, None, None)
        if company is None or not px:
            continue
        closes = [float(p.adj_close) for p in px]
        funds = await funds_repo.get_annual(company_id)
        est_row = await est_repo.latest(company_id)
        estimates = (
            EstimateValues(forward_pe=_f(est_row.forward_pe), peg=_f(est_row.peg),
                          forward_eps=_f(est_row.forward_eps))
            if est_row else None
        )
        inputs = SignalInputs(
            symbol=symbol, sector=company.sector or "Unknown", closes=closes,
            highs=[float(p.high) for p in px], lows=[float(p.low) for p in px],
            volumes=[float(p.volume) for p in px], opens=[float(p.open) for p in px],
            current_price=closes[-1], market_closes=spy_closes,
            annual=[_snap(f) for f in funds], estimates=estimates,
        )
        sig = compute_signals(inputs)
        signals_by_symbol[symbol] = sig
        inputs_by_symbol[symbol] = inputs
        latest_bar[symbol] = px[-1]
        companies.append(StrategyCompany(symbol, inputs.sector, sig))
        ma200 = sma(closes, DMA_LONG)
        if ma200 is not None:
            above, below = (above + 1, below) if closes[-1] > ma200 else (above, below + 1)

    breadth = above / (above + below) if (above + below) else None
    vix = [float(p.value) for p in await macro_repo.get_series("VIX")]
    t10y2y_row = await macro_repo.latest("T10Y2Y")
    features = build_features(vix, float(t10y2y_row.value) if t10y2y_row else None,
                              spy_closes, breadth)
    prev = await regime_repo.latest()
    raw_history = await regime_repo.recent_raw_labels(limit=4)
    today_raw, _, _ = classify_raw(features)
    regime = resolve(features, [*raw_history, today_raw], prev.label if prev else None)
    weights = WEIGHTS_BY_REGIME[regime.label]

    scores = {s.symbol: s for s in fuse_scores(companies, regime.label)}
    cycle_data: dict[str, SymbolCycleData] = {}
    latest_date: date | None = None
    for symbol, sig in signals_by_symbol.items():
        score = scores.get(symbol)
        bar = latest_bar[symbol]
        inputs = inputs_by_symbol[symbol]
        if score is None:
            continue
        latest_date = bar.date  # type: ignore[attr-defined]
        atr_pct = sig["technical"].get("atr_pct")
        close = float(bar.close)  # type: ignore[attr-defined]
        cycle_data[symbol] = SymbolCycleData(
            symbol=symbol, sector=inputs.sector,
            bar_open=float(bar.open), bar_high=float(bar.high),  # type: ignore[attr-defined]
            bar_low=float(bar.low), bar_close=close,  # type: ignore[attr-defined]
            closes=inputs.closes, signals=sig, score=score,
            atr=(atr_pct * close) if atr_pct and atr_pct > 0 else None,
        )
    return cycle_data, regime.label, weights, len(companies), latest_date


async def _load_positions(
    session: AsyncSession, cycle_data: dict[str, SymbolCycleData]
) -> tuple[dict[str, PositionState], dict[str, float]]:
    """Combine broker-truth shares (Position mirror) with the entry thesis (trail state)."""
    theses = {t.symbol: t for t in await ThesisRepository(session).all()}
    positions: dict[str, PositionState] = {}
    sector_notional: dict[str, float] = {}
    for mirror in await PositionRepository(session).all():
        t = theses.get(mirror.symbol)
        if t is None:
            continue  # broker holds it but we have no thesis — reconcile will surface it
        positions[mirror.symbol] = PositionState(
            symbol=mirror.symbol, entry_price=float(t.entry_price), shares=float(mirror.shares),
            atr_at_entry=float(t.atr_at_entry), stop_price=float(t.stop_price),
            target_price=float(t.target_price),
            entry_composite=float(t.entry_composite) if t.entry_composite is not None else None,
            entry_fundamentals_score=(
                float(t.entry_fundamentals_score)
                if t.entry_fundamentals_score is not None else None
            ),
            took_partial=t.took_partial, highest_close=float(t.highest_close),
            reversal_days=t.reversal_days,
        )
        d = cycle_data.get(mirror.symbol)
        mark = d.bar_close if d else float(t.entry_price)
        sector = d.sector if d else "Unknown"
        sector_notional[sector] = (
            sector_notional.get(sector, 0.0) + float(mirror.shares) * mark
        )
    return positions, sector_notional


def _fuse_check(latest_date: date | None, today: date) -> str | None:
    if latest_date is None:
        return "no_data"
    if (today - latest_date) > timedelta(days=STALENESS_MAX_DAYS):
        return "stale_data"
    return None


async def _daily_loss_locked(session: AsyncSession, equity: float, now: datetime) -> bool:
    start = datetime.combine(now.date(), time(0, 0), tzinfo=UTC)
    opening = await PortfolioSnapshotRepository(session).latest_before(start)
    if opening is None or float(opening.equity) <= 0:
        return False
    return (equity / float(opening.equity) - 1.0) < DAILY_LOSS_HALT


def _decision_rows(
    cycle_id: uuid.UUID,
    now: datetime,
    regime: str,
    plan: CyclePlan,
    cycle_data: dict[str, SymbolCycleData],
    halt_reason: str | None,
    entries_locked: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if halt_reason is not None:
        rows.append({
            "cycle_id": cycle_id, "ts": now, "symbol": "*", "action": "blocked",
            "reason": halt_reason, "regime": regime, "evidence": {"fuse": halt_reason},
        })
        return rows
    for intent in plan.exits:
        a = intent.action
        rows.append({
            "cycle_id": cycle_id, "ts": now, "symbol": intent.symbol,
            "action": "sell" if a.fraction > 0 else "hold", "reason": a.reason,
            "regime": regime,
            "evidence": {"fraction": a.fraction, "exit_price": a.exit_price,
                         "new_stop": a.new_stop},
        })
    for entry in plan.entries:
        action = "blocked" if entries_locked else "buy"
        reason = "daily_loss_lock" if entries_locked else "entry"
        d = cycle_data.get(entry.symbol)
        rows.append({
            "cycle_id": cycle_id, "ts": now, "symbol": entry.symbol, "action": action,
            "reason": reason, "regime": regime,
            "evidence": {"shares": entry.shares, "ref_price": entry.ref_price,
                         "stop": entry.stop_price, "target": entry.target_price,
                         "composite": entry.entry_composite,
                         "rank": d.score.rank if d else None},
        })
    for symbol, reason in plan.skips:
        rows.append({
            "cycle_id": cycle_id, "ts": now, "symbol": symbol, "action": "skip",
            "reason": reason, "regime": regime, "evidence": {},
        })
    return rows


def _thesis_row(entry) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "symbol": entry.symbol, "entry_price": entry.ref_price,
        "atr_at_entry": entry.atr, "stop_price": entry.stop_price,
        "target_price": entry.target_price, "entry_composite": entry.entry_composite,
        "entry_fundamentals_score": entry.entry_fundamentals_score,
        "took_partial": False, "highest_close": entry.ref_price, "reversal_days": 0,
    }


async def _update_thesis_trail(thesis_repo, intent) -> None:  # type: ignore[no-untyped-def]
    existing = await thesis_repo.get(intent.symbol)
    if existing is None:
        return
    await thesis_repo.upsert({
        "symbol": intent.symbol, "entry_price": existing.entry_price,
        "atr_at_entry": existing.atr_at_entry,
        "stop_price": intent.action.new_stop, "target_price": existing.target_price,
        "entry_composite": existing.entry_composite,
        "entry_fundamentals_score": existing.entry_fundamentals_score,
        "took_partial": existing.took_partial,
        "highest_close": intent.action.new_highest_close,
        "reversal_days": intent.action.reversal_days,
    })


async def _write_snapshot(session, now, account, regime, positions) -> None:  # type: ignore[no-untyped-def]
    await PortfolioSnapshotRepository(session).upsert({
        "ts": now, "equity": account.equity, "cash": account.cash,
        "positions": len(positions), "regime": regime,
        "holdings": {sym: p.shares for sym, p in positions.items()},
    })
