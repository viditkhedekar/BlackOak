"""Technical family: RSI, MACD histogram, volume spike, ATR%, S/R position, candle."""

from __future__ import annotations

from app.domain.indicators import (
    atr,
    is_bullish_engulfing,
    is_hammer,
    macd,
    rolling_high,
    rolling_low,
    rsi,
    volume_ratio,
)
from app.domain.signals.inputs import DMA_SHORT, SignalInputs


def _candle_signal(inputs: SignalInputs) -> float | None:
    """+1 on a bullish reversal (engulfing or hammer), else 0. None without OHLC opens."""
    o, h, low, c = inputs.opens, inputs.highs, inputs.lows, inputs.closes
    if len(o) < 2 or len(h) < 2 or len(low) < 2 or len(c) < 2:
        return None
    bullish = is_bullish_engulfing(o[-2], c[-2], o[-1], c[-1]) or is_hammer(
        o[-1], h[-1], low[-1], c[-1]
    )
    return 1.0 if bullish else 0.0


def compute(inputs: SignalInputs) -> dict[str, float | None]:
    closes = inputs.closes
    price = inputs.current_price if inputs.current_price is not None else (
        closes[-1] if closes else None
    )

    macd_result = macd(closes)
    atr_value = atr(inputs.highs, inputs.lows, closes, period=14)
    atr_pct = atr_value / price if atr_value is not None and price not in (None, 0) else None

    hi = rolling_high(closes, DMA_SHORT)
    lo = rolling_low(closes, DMA_SHORT)
    sr_position: float | None = None
    if None not in (hi, lo, price) and hi != lo:
        sr_position = (price - lo) / (hi - lo)  # type: ignore[operator]

    return {
        "rsi_14": rsi(closes, 14),
        "macd_hist": macd_result.histogram if macd_result is not None else None,
        "volume_spike": volume_ratio(inputs.volumes, DMA_SHORT),
        "atr_pct": atr_pct,
        "sr_position": sr_position,
        "candle_signal": _candle_signal(inputs),
    }
