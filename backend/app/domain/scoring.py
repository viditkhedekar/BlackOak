"""Deterministic scoring pipeline (docs/SCHEMA.md §7) — the platform's brain.

For each factor, within each sector: winsorize (1/99) → z-score → map to a 0-100
percentile via the normal CDF. A category is the mean of its available factor scores;
the composite is a risk-profile-weighted mean of the available categories. Pure and
fully golden-testable — no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import NormalDist, fmean, pstdev

from app.domain.factors import FACTOR_CATEGORIES

ENGINE_VERSION = "1.0.0"

# Factors where a LOWER raw value is better (everything else: higher is better).
# Directions are defined against the raw representation produced by factors.py —
# note max_drawdown_1y is stored as a non-positive fraction, so higher (closer to 0)
# is better and it is therefore NOT inverse here despite the spec's "(inv)" label.
INVERSE_FACTORS: frozenset[str] = frozenset(
    {
        "debt_to_equity",
        "ev_ebitda",
        "price_to_book",
        "gross_margin_stability",
        "accruals_ratio",
        "vol_252d",
        "vol_90d",
        "beta_distance",
        "downside_deviation",
        "net_debt_ebitda",
    }
)

PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "conservative": {
        "financial_health": 0.18, "quality": 0.18, "risk": 0.19, "value": 0.12,
        "profitability": 0.12, "volatility": 0.09, "growth": 0.06, "momentum": 0.06,
    },
    "balanced": {cat: 0.125 for cat in FACTOR_CATEGORIES},
    "aggressive": {
        "growth": 0.24, "momentum": 0.21, "value": 0.12, "profitability": 0.12,
        "quality": 0.08, "financial_health": 0.07, "risk": 0.08, "volatility": 0.08,
    },
}

_NEUTRAL = 50.0
_NORM = NormalDist()


@dataclass(frozen=True, slots=True)
class CompanyFactors:
    symbol: str
    sector: str
    factors: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class FactorDetail:
    raw: float | None
    score: float | None  # 0-100 sector percentile (direction-adjusted)


@dataclass(frozen=True, slots=True)
class CompanyScore:
    symbol: str
    categories: dict[str, float | None]
    composite: float | None
    data_completeness: float
    factor_details: dict[str, FactorDetail] = field(default_factory=dict)


def _quantile(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] + frac * (sorted_vals[lo + 1] - sorted_vals[lo])


def _winsorize(values: list[float], lo: float = 0.01, hi: float = 0.99) -> list[float]:
    ordered = sorted(values)
    low, high = _quantile(ordered, lo), _quantile(ordered, hi)
    return [min(max(v, low), high) for v in values]


def _percentile_from_z(z: float) -> float:
    return round(_NORM.cdf(z) * 100.0, 3)


def _score_factor_in_group(
    values_by_symbol: dict[str, float], inverse: bool
) -> dict[str, float]:
    """Winsorize → z-score → normal-CDF percentile for one factor in one sector."""
    symbols = list(values_by_symbol.keys())
    winsorized = _winsorize([values_by_symbol[s] for s in symbols])
    mean = fmean(winsorized)
    sd = pstdev(winsorized)
    if sd == 0:
        return dict.fromkeys(symbols, _NEUTRAL)
    out: dict[str, float] = {}
    for sym, wv in zip(symbols, winsorized, strict=True):
        z = (wv - mean) / sd
        if inverse:
            z = -z
        out[sym] = _percentile_from_z(z)
    return out


def _category_score(scores: list[float], total_factors: int) -> float | None:
    # Keep the category only if at least half its factors are present.
    if len(scores) * 2 < total_factors:
        return None
    return round(fmean(scores), 3) if scores else None


def _composite(categories: dict[str, float | None], weights: dict[str, float]) -> float | None:
    present = {c: s for c, s in categories.items() if s is not None}
    if not present:
        return None
    total_w = sum(weights[c] for c in present)
    if total_w == 0:
        return None
    return round(sum(present[c] * weights[c] for c in present) / total_w, 3)


def score_universe(companies: list[CompanyFactors], profile: str) -> list[CompanyScore]:
    """Rank a universe cross-sectionally within each sector for the given risk profile."""
    weights = PROFILE_WEIGHTS[profile]
    all_factors = [f for factors in FACTOR_CATEGORIES.values() for f in factors]

    # sector -> factor -> {symbol: percentile}
    scored: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    by_sector: dict[str, list[CompanyFactors]] = defaultdict(list)
    for c in companies:
        by_sector[c.sector].append(c)

    for sector, group in by_sector.items():
        for factor in all_factors:
            present: dict[str, float] = {}
            for c in group:
                value = c.factors.get(factor)
                if value is not None:
                    present[c.symbol] = value
            if present:
                scored[sector][factor] = _score_factor_in_group(
                    present, factor in INVERSE_FACTORS
                )

    results: list[CompanyScore] = []
    for c in companies:
        factor_scores = scored.get(c.sector, {})
        details: dict[str, FactorDetail] = {}
        categories: dict[str, float | None] = {}
        present_count = 0
        for category, factor_names in FACTOR_CATEGORIES.items():
            cat_scores: list[float] = []
            for name in factor_names:
                raw = c.factors.get(name)
                score = factor_scores.get(name, {}).get(c.symbol)
                details[name] = FactorDetail(raw=raw, score=score)
                if score is not None:
                    cat_scores.append(score)
                    present_count += 1
            categories[category] = _category_score(cat_scores, len(factor_names))
        results.append(
            CompanyScore(
                symbol=c.symbol,
                categories=categories,
                composite=_composite(categories, weights),
                data_completeness=round(present_count / len(all_factors), 4),
                factor_details=details,
            )
        )
    return results
