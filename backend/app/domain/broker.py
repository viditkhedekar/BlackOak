"""Broker boundary DTOs — plain data returned by any BrokerClient adapter.

Order status is normalised to our lifecycle vocabulary so services never branch on a
vendor's strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Normalised order lifecycle.
SUBMITTED = "submitted"
ACCEPTED = "accepted"
PARTIALLY_FILLED = "partially_filled"
FILLED = "filled"
CANCELED = "canceled"
REJECTED = "rejected"
EXPIRED = "expired"

TERMINAL = frozenset({FILLED, CANCELED, REJECTED, EXPIRED})


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    cash: float
    equity: float
    buying_power: float


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float


@dataclass(frozen=True, slots=True)
class PortfolioHistoryPoint:
    """One equity mark from the broker's own account history.

    Equity only: the history endpoint reports what the account was worth at a moment, not
    how that value was split between cash and holdings.
    """

    ts: datetime
    equity: float


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    client_order_id: str
    broker_order_id: str | None
    symbol: str
    side: str  # buy | sell
    qty: float
    status: str  # one of the lifecycle constants above
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    reject_reason: str | None = None
