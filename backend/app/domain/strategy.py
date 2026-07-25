"""v2 strategy fusion — raw signals → regime-weighted composite ranking.

The mirror of v1's ``scoring.py`` for the autonomous engine. Per metric, within its
cohort (sector-relative for valuation/fundamentals, universe-relative for the rest):
winsorize → z-score → percentile. Family = mean of its present metric scores; composite
= regime-weighted mean of present families. Pure and golden-testable — direction and
weights live here, raw values come from ``domain/signals``. Ranking is universe-wide.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean

from app.domain.cross_section import percentile_rank
from app.domain.signals.inputs import SIGNAL_FAMILIES

ENGINE_VERSION = "2.0.0"

# Metrics where a LOWER raw value is better. max_drawdown_1y is stored as a non-positive
# fraction (closer to 0 = shallower = better) so it is NOT inverse despite the "(inv)"
# label in the spec — same subtlety as v1.
INVERSE_METRICS: frozenset[str] = frozenset(
    {
        "ev_ebitda", "forward_pe", "peg", "price_to_book",  # valuation
        "debt_to_equity",  # fundamentals
        "atr_pct",  # technical
        "beta_distance", "vol_90d", "corr_to_holdings", "days_to_earnings",  # risk
    }
)

# Valuation & fundamentals are ranked within GICS sector; price-driven families are
# ranked across the whole universe (momentum/technical/risk aren't sector-idiosyncratic).
SECTOR_RELATIVE: frozenset[str] = frozenset({"valuation", "fundamentals"})

WEIGHTS_BY_REGIME: dict[str, dict[str, float]] = {
    "risk_on": {
        "valuation": 0.15, "fundamentals": 0.20, "momentum": 0.30,
        "technical": 0.20, "risk": 0.15,
    },
    "neutral": {
        "valuation": 0.20, "fundamentals": 0.25, "momentum": 0.20,
        "technical": 0.15, "risk": 0.20,
    },
    "risk_off": {
        "valuation": 0.25, "fundamentals": 0.30, "momentum": 0.10,
        "technical": 0.10, "risk": 0.25,
    },
}

# Entry gate constants (consumed by the R4 decision engine; defined here so the whole
# contract lives in one pure module).
MIN_COMPOSITE = 70.0
TOP_DECILE = 0.10
MIN_DATA_COMPLETENESS = 0.80

_ALL_METRICS = [m for names in SIGNAL_FAMILIES.values() for m in names]


@dataclass(frozen=True, slots=True)
class StrategyCompany:
    symbol: str
    sector: str
    signals: dict[str, dict[str, float | None]]  # family -> metric -> raw


@dataclass(frozen=True, slots=True)
class MetricDetail:
    raw: float | None
    score: float | None


@dataclass(frozen=True, slots=True)
class StrategyScore:
    symbol: str
    families: dict[str, float | None]
    composite: float | None
    rank: int | None
    data_completeness: float
    metric_details: dict[str, MetricDetail] = field(default_factory=dict)


def _cohort_key(family: str, sector: str) -> str:
    return sector if family in SECTOR_RELATIVE else "__ALL__"


def _family_score(scores: list[float], total_metrics: int) -> float | None:
    # Keep the family only if at least half its metrics are present (v1 parity).
    if len(scores) * 2 < total_metrics:
        return None
    return round(fmean(scores), 3) if scores else None


def _composite(families: dict[str, float | None], weights: dict[str, float]) -> float | None:
    present = {f: s for f, s in families.items() if s is not None}
    if not present:
        return None
    total_w = sum(weights[f] for f in present)
    if total_w == 0:
        return None
    return round(sum(present[f] * weights[f] for f in present) / total_w, 3)


def fuse_scores(companies: list[StrategyCompany], regime: str) -> list[StrategyScore]:
    """Rank a universe for the given regime. Returns scores with universe-wide ranks."""
    weights = WEIGHTS_BY_REGIME[regime]

    # (family, cohort) -> metric -> {symbol: percentile}
    ranked: dict[tuple[str, str], dict[str, dict[str, float]]] = defaultdict(dict)
    cohorts: dict[tuple[str, str], list[StrategyCompany]] = defaultdict(list)
    for c in companies:
        for family in SIGNAL_FAMILIES:
            cohorts[(family, _cohort_key(family, c.sector))].append(c)

    for (family, _cohort), group in cohorts.items():
        for metric in SIGNAL_FAMILIES[family]:
            present: dict[str, float] = {}
            for c in group:
                value = c.signals.get(family, {}).get(metric)
                if value is not None:
                    present[c.symbol] = value
            if present:
                ranked[(family, _cohort)][metric] = percentile_rank(
                    present, metric in INVERSE_METRICS
                )

    results: list[StrategyScore] = []
    for c in companies:
        details: dict[str, MetricDetail] = {}
        families: dict[str, float | None] = {}
        present_count = 0
        for family, metric_names in SIGNAL_FAMILIES.items():
            key = (family, _cohort_key(family, c.sector))
            fam_scores: list[float] = []
            for metric in metric_names:
                raw = c.signals.get(family, {}).get(metric)
                score = ranked.get(key, {}).get(metric, {}).get(c.symbol)
                details[metric] = MetricDetail(raw=raw, score=score)
                if score is not None:
                    fam_scores.append(score)
                    present_count += 1
            families[family] = _family_score(fam_scores, len(metric_names))
        results.append(
            StrategyScore(
                symbol=c.symbol,
                families=families,
                composite=_composite(families, weights),
                rank=None,
                data_completeness=round(present_count / len(_ALL_METRICS), 4),
                metric_details=details,
            )
        )

    # Universe-wide rank by composite (nulls last). rank 1 = best.
    ordered = sorted(
        results,
        key=lambda s: (s.composite is None, -(s.composite or 0.0)),
    )
    ranked_results: list[StrategyScore] = []
    for i, s in enumerate(ordered):
        rank = i + 1 if s.composite is not None else None
        ranked_results.append(
            StrategyScore(
                symbol=s.symbol, families=s.families, composite=s.composite, rank=rank,
                data_completeness=s.data_completeness, metric_details=s.metric_details,
            )
        )
    return ranked_results
