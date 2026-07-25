"""Pure technical indicators — RSI, MACD, ATR, breakouts, volume, candlesticks.

Stdlib-only and deterministic (docs/ARCHITECTURE.md rule 1). Conventions chosen to
match the widely published reference implementations so results line up with TA-Lib /
StockCharts:
  * RSI and ATR use Wilder's smoothing (the (n-1)/n recursion).
  * MACD/EMA use the 2/(n+1) multiplier, seeded from the SMA of the first `period`
    values (the StockCharts convention).
All functions return the *latest* value (or None when there isn't enough history),
which is what the signal engines consume.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """Full EMA series, seeded with the SMA of the first `period` values.

    The returned series starts at index `period-1` of the input (one EMA value per
    input point from that offset on). Empty if there isn't a full seed window.
    """
    if period <= 0 or len(values) < period:
        return []
    multiplier = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for value in values[period:]:
        out.append((value - out[-1]) * multiplier + out[-1])
    return out


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """Wilder's RSI of the latest bar. None if fewer than `period`+1 closes.

    All-gains history → 100; all-losses → 0 (avg loss 0 ⇒ RSI defined as 100)."""
    if period <= 0 or len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in pairwise(closes):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


@dataclass(frozen=True, slots=True)
class MacdResult:
    macd: float
    signal: float
    histogram: float


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> MacdResult | None:
    """MACD line (EMA fast - EMA slow), its signal EMA, and the histogram.

    Needs slow + signal - 1 closes so the signal EMA has a full seed window."""
    if fast >= slow or len(closes) < slow + signal - 1:
        return None

    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    # Align the two EMAs on their common tail (fast started earlier).
    offset = len(fast_ema) - len(slow_ema)
    macd_line = [f - s for f, s in zip(fast_ema[offset:], slow_ema, strict=True)]

    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None
    macd_value = macd_line[-1]
    signal_value = signal_line[-1]
    return MacdResult(
        macd=macd_value, signal=signal_value, histogram=macd_value - signal_value
    )


def true_ranges(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    """True Range per bar. The first bar's TR is simply high - low (no prior close)."""
    n = min(len(highs), len(lows), len(closes))
    if n == 0:
        return []
    out = [highs[0] - lows[0]]
    for i in range(1, n):
        prev_close = closes[i - 1]
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> float | None:
    """Wilder's Average True Range of the latest bar. None if fewer than `period`+1 bars."""
    tr = true_ranges(highs, lows, closes)
    if period <= 0 or len(tr) < period + 1:
        return None
    # Seed with the simple mean of the first `period` TRs (skip TR[0], which lacks a
    # prior close), then Wilder-smooth. Matches the standard ATR reference.
    seed = sum(tr[1 : period + 1]) / period
    value = seed
    for t in tr[period + 1 :]:
        value = (value * (period - 1) + t) / period
    return value


def rolling_high(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return max(values[-window:])


def rolling_low(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return min(values[-window:])


def breakout_strength(
    closes: Sequence[float], window: int, atr_value: float | None
) -> float | None:
    """(latest close - prior `window`-bar high) / ATR — how far past resistance, in ATRs.

    Positive = a fresh high beyond the prior range; negative = still below it. The prior
    high excludes the latest bar so a breakout registers on the bar that makes it."""
    if atr_value is None or atr_value <= 0 or len(closes) < window + 1:
        return None
    prior_high = max(closes[-window - 1 : -1])
    return (closes[-1] - prior_high) / atr_value


def volume_ratio(volumes: Sequence[float], window: int = 20) -> float | None:
    """Latest volume ÷ average of the prior `window` bars (a spike detector)."""
    if window <= 0 or len(volumes) < window + 1:
        return None
    avg = sum(volumes[-window - 1 : -1]) / window
    if avg <= 0:
        return None
    return volumes[-1] / avg


# --- Minimal candlestick primitives (low weight by design; most patterns have no edge) -

def is_bullish_engulfing(
    prev_open: float, prev_close: float, cur_open: float, cur_close: float
) -> bool:
    """Prior bar down, current bar up and its body engulfs the prior body."""
    prev_down = prev_close < prev_open
    cur_up = cur_close > cur_open
    engulfs = cur_open <= prev_close and cur_close >= prev_open
    return prev_down and cur_up and engulfs


def is_hammer(open_: float, high: float, low: float, close: float) -> bool:
    """Small real body near the top with a long lower shadow (>= 2x the body)."""
    body = abs(close - open_)
    if body == 0:
        return False
    lower_shadow = min(open_, close) - low
    upper_shadow = high - max(open_, close)
    return lower_shadow >= 2 * body and upper_shadow <= body


def is_doji(open_: float, high: float, low: float, close: float, tol: float = 0.001) -> bool:
    """Open ≈ close (indecision): body ≤ `tol` of the bar's full range."""
    rng = high - low
    if rng <= 0:
        return False
    return abs(close - open_) <= tol * rng
