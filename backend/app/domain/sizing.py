"""Pure position sizing (docs/ROADMAP.md §8 / plan §Buy rule 6).

Risk-parity first: every new position risks the same fraction of equity (the stop
distance times the share count), so a volatile name gets fewer shares than a calm one.
That budget is then capped by a max-position limit and available cash. Higher-composite
names are funded first by the caller (conviction tilt) rather than by inflating size.
"""

from __future__ import annotations

from dataclasses import dataclass

# Risk that one position's stop being hit costs, as a fraction of total equity.
# Sized for a MAX_POSITIONS-name book: risk budget x position count is the portfolio's
# worst case if every stop is hit at once, so these two move together.
RISK_BUDGET_PCT = 0.004
STOP_ATR_MULT = 2.5
TARGET_ATR_MULT = 3.0
TRAIL_ATR_MULT = 3.0  # chandelier trail distance once past +1R
# Must leave room for MAX_POSITIONS names to be funded from one book of equity. At the
# old 0.08 a typical 2%-ATR name sized straight to the cap, so cash ran out after ~12
# positions and everything after that skipped on insufficient_cash — the stated limit of
# 20 was never reachable.
MAX_POSITION_PCT = 0.025
MIN_NOTIONAL = 100.0  # skip dust positions


@dataclass(frozen=True, slots=True)
class PositionSize:
    shares: float
    notional: float
    stop_price: float
    target_price: float
    risk_amount: float  # dollars at risk to the initial stop


def size_position(
    equity: float, price: float, atr: float, cash_available: float
) -> PositionSize | None:
    """Size a new long. None if inputs are unusable or the position would be dust.

    ``atr`` is in price units (not a percent). Fractional shares are allowed (Alpaca
    supports them), so no integer flooring."""
    if equity <= 0 or price <= 0 or atr <= 0 or cash_available <= 0:
        return None

    stop_distance = STOP_ATR_MULT * atr
    if stop_distance <= 0:
        return None

    risk_shares = (RISK_BUDGET_PCT * equity) / stop_distance
    max_pos_shares = (MAX_POSITION_PCT * equity) / price
    affordable_shares = cash_available / price

    shares = min(risk_shares, max_pos_shares, affordable_shares)
    notional = shares * price
    if shares <= 0 or notional < MIN_NOTIONAL:
        return None

    return PositionSize(
        shares=shares,
        notional=notional,
        stop_price=price - stop_distance,
        target_price=price + TARGET_ATR_MULT * atr,
        risk_amount=shares * stop_distance,
    )
