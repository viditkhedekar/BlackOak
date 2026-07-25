"""Market regime classifier (pure) — risk_on / neutral / risk_off.

Four transparent bearish checks (no ML): elevated VIX, inverted yield curve, SPY below
its 200-DMA, and weak market breadth. >=3 bearish -> risk_off; <=1 -> risk_on; else
neutral. A 2-day confirmation rule prevents whipsaw: the regime only switches after the
new raw label prints two sessions running. The regime picks the family weight set, the
cash floor, and threshold strictness in later phases — it never scores individual stocks.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.stats import sma

RISK_ON = "risk_on"
NEUTRAL = "neutral"
RISK_OFF = "risk_off"

# Thresholds (a versioned strategy_config may override these later).
VIX_ELEVATED = 20.0
BREADTH_WEAK = 0.50  # fraction of the universe above its 200-DMA
DMA_LONG = 200


@dataclass(frozen=True, slots=True)
class RegimeFeatures:
    vix_level: float | None
    vix_slope_10d: float | None  # VIX now minus VIX ~10 sessions ago (rising = fear)
    t10y2y: float | None  # 10y-2y spread; negative = inverted
    spy_vs_200dma: float | None  # SPY/200dma - 1; negative = below trend
    breadth: float | None  # fraction of universe above its own 200-DMA


@dataclass(frozen=True, slots=True)
class RegimeResult:
    label: str  # confirmed regime after the 2-day rule
    raw_label: str  # today's unconfirmed classification
    bearish_count: int
    flags: dict[str, bool]


def build_features(
    vix_series: list[float],
    t10y2y: float | None,
    spy_closes: list[float],
    breadth: float | None,
) -> RegimeFeatures:
    """Assemble features from raw series. vix_series/spy_closes ascending by date."""
    vix_level = vix_series[-1] if vix_series else None
    vix_slope = (
        vix_series[-1] - vix_series[-11] if len(vix_series) >= 11 else None
    )
    spy_200 = sma(spy_closes, DMA_LONG)
    spy_vs_200 = (
        spy_closes[-1] / spy_200 - 1.0
        if spy_200 not in (None, 0) and spy_closes
        else None
    )
    return RegimeFeatures(
        vix_level=vix_level,
        vix_slope_10d=vix_slope,
        t10y2y=t10y2y,
        spy_vs_200dma=spy_vs_200,
        breadth=breadth,
    )


def _bearish_flags(f: RegimeFeatures) -> dict[str, bool]:
    # A missing feature is treated as not-bearish (absence of evidence, not evidence).
    return {
        # VIX bearish if elevated OR rising fast (>3 pts over 10 sessions).
        "vix": (f.vix_level is not None and f.vix_level > VIX_ELEVATED)
        or (f.vix_slope_10d is not None and f.vix_slope_10d > 3.0),
        "curve_inverted": f.t10y2y is not None and f.t10y2y < 0.0,
        "spy_below_200dma": f.spy_vs_200dma is not None and f.spy_vs_200dma < 0.0,
        "weak_breadth": f.breadth is not None and f.breadth < BREADTH_WEAK,
    }


def classify_raw(f: RegimeFeatures) -> tuple[str, int, dict[str, bool]]:
    flags = _bearish_flags(f)
    count = sum(flags.values())
    if count >= 3:
        label = RISK_OFF
    elif count <= 1:
        label = RISK_ON
    else:
        label = NEUTRAL
    return label, count, flags


def confirmed_regime(raw_history: list[str], prev_confirmed: str | None) -> str:
    """Apply the 2-day confirmation rule. ``raw_history`` is newest-last and includes
    today's raw label. Switches only when the last two raw labels agree and differ from
    the currently confirmed regime."""
    if prev_confirmed is None:
        return raw_history[-1] if raw_history else NEUTRAL
    today = raw_history[-1]
    if today == prev_confirmed:
        return prev_confirmed
    if len(raw_history) >= 2 and raw_history[-1] == raw_history[-2]:
        return today
    return prev_confirmed


def resolve(
    features: RegimeFeatures, raw_history: list[str], prev_confirmed: str | None
) -> RegimeResult:
    """Classify today and resolve the confirmed regime. ``raw_history`` must already
    include today's raw label as its last element."""
    raw_label, count, flags = classify_raw(features)
    label = confirmed_regime(raw_history, prev_confirmed)
    return RegimeResult(label=label, raw_label=raw_label, bearish_count=count, flags=flags)
