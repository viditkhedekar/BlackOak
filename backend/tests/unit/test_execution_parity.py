"""R4 gate: backtest and live execution honor the SAME plan_cycle output identically,
and order placement is idempotent on client_order_id.

Pure tests (FakeBroker + SimPortfolio, no DB): the architectural parity guarantee is that
both worlds consume the same intents from the shared decision core."""

from __future__ import annotations

import uuid
from datetime import date

from app.adapters.fake_broker import FakeBroker
from app.backtest.portfolio import SimPortfolio
from app.domain.decision import SymbolCycleData, plan_cycle
from app.domain.rules import PositionState
from app.domain.signals.inputs import SIGNAL_FAMILIES
from app.domain.strategy import StrategyScore
from app.services.execution import client_order_id


def _buy_ready(symbol: str, rank: int) -> SymbolCycleData:
    closes = [100.0 + i * 0.5 for i in range(60)]  # steady rise → price above 50DMA
    signals = {fam: {m: 60.0 for m in metrics} for fam, metrics in SIGNAL_FAMILIES.items()}
    signals["technical"]["macd_hist"] = 0.8
    signals["technical"]["atr_pct"] = 0.02
    signals["technical"]["volume_spike"] = 1.0
    signals["momentum"]["breakout_strength"] = 1.5
    signals["fundamentals"]["interest_coverage"] = 8.0
    score = StrategyScore(
        symbol=symbol,
        families={f: 80.0 for f in SIGNAL_FAMILIES},
        composite=62.0, rank=rank, data_completeness=0.9, composite_percentile=95.0,
    )
    return SymbolCycleData(
        symbol=symbol, sector="Tech",
        bar_open=closes[-1], bar_high=closes[-1] + 1, bar_low=closes[-1] - 1,
        bar_close=closes[-1], closes=closes, signals=signals, score=score,
        atr=0.02 * closes[-1],
    )


def test_backtest_and_live_execution_agree_on_plan() -> None:
    data = {f"S{i}": _buy_ready(f"S{i}", rank=i + 1) for i in range(3)}
    plan = plan_cycle(
        data, positions={}, equity=100_000, cash=100_000,
        sector_notional={}, entries_today=0, n_scored=30,
    )
    assert plan.entries, "expected at least one entry from a buy-ready universe"

    # Backtest execution path.
    sim = SimPortfolio(cash=100_000)
    for e in plan.entries:
        state = PositionState(
            symbol=e.symbol, entry_price=e.ref_price, shares=e.shares, atr_at_entry=e.atr,
            stop_price=e.stop_price, target_price=e.target_price,
            entry_composite=e.entry_composite, entry_fundamentals_score=e.entry_fundamentals_score,
            highest_close=e.ref_price,
        )
        sim.buy(e.symbol, date(2026, 1, 2), e.shares, e.ref_price, state)

    # Live execution path (broker).
    broker = FakeBroker(cash=100_000)
    cid = uuid.uuid4()
    for e in plan.entries:
        broker.set_price(e.symbol, e.ref_price)
        broker.submit_order(str(client_order_id(cid, e.symbol, "buy")), e.symbol, "buy", e.shares)

    sim_holdings = {sym: pos.shares for sym, pos in sim.positions.items()}
    live_holdings = {p.symbol: p.qty for p in broker.list_positions()}
    assert sim_holdings == live_holdings  # identical symbols and share counts


def test_order_placement_idempotent() -> None:
    broker = FakeBroker(cash=100_000)
    broker.set_price("AAPL", 200.0)
    cid = uuid.uuid4()
    coid = str(client_order_id(cid, "AAPL", "buy"))

    first = broker.submit_order(coid, "AAPL", "buy", 10)
    after_one = {p.symbol: p.qty for p in broker.list_positions()}
    # Resubmit the SAME client_order_id — must not create a second fill.
    second = broker.submit_order(coid, "AAPL", "buy", 10)
    after_two = {p.symbol: p.qty for p in broker.list_positions()}

    assert first.broker_order_id == second.broker_order_id
    assert after_one == after_two == {"AAPL": 10.0}


def test_client_order_id_deterministic() -> None:
    cid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert client_order_id(cid, "AAPL", "buy") == client_order_id(cid, "AAPL", "buy")
    assert client_order_id(cid, "AAPL", "buy") != client_order_id(cid, "AAPL", "sell")
