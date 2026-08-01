"""R4 gate: backtest and live execution honor the SAME plan_cycle output identically,
and order placement is idempotent on client_order_id.

Pure tests (FakeBroker + SimPortfolio, no DB): the architectural parity guarantee is that
both worlds consume the same intents from the shared decision core."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from app.adapters.fake_broker import FakeBroker
from app.backtest.portfolio import SimPortfolio
from app.domain.decision import SymbolCycleData, plan_cycle, plan_exits
from app.domain.rules import PositionState
from app.domain.signals.inputs import SIGNAL_FAMILIES
from app.domain.strategy import StrategyScore
from app.services.decision_engine import _persist_exit_state
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
        weight_covered=1.0,
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


# --- Partial-exit state must survive the cycle (the live engine's half of parity) ------
#
# The backtester latches took_partial inside SimPortfolio.sell and writes the advanced
# trail back on the same pass. The live engine persists that state through the thesis
# row, so these lock the equivalent behaviour on that side.


@dataclass
class _ThesisRow:
    symbol: str
    entry_price: float
    atr_at_entry: float
    stop_price: float
    target_price: float
    entry_composite: float | None = None
    entry_fundamentals_score: float | None = None
    took_partial: bool = False
    highest_close: float = 0.0
    reversal_days: int = 0


class _FakeThesisRepo:
    """In-memory stand-in for ThesisRepository (same three methods the engine uses)."""

    def __init__(self, rows: dict[str, _ThesisRow]) -> None:
        self.rows = rows

    async def get(self, symbol: str) -> _ThesisRow | None:
        return self.rows.get(symbol)

    async def upsert(self, row: dict) -> None:  # type: ignore[type-arg]
        self.rows[str(row["symbol"])] = _ThesisRow(**row)  # type: ignore[arg-type]

    async def delete_symbol(self, symbol: str) -> None:
        self.rows.pop(symbol, None)


def _at_target(symbol: str = "T1") -> SymbolCycleData:
    """A held name trading through its target: rising trend, healthy score, no exit signal
    other than the target itself."""
    closes = [100.0 + i * 0.5 for i in range(60)]
    signals = {fam: {m: 60.0 for m in metrics} for fam, metrics in SIGNAL_FAMILIES.items()}
    signals["technical"]["macd_hist"] = 0.8
    signals["fundamentals"]["interest_coverage"] = 8.0
    score = StrategyScore(
        symbol=symbol, families={f: 80.0 for f in SIGNAL_FAMILIES},
        composite=62.0, rank=1, data_completeness=0.9, composite_percentile=95.0,
        weight_covered=1.0,
    )
    return SymbolCycleData(
        symbol=symbol, sector="Tech",
        bar_open=106.0, bar_high=108.0, bar_low=105.0, bar_close=107.0,
        closes=closes, signals=signals, score=score, atr=2.0,
    )


def _thesis_to_state(row: _ThesisRow, shares: float) -> PositionState:
    """Mirror of the live engine's _load_positions: broker shares + thesis trail state."""
    return PositionState(
        symbol=row.symbol, entry_price=row.entry_price, shares=shares,
        atr_at_entry=row.atr_at_entry, stop_price=row.stop_price,
        target_price=row.target_price, entry_composite=row.entry_composite,
        entry_fundamentals_score=row.entry_fundamentals_score,
        took_partial=row.took_partial, highest_close=row.highest_close,
        reversal_days=row.reversal_days,
    )


def _fresh_thesis() -> _ThesisRow:
    # stop = entry - 2.5*ATR, target = entry + 3*ATR, matching domain.sizing.
    return _ThesisRow(
        symbol="T1", entry_price=100.0, atr_at_entry=2.0,
        stop_price=95.0, target_price=106.0, highest_close=100.0,
    )


async def test_partial_exit_latches_took_partial_and_breakeven_stop() -> None:
    repo = _FakeThesisRepo({"T1": _fresh_thesis()})
    data = {"T1": _at_target()}
    positions = {"T1": _thesis_to_state(repo.rows["T1"], shares=10.0)}

    (intent,) = plan_exits(positions, data)
    assert intent.action.fraction == 0.5, "expected a target trim"

    await _persist_exit_state(repo, intent)

    row = repo.rows["T1"]
    assert row.took_partial is True
    assert row.stop_price == 100.0  # raised to breakeven by the trim
    assert row.highest_close == 107.0


async def test_target_trim_does_not_repeat_on_the_next_cycle() -> None:
    """The regression: without a persisted took_partial the engine re-trims half the
    position every 30-minute cycle for as long as price stays above the target."""
    repo = _FakeThesisRepo({"T1": _fresh_thesis()})
    data = {"T1": _at_target()}
    shares = 10.0
    fractions = []

    for _ in range(3):  # three consecutive cycles on the same above-target bar
        positions = {"T1": _thesis_to_state(repo.rows["T1"], shares)}
        (intent,) = plan_exits(positions, data)
        fractions.append(intent.action.fraction)
        shares -= shares * intent.action.fraction
        await _persist_exit_state(repo, intent)

    assert fractions == [0.5, 0.0, 0.0], "the target trim must fire once, not every cycle"
    assert shares == 5.0


async def test_full_exit_drops_the_thesis() -> None:
    repo = _FakeThesisRepo({"T1": _fresh_thesis()})
    data = {"T1": _at_target()}
    # Gap straight through the stop → full exit.
    stopped = {"T1": _thesis_to_state(repo.rows["T1"], shares=10.0)}
    stopped["T1"].stop_price = 110.0  # above the bar's low, so the stop triggers

    (intent,) = plan_exits(stopped, data)
    assert intent.action.fraction == 1.0

    await _persist_exit_state(repo, intent)
    assert "T1" not in repo.rows
