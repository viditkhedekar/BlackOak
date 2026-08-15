"""Exit sizing against broker truth.

Regression for a live rejection: the mirror stores shares as Numeric(18,6), so a broker
holding of 28.156361547 lands in the DB as 28.156362. Selling that rounded number liquidated
nothing — Alpaca rejected the order ("insufficient qty available"), the exception aborted the
cycle before its snapshot, and the equity curve lost the point entirely.
"""

from __future__ import annotations

import uuid

import pytest

from app.adapters.fake_broker import FakeBroker
from app.services.decision_engine import _exit_qty
from app.services.execution import client_order_id

# The exact holding and mirror value from the rejected CTVA order.
BROKER_SHARES = 28.156361547
MIRROR_SHARES = 28.156362  # Numeric(18,6) rounds the 7th decimal up


def test_full_exit_sells_exactly_what_the_broker_holds() -> None:
    assert _exit_qty(BROKER_SHARES, MIRROR_SHARES, 1.0) == BROKER_SHARES


def test_full_exit_never_exceeds_the_holding() -> None:
    assert _exit_qty(BROKER_SHARES, MIRROR_SHARES, 1.0) <= BROKER_SHARES


def test_partial_exit_scales_the_broker_quantity() -> None:
    assert _exit_qty(BROKER_SHARES, MIRROR_SHARES, 0.5) == pytest.approx(
        BROKER_SHARES * 0.5
    )


def test_mirror_is_the_fallback_when_the_broker_omits_the_symbol() -> None:
    # A position the broker did not return still has to be sizable from what we know.
    assert _exit_qty(None, MIRROR_SHARES, 1.0) == MIRROR_SHARES


def test_broker_rejects_the_mirror_rounded_liquidation() -> None:
    """The bug itself, end to end through the broker boundary."""
    broker = FakeBroker()
    broker.set_price("CTVA", 60.0)
    broker.set_position("CTVA", BROKER_SHARES, 55.0)
    coid = str(client_order_id(uuid.uuid4(), "CTVA", "sell"))

    with pytest.raises(ValueError, match="insufficient qty"):
        broker.submit_order(coid, "CTVA", "sell", MIRROR_SHARES)


def test_broker_accepts_the_exit_quantity_we_now_send() -> None:
    broker = FakeBroker()
    broker.set_price("CTVA", 60.0)
    broker.set_position("CTVA", BROKER_SHARES, 55.0)
    qty = _exit_qty(BROKER_SHARES, MIRROR_SHARES, 1.0)

    order = broker.submit_order(
        str(client_order_id(uuid.uuid4(), "CTVA", "sell")), "CTVA", "sell", qty
    )

    assert order.filled_qty == pytest.approx(BROKER_SHARES)
    assert broker.list_positions() == []
