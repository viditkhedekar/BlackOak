"""Momentum family: MA stack, distance above 200-DMA, relative strength, 12-1, breakout."""

from __future__ import annotations

from app.domain.indicators import atr, breakout_strength
from app.domain.signals.inputs import (
    DMA_LONG,
    DMA_MID,
    DMA_SHORT,
    MONTH,
    RS_WINDOW,
    YEAR,
    SignalInputs,
    windowed_return,
)
from app.domain.stats import sma


def compute(inputs: SignalInputs) -> dict[str, float | None]:
    closes = inputs.closes
    price = inputs.current_price if inputs.current_price is not None else (
        closes[-1] if closes else None
    )

    ma20 = sma(closes, DMA_SHORT)
    ma50 = sma(closes, DMA_MID)
    ma200 = sma(closes, DMA_LONG)

    ma_stack: float | None = None
    if price is not None and None not in (ma20, ma50, ma200):
        ma_stack = float(sum(price > m for m in (ma20, ma50, ma200)))  # type: ignore[operator]

    pct_above_200dma = (
        price / ma200 - 1.0 if price is not None and ma200 not in (None, 0) else None
    )

    # Relative strength: the stock's window return minus SPY's over the same window.
    rs_vs_spy: float | None = None
    stock_ret = windowed_return(closes, RS_WINDOW)
    spy_ret = windowed_return(inputs.market_closes, RS_WINDOW)
    if stock_ret is not None and spy_ret is not None:
        rs_vs_spy = stock_ret - spy_ret

    # 12-1 momentum: return from ~12 months ago to ~1 month ago (skip the last month).
    ret_12_1 = windowed_return(closes, YEAR - MONTH, skip=MONTH)

    atr_value = atr(inputs.highs, inputs.lows, closes, period=14)
    breakout = breakout_strength(closes, DMA_SHORT, atr_value)

    return {
        "ma_stack": ma_stack,
        "pct_above_200dma": pct_above_200dma,
        "rs_vs_spy": rs_vs_spy,
        "ret_12_1": ret_12_1,
        "breakout_strength": breakout,
    }
