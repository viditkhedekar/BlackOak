"""Pure numeric helpers shared by the factor engine (and later the metrics engine).

Deliberately stdlib-only (math + statistics) so results are deterministic and the
domain layer stays dependency-free and trivially unit-testable.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from itertools import pairwise


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def daily_returns(prices: Sequence[float]) -> list[float]:
    """Simple day-over-day returns. Skips any non-positive prior price."""
    out: list[float] = []
    for prev, cur in pairwise(prices):
        if prev > 0:
            out.append(cur / prev - 1.0)
    return out


def sma(prices: Sequence[float], window: int) -> float | None:
    if len(prices) < window or window <= 0:
        return None
    return sum(prices[-window:]) / window


def annualized_vol(returns: Sequence[float], periods_per_year: int = 252) -> float | None:
    if len(returns) < 2:
        return None
    return statistics.pstdev(returns) * math.sqrt(periods_per_year)


def downside_deviation(
    returns: Sequence[float], threshold: float = 0.0, periods_per_year: int = 252
) -> float | None:
    downside = [min(r - threshold, 0.0) for r in returns]
    if len(downside) < 2:
        return None
    mean_sq = sum(d * d for d in downside) / len(downside)
    return math.sqrt(mean_sq) * math.sqrt(periods_per_year)


def max_drawdown(prices: Sequence[float]) -> float | None:
    """Largest peak-to-trough decline as a non-positive fraction (e.g. -0.23)."""
    if len(prices) < 2:
        return None
    peak = prices[0]
    worst = 0.0
    for p in prices:
        peak = max(peak, p)
        if peak > 0:
            worst = min(worst, p / peak - 1.0)
    return worst


def beta(asset_returns: Sequence[float], market_returns: Sequence[float]) -> float | None:
    """Covariance(asset, market) / Variance(market) over the overlapping tail."""
    n = min(len(asset_returns), len(market_returns))
    if n < 2:
        return None
    a = list(asset_returns[-n:])
    m = list(market_returns[-n:])
    var_m = statistics.pvariance(m)
    if var_m == 0:
        return None
    mean_a = statistics.fmean(a)
    mean_m = statistics.fmean(m)
    cov = sum((ai - mean_a) * (mi - mean_m) for ai, mi in zip(a, m, strict=True)) / n
    return cov / var_m


def cagr(start: float | None, end: float | None, years: float) -> float | None:
    """Compound annual growth rate. None unless both ends are positive."""
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return float((end / start) ** (1.0 / years)) - 1.0


def stdev_or_none(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return float(statistics.pstdev(values))
