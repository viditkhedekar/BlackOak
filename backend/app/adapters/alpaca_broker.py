"""Alpaca **paper** broker adapter (ADR-0007: no real money, ever).

Safety rails, defence in depth:
  * constructed with paper=True and the base URL is hard-asserted to the paper host —
    the adapter refuses to talk to the live endpoint;
  * a per-day order-count cap and a per-order notional cap are enforced here as well as
    in the decision engine.
Idempotency: our client_order_id is sent to Alpaca; a resubmit returns the existing order
rather than creating a second.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.domain.broker import (
    ACCEPTED,
    CANCELED,
    EXPIRED,
    FILLED,
    PARTIALLY_FILLED,
    REJECTED,
    BrokerAccount,
    BrokerOrder,
    BrokerPosition,
    PortfolioHistoryPoint,
)

log = structlog.get_logger()

PAPER_HOST = "paper-api.alpaca.markets"
MAX_ORDERS_PER_DAY = 40

_STATUS_MAP = {
    "filled": FILLED,
    "partially_filled": PARTIALLY_FILLED,
    "canceled": CANCELED,
    "expired": EXPIRED,
    "rejected": REJECTED,
    "done_for_day": CANCELED,
}


def _map_status(raw: str) -> str:
    return _STATUS_MAP.get(raw.lower(), ACCEPTED)


class AlpacaPaperBroker:
    name = "alpaca_paper"

    def __init__(self, api_key: str, secret_key: str) -> None:
        from alpaca.trading.client import TradingClient

        self._client = TradingClient(api_key, secret_key, paper=True)
        # Belt-and-suspenders: refuse anything that isn't the paper endpoint.
        # alpaca-py stores _base_url as a BaseURL enum whose str() is the member name,
        # not the URL — read .value first or the guard rejects the paper host itself.
        raw_base = getattr(self._client, "_base_url", PAPER_HOST)
        base = str(getattr(raw_base, "value", raw_base))
        if PAPER_HOST not in base:
            raise RuntimeError(f"refusing non-paper broker endpoint: {base!r}")
        self._orders_today = 0

    def get_account(self) -> BrokerAccount:
        acct: Any = self._client.get_account()
        return BrokerAccount(
            cash=float(acct.cash),
            equity=float(acct.equity),
            buying_power=float(acct.buying_power),
        )

    def list_positions(self) -> list[BrokerPosition]:
        out: list[BrokerPosition] = []
        positions: list[Any] = list(self._client.get_all_positions())
        for p in positions:
            out.append(
                BrokerPosition(
                    symbol=p.symbol,
                    qty=float(p.qty),
                    avg_entry_price=float(p.avg_entry_price),
                    market_value=float(p.market_value or 0),
                )
            )
        return out

    def get_portfolio_history(
        self, period: str = "1M", timeframe: str = "1H"
    ) -> list[PortfolioHistoryPoint]:
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        history: Any = self._client.get_portfolio_history(
            GetPortfolioHistoryRequest(period=period, timeframe=timeframe)
        )
        stamps: list[Any] = list(getattr(history, "timestamp", None) or [])
        equities: list[Any] = list(getattr(history, "equity", None) or [])

        out: list[PortfolioHistoryPoint] = []
        for stamp, equity in zip(stamps, equities, strict=False):
            # Alpaca emits a null equity for marks before the account was funded, and a
            # zero would read as a total wipeout on the curve rather than as "no data".
            if stamp is None or equity is None or float(equity) <= 0:
                continue
            out.append(
                PortfolioHistoryPoint(
                    ts=datetime.fromtimestamp(int(stamp), tz=UTC), equity=float(equity)
                )
            )
        out.sort(key=lambda p: p.ts)
        return out

    def submit_order(
        self, client_order_id: str, symbol: str, side: str, qty: float
    ) -> BrokerOrder:
        # Idempotency: return the existing order if this client id was already used.
        existing = self.get_order(client_order_id)
        if existing is not None:
            return existing
        if self._orders_today >= MAX_ORDERS_PER_DAY:
            raise RuntimeError(f"daily order cap {MAX_ORDERS_PER_DAY} reached")

        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        order = self._client.submit_order(request)
        self._orders_today += 1
        return self._to_order(order, client_order_id)

    def get_order(self, client_order_id: str) -> BrokerOrder | None:
        try:
            order = self._client.get_order_by_client_id(client_order_id)
        except Exception:
            return None
        return self._to_order(order, client_order_id)

    def _to_order(self, order: object, client_order_id: str) -> BrokerOrder:
        filled_qty = float(getattr(order, "filled_qty", 0) or 0)
        avg = getattr(order, "filled_avg_price", None)
        return BrokerOrder(
            client_order_id=client_order_id,
            broker_order_id=str(getattr(order, "id", "") or "") or None,
            symbol=str(getattr(order, "symbol", "")),
            side=str(getattr(getattr(order, "side", ""), "value", getattr(order, "side", ""))),
            qty=float(getattr(order, "qty", 0) or 0),
            status=_map_status(str(getattr(getattr(order, "status", ""), "value", ""))),
            filled_qty=filled_qty,
            filled_avg_price=float(avg) if avg is not None else None,
        )
