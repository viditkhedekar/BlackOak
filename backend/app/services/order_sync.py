"""Advance open orders from broker truth (docs/ARCHITECTURE.md §12, "advance open-order
statuses").

``place_order`` records an execution only when the broker fills synchronously at submit.
Anything placed outside regular trading hours comes back ``accepted`` and fills later, so
without this poller the local ledger would keep those orders open forever and never record
the fill — the position mirror would show the shares with no trade behind them.

Idempotent: terminal orders are never re-fetched, and an order that already has an
execution row is never double-recorded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.trading import ExecutionRepository, OrderRepository
from app.domain.broker import FILLED, PARTIALLY_FILLED
from app.services.ports import BrokerClient

log = structlog.get_logger()


@dataclass
class OrderSyncReport:
    checked: int = 0
    advanced: int = 0  # status changed
    filled: int = 0  # execution rows written
    missing: list[str] = field(default_factory=list)  # broker has no record


async def sync_open_orders(session: AsyncSession, broker: BrokerClient) -> OrderSyncReport:
    orders = OrderRepository(session)
    executions = ExecutionRepository(session)
    report = OrderSyncReport()

    for order in await orders.open_orders():
        report.checked += 1
        remote = await asyncio.to_thread(broker.get_order, str(order.client_order_id))
        if remote is None:
            report.missing.append(order.symbol)
            continue

        if remote.status != order.status:
            await orders.update_status(order.id, remote.status, remote.reject_reason)
            report.advanced += 1

        filled = remote.status in (FILLED, PARTIALLY_FILLED) and remote.filled_avg_price
        if filled and not await executions.exists_for_order(order.id):
            await executions.record(
                {
                    "order_id": order.id,
                    "broker_execution_id": remote.broker_order_id,
                    "symbol": order.symbol,
                    "fill_qty": remote.filled_qty,
                    "fill_price": remote.filled_avg_price,
                    "filled_at": datetime.now(UTC),
                }
            )
            report.filled += 1

    log.info(
        "order_sync.done",
        checked=report.checked,
        advanced=report.advanced,
        filled=report.filled,
        missing=report.missing,
    )
    return report
