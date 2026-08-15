"""Equity-curve snapshots — the one place a portfolio_snapshots row gets written.

The curve used to move only when a decision cycle completed, which made it hostage to the
cycle: a rejected order aborted the run before the write, and a worker that was down over a
session left no marks at all. Three writers now feed it, tagged by ``source``:

* ``cycle``  — the decision engine, post-trade (and post-failure; see decision_engine).
* ``poll``   — the 15-minute intraday poll, so equity tracks the market between trades.
* ``backfill`` — a one-off reconstruction from the broker's own history, equity only.

The broker is the source of truth for equity and holdings here, not the local mirror: the
mirror is written at cycle time and can be a whole session stale.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.strategy import RegimeRepository
from app.db.repositories.trading import PortfolioSnapshotRepository
from app.services.ports import BrokerClient

log = structlog.get_logger()

CYCLE = "cycle"
POLL = "poll"
BACKFILL = "backfill"


async def record_live_snapshot(
    session: AsyncSession,
    broker: BrokerClient,
    now: datetime | None = None,
    source: str = POLL,
) -> float:
    """Write one snapshot from live broker state. Returns the equity recorded.

    The regime is read from the latest classification rather than recomputed — this runs
    every 15 minutes and the regime only moves once a day.
    """
    ts = now or datetime.now(UTC)
    account, positions = await asyncio.gather(
        asyncio.to_thread(broker.get_account),
        asyncio.to_thread(broker.list_positions),
    )
    regime = await RegimeRepository(session).latest()

    await PortfolioSnapshotRepository(session).upsert({
        "ts": ts,
        "equity": account.equity,
        "cash": account.cash,
        "positions": len(positions),
        "regime": regime.label if regime else None,
        "holdings": {p.symbol: p.qty for p in positions},
        "source": source,
    })
    return account.equity


async def backfill_equity(
    session: AsyncSession,
    broker: BrokerClient,
    period: str = "1M",
    timeframe: str = "1H",
) -> int:
    """Seed the curve from the broker's account history. Returns rows inserted.

    Only fills gaps: a timestamp that already has a snapshot keeps its live row, which
    carries cash, positions and regime that the history endpoint cannot supply.
    """
    history = await asyncio.to_thread(broker.get_portfolio_history, period, timeframe)
    rows: list[dict[str, object]] = [
        {
            "ts": point.ts,
            "equity": point.equity,
            "cash": None,
            "positions": None,
            "regime": None,
            "holdings": {},
            "source": BACKFILL,
        }
        for point in history
    ]
    inserted = await PortfolioSnapshotRepository(session).insert_missing(rows)
    log.info(
        "snapshots.backfill",
        fetched=len(rows),
        inserted=inserted,
        period=period,
        timeframe=timeframe,
    )
    return inserted
