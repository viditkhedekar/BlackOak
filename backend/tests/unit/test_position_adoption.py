"""Adopting broker positions the engine has no thesis for.

Without a thesis a holding is invisible to the sell rules — it can never stop out, hit a
target, or trail. These cover the adoption that closes that gap, and the one case where
adoption must refuse rather than invent a stop.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.rules import evaluate_sell
from app.domain.sizing import STOP_ATR_MULT, TARGET_ATR_MULT
from app.services import position_adoption
from app.services.position_adoption import adopt_orphan_positions


@dataclass
class _Mirror:
    symbol: str
    avg_entry_price: float
    shares: float = 10.0


@dataclass
class _Thesis:
    symbol: str


@dataclass
class _Data:
    symbol: str
    atr: float | None
    bar_close: float
    sector: str = "Financials"


class _FakePositions:
    def __init__(self, rows: list[_Mirror]) -> None:
        self._rows = rows

    async def all(self) -> list[_Mirror]:
        return list(self._rows)


class _FakeTheses:
    def __init__(self, existing: list[str]) -> None:
        self._existing = [_Thesis(s) for s in existing]
        self.written: list[dict[str, object]] = []

    async def all(self) -> list[_Thesis]:
        return list(self._existing)

    async def upsert(self, row: dict[str, object]) -> None:
        self.written.append(row)


def _wire(
    monkeypatch: pytest.MonkeyPatch, positions: _FakePositions, theses: _FakeTheses
) -> None:
    monkeypatch.setattr(position_adoption, "PositionRepository", lambda _s: positions)
    monkeypatch.setattr(position_adoption, "ThesisRepository", lambda _s: theses)


@pytest.mark.asyncio
async def test_orphan_gets_a_thesis_priced_off_current_atr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    positions = _FakePositions([_Mirror("JPM", avg_entry_price=354.25)])
    theses = _FakeTheses([])
    _wire(monkeypatch, positions, theses)
    data = {"JPM": _Data("JPM", atr=6.0, bar_close=360.0)}

    report = await adopt_orphan_positions(object(), data)  # type: ignore[arg-type]

    assert report.adopted == ["JPM"]
    row = theses.written[0]
    assert row["entry_price"] == 354.25  # the real cost basis, not the current mark
    assert row["stop_price"] == pytest.approx(354.25 - STOP_ATR_MULT * 6.0)
    assert row["target_price"] == pytest.approx(354.25 + TARGET_ATR_MULT * 6.0)
    assert row["entry_composite"] is None
    assert row["took_partial"] is False
    assert row["reversal_days"] == 0


@pytest.mark.asyncio
async def test_positions_that_already_have_a_thesis_are_left_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-adopting would reset the trail and discard a hard-won breakeven stop."""
    positions = _FakePositions([_Mirror("STT", 105.5), _Mirror("KIM", 26.6)])
    theses = _FakeTheses(["STT"])
    _wire(monkeypatch, positions, theses)
    data = {
        "STT": _Data("STT", atr=2.0, bar_close=107.0),
        "KIM": _Data("KIM", atr=0.5, bar_close=27.0),
    }

    report = await adopt_orphan_positions(object(), data)  # type: ignore[arg-type]

    assert report.adopted == ["KIM"]
    assert [r["symbol"] for r in theses.written] == ["KIM"]


@pytest.mark.asyncio
@pytest.mark.parametrize("atr", [None, 0.0, -1.0])
async def test_refuses_to_adopt_without_a_usable_atr(
    monkeypatch: pytest.MonkeyPatch, atr: float | None
) -> None:
    """No ATR means no defensible stop distance — report it, never fabricate one."""
    positions = _FakePositions([_Mirror("GHOST", 50.0)])
    theses = _FakeTheses([])
    _wire(monkeypatch, positions, theses)
    data = {"GHOST": _Data("GHOST", atr=atr, bar_close=51.0)}

    report = await adopt_orphan_positions(object(), data)  # type: ignore[arg-type]

    assert report.adopted == []
    assert report.unmanageable == ["GHOST"]
    assert theses.written == []


@pytest.mark.asyncio
async def test_symbol_absent_from_the_cycle_is_unmanageable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    positions = _FakePositions([_Mirror("DELISTED", 12.0)])
    theses = _FakeTheses([])
    _wire(monkeypatch, positions, theses)

    report = await adopt_orphan_positions(object(), {})  # type: ignore[arg-type]

    assert report.unmanageable == ["DELISTED"]


@pytest.mark.asyncio
async def test_highest_close_never_starts_above_the_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guessed post-entry high would put the chandelier trail above price and force an
    immediate sell — an invented trade on invented state."""
    positions = _FakePositions([_Mirror("BAC", avg_entry_price=62.19)])
    theses = _FakeTheses([])
    _wire(monkeypatch, positions, theses)
    # Position is underwater: entry 62.19, now 55.00.
    data = {"BAC": _Data("BAC", atr=1.5, bar_close=55.0)}

    await adopt_orphan_positions(object(), data)  # type: ignore[arg-type]

    assert theses.written[0]["highest_close"] == 62.19


@pytest.mark.asyncio
async def test_adopted_position_is_actually_sellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of adoption: the sell rules can now act on the holding."""
    from app.domain.rules import PositionState

    positions = _FakePositions([_Mirror("APA", avg_entry_price=35.6)])
    theses = _FakeTheses([])
    _wire(monkeypatch, positions, theses)
    await adopt_orphan_positions(  # type: ignore[arg-type]
        object(), {"APA": _Data("APA", atr=1.0, bar_close=35.0)}
    )
    row = theses.written[0]

    pos = PositionState(
        symbol="APA", entry_price=float(row["entry_price"]),  # type: ignore[arg-type]
        shares=10.0, atr_at_entry=float(row["atr_at_entry"]),  # type: ignore[arg-type]
        stop_price=float(row["stop_price"]),  # type: ignore[arg-type]
        target_price=float(row["target_price"]),  # type: ignore[arg-type]
        entry_composite=None, entry_fundamentals_score=None,
        took_partial=False, highest_close=float(row["highest_close"]),  # type: ignore[arg-type]
        reversal_days=0,
    )
    # Price craters through the freshly-derived stop.
    action = evaluate_sell(
        pos, bar_open=33.5, bar_high=33.6, bar_low=32.0, bar_close=32.2,
        composite_percentile=80.0, fundamentals_score=60.0, momentum_score=50.0,
        interest_coverage=5.0, price_below_50dma=True, macd_bearish=True,
    )
    assert action.fraction == 1.0
    assert action.reason in ("stop_loss", "stop_gap")
