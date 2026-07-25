"""Valuation family: EV/EBITDA, forward P/E, PEG, price/book, FCF yield (raw values)."""

from __future__ import annotations

from app.domain.signals.inputs import SignalInputs
from app.domain.stats import safe_div


def _market_cap(inputs: SignalInputs) -> float | None:
    snap = inputs.latest_fundamentals
    if snap is None or inputs.current_price is None or snap.shares_out is None:
        return None
    return inputs.current_price * snap.shares_out


def compute(inputs: SignalInputs) -> dict[str, float | None]:
    snap = inputs.latest_fundamentals
    est = inputs.estimates
    market_cap = _market_cap(inputs)

    ev: float | None = None
    if market_cap is not None and snap is not None:
        debt = snap.total_debt or 0.0
        cash = snap.cash or 0.0
        ev = market_cap + debt - cash

    ev_ebitda = safe_div(ev, snap.ebitda) if snap is not None else None
    price_to_book = safe_div(market_cap, snap.equity) if snap is not None else None
    fcf_yield = safe_div(snap.fcf, market_cap) if snap is not None else None

    return {
        "ev_ebitda": ev_ebitda,
        "forward_pe": est.forward_pe if est else None,
        "peg": est.peg if est else None,
        "price_to_book": price_to_book,
        "fcf_yield": fcf_yield,
    }
