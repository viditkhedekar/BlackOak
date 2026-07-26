"""Order execution: idempotent placement via the broker + local ledger recording.

client_order_id is derived deterministically from (cycle_id, symbol, side) so re-running a
cycle never double-submits — the broker and the local ledger both dedupe on it. The DB
owns intent (orders); the broker owns fills (executions/positions truth)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.trading import (
    ExecutionRepository,
    OrderRepository,
)
from app.domain.broker import FILLED, PARTIALLY_FILLED, BrokerOrder
from app.services.ports import BrokerClient

log = structlog.get_logger()

_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-00000000ba51")  # stable app namespace


def client_order_id(cycle_id: uuid.UUID, symbol: str, side: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{cycle_id}:{symbol}:{side}")


async def place_order(
    session: AsyncSession,
    broker: BrokerClient,
    cycle_id: uuid.UUID,
    symbol: str,
    side: str,
    qty: float,
    reason: str,
) -> BrokerOrder | None:
    """Place one market order idempotently. Returns the broker order, or None if this
    (cycle, symbol, side) was already placed."""
    coid = client_order_id(cycle_id, symbol, side)
    orders = OrderRepository(session)
    if await orders.by_client_id(coid) is not None:
        log.info("execution.duplicate_skipped", symbol=symbol, side=side)
        return None

    broker_order = await asyncio.to_thread(broker.submit_order, str(coid), symbol, side, qty)

    await orders.create(
        {
            "client_order_id": coid,
            "broker_order_id": broker_order.broker_order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "status": broker_order.status,
            "reason": reason,
            "reject_reason": broker_order.reject_reason,
            "submitted_at": datetime.now(UTC),
        }
    )

    if broker_order.status in (FILLED, PARTIALLY_FILLED) and broker_order.filled_avg_price:
        order_row = await orders.by_client_id(coid)
        assert order_row is not None
        await ExecutionRepository(session).record(
            {
                "order_id": order_row.id,
                "broker_execution_id": broker_order.broker_order_id,
                "symbol": symbol,
                "fill_qty": broker_order.filled_qty,
                "fill_price": broker_order.filled_avg_price,
                "filled_at": datetime.now(UTC),
            }
        )
    return broker_order
