"""Execution cost model (ADR-0008): slippage + half-spread + volume-spike impact.

Deliberately conservative so backtest results aren't flattered. All costs push the fill
price against the trade (buys fill higher, sells fill lower)."""

from __future__ import annotations

SLIPPAGE_BPS = 5.0  # 5 basis points base slippage
HALF_SPREAD_BPS = 2.0  # half the bid/ask spread, modelled flat
IMPACT_BPS_PER_SPIKE = 3.0  # extra drag when entering on a volume spike (thin liquidity)


def fill_price(mid: float, side: str, volume_ratio: float | None = None) -> float:
    """Adjust a mid/close price for costs. ``side`` is 'buy' or 'sell'.

    A volume_ratio > 1.5 (a spike we chase) adds market-impact drag scaled by how far
    past the spike threshold we are."""
    bps = SLIPPAGE_BPS + HALF_SPREAD_BPS
    if volume_ratio is not None and volume_ratio > 1.5:
        bps += IMPACT_BPS_PER_SPIKE * min(volume_ratio - 1.5, 3.0)
    adj = mid * bps / 10_000.0
    return mid + adj if side == "buy" else mid - adj
