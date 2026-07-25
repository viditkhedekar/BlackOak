"""Golden tests for the pure indicators.

Reference values are hand-computed and shown in each test's arithmetic, so the lock is
auditable rather than copied from an opaque fixture. Conventions (Wilder RSI/ATR,
2/(n+1) EMA seeded from SMA) match TA-Lib / StockCharts.
"""

from __future__ import annotations

import math

from app.domain.indicators import (
    atr,
    breakout_strength,
    ema_series,
    is_bullish_engulfing,
    is_doji,
    is_hammer,
    macd,
    rsi,
    volume_ratio,
)


def test_ema_seeded_from_sma() -> None:
    # values [1,2,3,4,5], period 3: seed=SMA(1,2,3)=2, mult=0.5.
    # next: (4-2)*.5+2=3 ; (5-3)*.5+3=4  →  series [2,3,4]
    assert ema_series([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]


def test_ema_constant_series_is_constant() -> None:
    assert ema_series([7.0] * 10, 4) == [7.0] * 7


def test_rsi_all_gains_is_100() -> None:
    assert rsi([float(i) for i in range(1, 20)], 14) == 100.0


def test_rsi_all_losses_is_0() -> None:
    assert rsi([float(i) for i in range(20, 1, -1)], 14) == 0.0


def test_rsi_hand_computed() -> None:
    # closes [10,11,10,11,12], period 2.
    # gains [1,0,1,1] losses [0,1,0,0]; seeds avg_gain=.5 avg_loss=.5
    # step: (.5+1)/2=.75 / (.5)/2=.25 ; (.75+1)/2=.875 / (.25)/2=.125
    # RS=.875/.125=7 → RSI=100-100/8=87.5
    result = rsi([10, 11, 10, 11, 12], 2)
    assert result is not None
    assert math.isclose(result, 87.5, abs_tol=1e-9)


def test_rsi_none_when_insufficient() -> None:
    assert rsi([10, 11], 14) is None


def test_macd_constant_series_is_zero() -> None:
    result = macd([5.0] * 40)
    assert result is not None
    assert math.isclose(result.macd, 0.0, abs_tol=1e-9)
    assert math.isclose(result.histogram, 0.0, abs_tol=1e-9)


def test_macd_positive_histogram_on_uptrend() -> None:
    result = macd([float(i) for i in range(1, 60)])
    assert result is not None
    # A steady rise keeps the fast EMA above the slow EMA → positive MACD.
    assert result.macd > 0


def test_macd_none_when_insufficient() -> None:
    assert macd([1.0] * 10) is None


def test_atr_hand_computed() -> None:
    # period 2. highs [10,12,11,15] lows [8,9,10,11] closes [9,11,10,14]
    # TR: 2, max(3,3,0)=3, max(1,0,1)=1, max(4,5,1)=5
    # seed=mean(TR[1:3])=mean(3,1)=2 ; step (2*1+5)/2=3.5
    result = atr([10, 12, 11, 15], [8, 9, 10, 11], [9, 11, 10, 14], period=2)
    assert result is not None
    assert math.isclose(result, 3.5, abs_tol=1e-9)


def test_atr_constant_range() -> None:
    highs = [10, 11, 12, 13, 14]
    lows = [8, 9, 10, 11, 12]
    closes = [9, 10, 11, 12, 13]
    result = atr(highs, lows, closes, period=3)
    assert result is not None
    assert math.isclose(result, 2.0, abs_tol=1e-9)


def test_breakout_strength_in_atrs() -> None:
    # prior 3-bar high (excl. latest) = 10, close 12, atr 1 → 2 ATRs above.
    assert breakout_strength([10, 10, 10, 12], window=3, atr_value=1.0) == 2.0


def test_breakout_strength_none_without_atr() -> None:
    assert breakout_strength([10, 10, 10, 12], window=3, atr_value=None) is None


def test_volume_ratio() -> None:
    # latest 200 over prior-3 average 100 → 2.0
    assert volume_ratio([100, 100, 100, 200], window=3) == 2.0


def test_candles() -> None:
    # prior down bar (open 11, close 9) engulfed by up bar (open 8.5, close 11.5)
    assert is_bullish_engulfing(11, 9, 8.5, 11.5) is True
    assert is_bullish_engulfing(9, 11, 8.5, 11.5) is False  # prior was up
    # hammer: body 1 (10→11), long lower shadow 3 (low 7), tiny upper shadow
    assert is_hammer(open_=10, high=11.2, low=7, close=11) is True
    # doji: open≈close relative to range
    assert is_doji(open_=10.0, high=11.0, low=9.0, close=10.0005) is True
    assert is_doji(open_=10.0, high=11.0, low=9.0, close=10.9) is False
