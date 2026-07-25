"""Cross-sectional ranking primitive: winsorize → z-score → normal-CDF percentile.

Shared by the v2 strategy fusion (``domain/strategy.py``). The v1 ``domain/scoring.py``
keeps its own private copy on purpose — that engine is frozen (ADR-0007) and its golden
tests lock exact outputs, so it must not shift if this file ever changes.
"""

from __future__ import annotations

from statistics import NormalDist, fmean, pstdev

_NEUTRAL = 50.0
_NORM = NormalDist()


def _quantile(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])


def winsorize(values: list[float], lo: float = 0.01, hi: float = 0.99) -> list[float]:
    ordered = sorted(values)
    low, high = _quantile(ordered, lo), _quantile(ordered, hi)
    return [min(max(v, low), high) for v in values]


def percentile_rank(
    values_by_symbol: dict[str, float], inverse: bool
) -> dict[str, float]:
    """One metric, one cohort → {symbol: 0-100 percentile}.

    Winsorize the cohort at 1/99, z-score, map through the normal CDF. A degenerate
    cohort (all equal) scores everyone at the neutral 50. When ``inverse`` is set, the
    sign flips so a lower raw value ranks higher."""
    symbols = list(values_by_symbol)
    winsorized = winsorize([values_by_symbol[s] for s in symbols])
    mean = fmean(winsorized)
    sd = pstdev(winsorized)
    if sd == 0:
        return dict.fromkeys(symbols, _NEUTRAL)
    out: dict[str, float] = {}
    for sym, wv in zip(symbols, winsorized, strict=True):
        z = (wv - mean) / sd
        if inverse:
            z = -z
        out[sym] = round(_NORM.cdf(z) * 100.0, 3)
    return out
