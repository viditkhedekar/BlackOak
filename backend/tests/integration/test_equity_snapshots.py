"""The equity curve keeps its points.

Covers the two ways the curve went blank: a backfilled row overwriting (or shadowing) a
live one, and the live snapshot itself never being written.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.fake_broker import FakeBroker
from app.db.models import PortfolioSnapshot
from app.db.repositories.trading import PortfolioSnapshotRepository
from app.services.snapshots import BACKFILL, POLL, backfill_equity, record_live_snapshot

# Far enough out that these rows can never collide with real snapshots.
_BASE_TS = datetime(2019, 3, 4, 15, 0, tzinfo=UTC)


@pytest.fixture
async def clean_snapshots(db_session: AsyncSession):
    async def _purge() -> None:
        await db_session.execute(
            delete(PortfolioSnapshot).where(
                PortfolioSnapshot.ts >= _BASE_TS,
                PortfolioSnapshot.ts < _BASE_TS + timedelta(days=1),
            )
        )
        await db_session.commit()

    await _purge()
    yield
    await _purge()


async def _rows(session: AsyncSession) -> list[PortfolioSnapshot]:
    return [
        s for s in await PortfolioSnapshotRepository(session).series(limit=5000)
        if _BASE_TS <= s.ts < _BASE_TS + timedelta(days=1)
    ]


async def test_poll_snapshot_records_broker_equity(
    db_session: AsyncSession, clean_snapshots: None
) -> None:
    broker = FakeBroker(cash=50_000.0)
    broker.set_price("AAA", 20.0)
    broker.submit_order("coid-1", "AAA", "buy", 100.0)

    equity = await record_live_snapshot(db_session, broker, _BASE_TS, POLL)
    await db_session.commit()

    (row,) = await _rows(db_session)
    assert row.source == POLL
    assert float(row.equity) == pytest.approx(equity)
    assert row.positions == 1
    assert row.holdings == {"AAA": 100.0}


async def test_backfill_fills_gaps_without_touching_live_rows(
    db_session: AsyncSession, clean_snapshots: None
) -> None:
    live_ts = _BASE_TS
    gap_ts = _BASE_TS + timedelta(hours=1)

    broker = FakeBroker(cash=50_000.0)
    await record_live_snapshot(db_session, broker, live_ts, POLL)
    await db_session.commit()

    # History covers the live timestamp as well as the gap; only the gap may be written.
    broker.set_history([(live_ts, 1.0), (gap_ts, 61_234.5)])
    inserted = await backfill_equity(db_session, broker)
    await db_session.commit()

    assert inserted == 1
    by_ts = {r.ts: r for r in await _rows(db_session)}
    assert float(by_ts[live_ts].equity) == pytest.approx(50_000.0)  # untouched
    assert by_ts[live_ts].source == POLL
    assert float(by_ts[gap_ts].equity) == pytest.approx(61_234.5)
    assert by_ts[gap_ts].source == BACKFILL
    assert by_ts[gap_ts].cash is None  # history reports equity and nothing else


async def test_backfilled_row_never_becomes_the_dashboard_latest(
    db_session: AsyncSession, clean_snapshots: None
) -> None:
    """A reconstructed point has no cash or regime, so it must not shadow the live row."""
    broker = FakeBroker(cash=50_000.0)
    await record_live_snapshot(db_session, broker, _BASE_TS, POLL)
    broker.set_history([(_BASE_TS + timedelta(hours=2), 99_000.0)])
    await backfill_equity(db_session, broker)
    await db_session.commit()

    latest = await PortfolioSnapshotRepository(db_session).latest()

    assert latest is not None
    assert latest.source != BACKFILL
    assert latest.cash is not None


async def test_backfill_is_idempotent(
    db_session: AsyncSession, clean_snapshots: None
) -> None:
    broker = FakeBroker()
    broker.set_history([(_BASE_TS + timedelta(minutes=m), 100.0 + m) for m in (0, 15, 30)])

    first = await backfill_equity(db_session, broker)
    await db_session.commit()
    second = await backfill_equity(db_session, broker)
    await db_session.commit()

    assert first == 3
    assert second == 0
    assert len(await _rows(db_session)) == 3
