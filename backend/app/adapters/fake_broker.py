"""In-memory broker for tests and backtest/live parity checks.

Fills market orders instantly at a supplied reference price. Enforces the same
client_order_id idempotency contract as the real adapter so idempotency is testable
without a network."""

from __future__ import annotations

from app.domain.broker import (
    FILLED,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
)


class FakeBroker:
    name = "fake"

    def __init__(self, cash: float = 100_000.0) -> None:
        self._cash = cash
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, BrokerOrder] = {}
        self._prices: dict[str, float] = {}

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def get_account(self) -> BrokerAccount:
        holdings = sum(
            p.qty * self._prices.get(p.symbol, p.avg_entry_price)
            for p in self._positions.values()
        )
        equity = self._cash + holdings
        return BrokerAccount(cash=self._cash, equity=equity, buying_power=self._cash)

    def list_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def submit_order(
        self, client_order_id: str, symbol: str, side: str, qty: float
    ) -> BrokerOrder:
        # Idempotency: a known client_order_id returns the existing order untouched.
        if client_order_id in self._orders:
            return self._orders[client_order_id]

        price = self._prices.get(symbol, 100.0)
        if side == "buy":
            self._cash -= qty * price
            existing = self._positions.get(symbol)
            if existing is None:
                self._positions[symbol] = BrokerPosition(symbol, qty, price, qty * price)
            else:
                total = existing.qty + qty
                avg = (existing.qty * existing.avg_entry_price + qty * price) / total
                self._positions[symbol] = BrokerPosition(symbol, total, avg, total * price)
        else:  # sell
            self._cash += qty * price
            existing = self._positions.get(symbol)
            if existing is not None:
                remaining = existing.qty - qty
                if remaining <= 1e-9:
                    del self._positions[symbol]
                else:
                    self._positions[symbol] = BrokerPosition(
                        symbol, remaining, existing.avg_entry_price, remaining * price
                    )

        order = BrokerOrder(
            client_order_id=client_order_id,
            broker_order_id=f"fake-{len(self._orders) + 1}",
            symbol=symbol, side=side, qty=qty, status=FILLED,
            filled_qty=qty, filled_avg_price=price,
        )
        self._orders[client_order_id] = order
        return order

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        return self._orders.get(client_order_id)
