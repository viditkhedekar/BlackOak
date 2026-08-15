"""A cycle that dies mid-execution still marks the equity curve.

The regression: a rejected sell order raised out of the execution loop, which sat *above*
the snapshot write. The run journaled its decisions (track_job commits on the failure path)
but left no equity point, so a day of real trading showed up on the dashboard as a flat
line with nothing on it.

The cycle's data-gathering seams are stubbed here — the point under test is the ordering of
execution and the snapshot write, not the signal pipeline.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.fake_broker import FakeBroker
from app.db.models import (
    Execution,
    JobRun,
    Order,
    PortfolioSnapshot,
    PositionThesis,
    TradeDecision,
)
from app.domain.decision import CyclePlan, EntryIntent
from app.services import decision_engine
from app.services.position_adoption import AdoptionReport

_STARTING_CASH = 75_000.0


@pytest.fixture
def stubbed_cycle(monkeypatch: pytest.MonkeyPatch):
    """Reduce the cycle to: fetch account, plan one entry, place it, snapshot."""
    entry = EntryIntent(
        symbol="AAA", shares=10.0, ref_price=50.0, stop_price=45.0, target_price=60.0,
        atr=1.0, entry_composite=61.0, entry_fundamentals_score=70.0, sector="Tech",
    )

    async def _snapshot(_session):  # noqa: ANN001
        return {}, "risk_on", {}, 0, datetime.now(UTC).date()

    async def _adopt(_session, _data):  # noqa: ANN001
        return AdoptionReport()

    async def _reconcile(_session, _broker):  # noqa: ANN001
        return None

    async def _positions(_session, _data):  # noqa: ANN001
        return {}, {}

    async def _unlocked(_session, _equity, _now):  # noqa: ANN001
        # The fuse compares against whatever equity the database last saw, which for a
        # stub account is an arbitrary drawdown. Entries must stay open here.
        return False

    monkeypatch.setattr(decision_engine, "_daily_loss_locked", _unlocked)
    monkeypatch.setattr(decision_engine, "_build_snapshot", _snapshot)
    monkeypatch.setattr(decision_engine, "adopt_orphan_positions", _adopt)
    monkeypatch.setattr(decision_engine, "reconcile_positions", _reconcile)
    monkeypatch.setattr(decision_engine, "_load_positions", _positions)
    monkeypatch.setattr(
        decision_engine, "plan_cycle",
        lambda *a, **k: CyclePlan(exits=[], entries=[entry], skips=[]),
    )
    return entry


@pytest.fixture
async def clean_cycle_rows(db_session: AsyncSession):
    """Everything a cycle writes, removed afterwards — this runs against a real database."""
    started = datetime.now(UTC) - timedelta(seconds=1)
    yield started
    # A failing cycle leaves the session dirty; the teardown needs a clean one.
    await db_session.rollback()
    await db_session.execute(delete(Execution).where(Execution.created_at >= started))
    await db_session.execute(delete(Order).where(Order.created_at >= started))
    await db_session.execute(
        delete(PositionThesis).where(PositionThesis.created_at >= started)
    )
    await db_session.execute(
        delete(PortfolioSnapshot).where(PortfolioSnapshot.ts >= started)
    )
    await db_session.execute(delete(TradeDecision).where(TradeDecision.ts >= started))
    await db_session.execute(delete(JobRun).where(JobRun.started_at >= started))
    await db_session.commit()


async def _latest_snapshot(session: AsyncSession, since: datetime) -> PortfolioSnapshot | None:
    result = await session.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.ts >= since)
        .order_by(PortfolioSnapshot.ts.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def test_rejected_order_still_leaves_an_equity_point(
    db_session: AsyncSession, stubbed_cycle: EntryIntent, clean_cycle_rows: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _reject(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("insufficient qty available for order")

    monkeypatch.setattr(decision_engine, "place_order", _reject)
    broker = FakeBroker(cash=_STARTING_CASH)

    with pytest.raises(RuntimeError, match="insufficient qty"):
        await decision_engine.run_decision_cycle(db_session, broker)

    snapshot = await _latest_snapshot(db_session, clean_cycle_rows)
    assert snapshot is not None, "a failed cycle must still record where equity stood"
    assert float(snapshot.equity) == pytest.approx(_STARTING_CASH)
    assert snapshot.source == "cycle"


async def test_successful_cycle_still_records_one_point(
    db_session: AsyncSession, stubbed_cycle: EntryIntent, clean_cycle_rows: datetime,
) -> None:
    broker = FakeBroker(cash=_STARTING_CASH)
    broker.set_price("AAA", 50.0)

    report = await decision_engine.run_decision_cycle(db_session, broker)

    assert report.buys == 1
    snapshot = await _latest_snapshot(db_session, clean_cycle_rows)
    assert snapshot is not None
    assert snapshot.source == "cycle"
    # Cash spent on the entry, equity unchanged: the snapshot is post-trade.
    assert float(snapshot.cash) == pytest.approx(_STARTING_CASH - 500.0)
