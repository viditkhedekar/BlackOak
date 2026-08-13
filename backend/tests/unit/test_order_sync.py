"""Open-order sync: a fill that lands after submit must reach the ledger, exactly once.

Orders placed outside regular trading hours come back ``accepted`` and fill at the open,
so the submit-time execution record in ``place_order`` never fires for them. These cover
the poller that closes that gap.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from app.domain.broker import ACCEPTED, FILLED, REJECTED, BrokerOrder
from app.services import order_sync
from app.services.order_sync import sync_open_orders


@dataclass
class _Order:
    id: uuid.UUID
    client_order_id: uuid.UUID
    symbol: str
    status: str


class _FakeOrders:
    def __init__(self, orders: list[_Order]) -> None:
        self._orders = orders
        self.updates: list[tuple[uuid.UUID, str, str | None]] = []

    async def open_orders(self) -> list[_Order]:
        return list(self._orders)

    async def update_status(
        self, order_id: uuid.UUID, status: str, reject_reason: str | None
    ) -> None:
        self.updates.append((order_id, status, reject_reason))


class _FakeExecutions:
    def __init__(self) -> None:
        self.recorded: list[dict[str, object]] = []

    async def record(self, row: dict[str, object]) -> None:
        self.recorded.append(row)

    async def exists_for_order(self, order_id: uuid.UUID) -> bool:
        return any(r["order_id"] == order_id for r in self.recorded)


class _StubBroker:
    name = "stub"

    def __init__(self, remote: dict[str, BrokerOrder | None]) -> None:
        self._remote = remote

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        return self._remote.get(client_order_id)


def _wire(monkeypatch: pytest.MonkeyPatch, orders: _FakeOrders, execs: _FakeExecutions) -> None:
    monkeypatch.setattr(order_sync, "OrderRepository", lambda _session: orders)
    monkeypatch.setattr(order_sync, "ExecutionRepository", lambda _session: execs)


def _order(symbol: str, status: str = ACCEPTED) -> _Order:
    return _Order(id=uuid.uuid4(), client_order_id=uuid.uuid4(), symbol=symbol, status=status)


def _filled(o: _Order, qty: float, price: float) -> BrokerOrder:
    return BrokerOrder(
        client_order_id=str(o.client_order_id), broker_order_id=f"brk-{o.symbol}",
        symbol=o.symbol, side="buy", qty=qty, status=FILLED,
        filled_qty=qty, filled_avg_price=price,
    )


@pytest.mark.asyncio
async def test_late_fill_advances_status_and_records_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    o = _order("STT")
    orders, execs = _FakeOrders([o]), _FakeExecutions()
    _wire(monkeypatch, orders, execs)
    broker = _StubBroker({str(o.client_order_id): _filled(o, 12.94, 105.5)})

    report = await sync_open_orders(object(), broker)  # type: ignore[arg-type]

    assert report.checked == 1
    assert report.advanced == 1
    assert report.filled == 1
    assert orders.updates == [(o.id, FILLED, None)]
    assert execs.recorded[0]["symbol"] == "STT"
    assert execs.recorded[0]["fill_price"] == 105.5


@pytest.mark.asyncio
async def test_second_poll_does_not_double_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """The poller revisits orders every 30 min — the fill must not be recorded twice."""
    o = _order("NEM")
    orders, execs = _FakeOrders([o]), _FakeExecutions()
    _wire(monkeypatch, orders, execs)
    broker = _StubBroker({str(o.client_order_id): _filled(o, 20.9, 61.2)})

    first = await sync_open_orders(object(), broker)  # type: ignore[arg-type]
    second = await sync_open_orders(object(), broker)  # type: ignore[arg-type]

    assert first.filled == 1
    assert second.filled == 0
    assert len(execs.recorded) == 1


@pytest.mark.asyncio
async def test_still_open_order_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    o = _order("BAC")
    orders, execs = _FakeOrders([o]), _FakeExecutions()
    _wire(monkeypatch, orders, execs)
    unchanged = BrokerOrder(
        client_order_id=str(o.client_order_id), broker_order_id="brk-BAC", symbol="BAC",
        side="buy", qty=38.0, status=ACCEPTED,
    )
    broker = _StubBroker({str(o.client_order_id): unchanged})

    report = await sync_open_orders(object(), broker)  # type: ignore[arg-type]

    assert (report.advanced, report.filled) == (0, 0)
    assert orders.updates == []
    assert execs.recorded == []


@pytest.mark.asyncio
async def test_rejected_order_advances_with_reason_but_no_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    o = _order("APA")
    orders, execs = _FakeOrders([o]), _FakeExecutions()
    _wire(monkeypatch, orders, execs)
    rejected = BrokerOrder(
        client_order_id=str(o.client_order_id), broker_order_id="brk-APA", symbol="APA",
        side="buy", qty=61.5, status=REJECTED, reject_reason="insufficient buying power",
    )
    broker = _StubBroker({str(o.client_order_id): rejected})

    report = await sync_open_orders(object(), broker)  # type: ignore[arg-type]

    assert orders.updates == [(o.id, REJECTED, "insufficient buying power")]
    assert report.filled == 0
    assert execs.recorded == []


@pytest.mark.asyncio
async def test_order_unknown_to_broker_is_reported_not_crashed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    o = _order("GHOST")
    orders, execs = _FakeOrders([o]), _FakeExecutions()
    _wire(monkeypatch, orders, execs)
    broker = _StubBroker({})  # broker has no record of it

    report = await sync_open_orders(object(), broker)  # type: ignore[arg-type]

    assert report.missing == ["GHOST"]
    assert (report.advanced, report.filled) == (0, 0)
