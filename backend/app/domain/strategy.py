"""v2 strategy fusion — raw signals → regime-weighted composite ranking.

The mirror of v1's ``scoring.py`` for the autonomous engine. Per metric, within its
cohort (sector-relative for valuation/fundamentals, universe-relative for the rest):
winsorize → z-score → percentile. Family = mean of its present metric scores; composite
= regime-weighted mean of present families. Pure and golden-testable — direction and
weights live here, raw values come from ``domain/signals``. Ranking is universe-wide.

Two units travel together and must not be confused. ``composite`` is a *mean of
percentiles*, so averaging collapses its spread to roughly 50 ± 7 — a composite of 70 is
a multi-sigma event, not "the 70th percentile". ``composite_percentile`` is that raw
composite ranked across the universe, which is the unit the entry/exit gates use so a
threshold of 70 means what it looks like: the top 30% of the cross-section.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import fmean

from app.domain.cross_section import percentile_rank
from app.domain.signals.inputs import SIGNAL_FAMILIES

ENGINE_VERSION = "2.1.0"

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
# contract lives in one pure module). MIN_COMPOSITE_PERCENTILE gates the *percentile*,
# never the raw composite — see the module docstring.
MIN_COMPOSITE_PERCENTILE = 70.0
TOP_DECILE = 0.10

# How much of the strategy's thesis the engine actually managed to evaluate, as the sum of
# the regime weights of the families that produced a score. This is the honest data gate:
# metrics missing scattered across families cost nothing (the family still scores, and the
# composite renormalizes), while a name with no valuation *or* fundamentals input at all is
# held out no matter how good its price action looks.
MIN_WEIGHT_COVERAGE = 0.70

# A far looser backstop on raw metric coverage, for a name that keeps all five families
# alive but only barely. The >=50% per-family rule in _family_score is the finer guard.
MIN_DATA_COMPLETENESS = 0.50

# A metric counts toward a cohort's completeness denominator only if this fraction of the
# cohort actually reports it. Below that it is inapplicable rather than missing: banks
# have no EBITDA or gross margin, and corr_to_holdings has no value until the book is
# non-empty. Charging a name for data its peers don't have either is what made
# insufficient_data fire on whole sectors.
METRIC_APPLICABILITY_MIN = 0.20

_NEUTRAL = 50.0


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
    composite: float | None  # weighted mean of family percentiles; clusters near 50
    rank: int | None
    data_completeness: float
    composite_percentile: float | None = None  # composite ranked universe-wide, 0-100
    weight_covered: float = 0.0  # regime weight of the families that scored
    metrics_present: int = 0
    metrics_applicable: int = 0
    metric_details: dict[str, MetricDetail] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FamilyContribution:
    """One family's pull on the composite, in composite points."""

    family: str
    score: float
    weight: float  # renormalized over present families
    contribution: float  # weight * (score - 50); negative = dragged the composite down


def _cohort_key(family: str, sector: str) -> str:
    return sector if family in SECTOR_RELATIVE else "__ALL__"


def _family_score(scores: list[float], applicable_metrics: int) -> float | None:
    """Keep the family only if at least half its *applicable* metrics are present.

    The denominator is the applicable count, not the catalogue size: a Financials cohort
    where 4 of the 9 fundamentals metrics are inapplicable can never reach 5-of-9, so a
    catalogue denominator would drop the family for every bank in the universe.
    """
    if applicable_metrics <= 0:
        return None
    if len(scores) * 2 < applicable_metrics:
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


def score_attribution(
    score: StrategyScore, weights: dict[str, float]
) -> list[FamilyContribution]:
    """Per-family pull on the composite, worst first — "which signals dragged this down".

    Contribution is the renormalized weight times the family's deviation from the neutral
    50, so the contributions sum to ``composite - 50``.
    """
    present = {f: s for f, s in score.families.items() if s is not None}
    total_w = sum(weights[f] for f in present)
    if total_w == 0:
        return []
    out = [
        FamilyContribution(
            family=f,
            score=s,
            weight=round(weights[f] / total_w, 4),
            contribution=round(weights[f] / total_w * (s - _NEUTRAL), 3),
        )
        for f, s in present.items()
    ]
    return sorted(out, key=lambda c: c.contribution)


def weakest_metrics(score: StrategyScore, limit: int = 3) -> list[tuple[str, float]]:
    """The individual metrics scoring below neutral, worst first."""
    below = [
        (m, d.score)
        for m, d in score.metric_details.items()
        if d.score is not None and d.score < _NEUTRAL
    ]
    below.sort(key=lambda pair: pair[1])
    return [(m, round(s, 3)) for m, s in below[:limit]]


def _applicable_metrics(
    cohorts: dict[tuple[str, str], list[StrategyCompany]],
) -> dict[tuple[str, str], set[str]]:
    """Per (family, cohort), the metrics enough of the cohort reports to be judged on."""
    applicable: dict[tuple[str, str], set[str]] = {}
    for key, group in cohorts.items():
        family = key[0]
        live: set[str] = set()
        for metric in SIGNAL_FAMILIES[family]:
            covered = sum(
                1 for c in group if c.signals.get(family, {}).get(metric) is not None
            )
            if group and covered / len(group) >= METRIC_APPLICABILITY_MIN:
                live.add(metric)
        applicable[key] = live
    return applicable


def fuse_scores(companies: list[StrategyCompany], regime: str) -> list[StrategyScore]:
    """Rank a universe for the given regime. Returns scores with universe-wide ranks."""
    weights = WEIGHTS_BY_REGIME[regime]

    # (family, cohort) -> metric -> {symbol: percentile}
    ranked: dict[tuple[str, str], dict[str, dict[str, float]]] = defaultdict(dict)
    cohorts: dict[tuple[str, str], list[StrategyCompany]] = defaultdict(list)
    for c in companies:
        for family in SIGNAL_FAMILIES:
            cohorts[(family, _cohort_key(family, c.sector))].append(c)

    applicable = _applicable_metrics(cohorts)

    for (family, cohort), group in cohorts.items():
        for metric in SIGNAL_FAMILIES[family]:
            present: dict[str, float] = {}
            for c in group:
                value = c.signals.get(family, {}).get(metric)
                if value is not None:
                    present[c.symbol] = value
            if present:
                ranked[(family, cohort)][metric] = percentile_rank(
                    present, metric in INVERSE_METRICS
                )

    results: list[StrategyScore] = []
    for c in companies:
        details: dict[str, MetricDetail] = {}
        families: dict[str, float | None] = {}
        present_count = 0
        applicable_count = 0
        for family, metric_names in SIGNAL_FAMILIES.items():
            key = (family, _cohort_key(family, c.sector))
            live = applicable.get(key, set())
            applicable_count += len(live)
            fam_scores: list[float] = []
            for metric in metric_names:
                raw = c.signals.get(family, {}).get(metric)
                score = ranked.get(key, {}).get(metric, {}).get(c.symbol)
                details[metric] = MetricDetail(raw=raw, score=score)
                if score is not None:
                    # A rare metric still informs the family score, but completeness is
                    # only ever measured against the applicable set so it stays in [0, 1].
                    fam_scores.append(score)
                    if metric in live:
                        present_count += 1
            families[family] = _family_score(fam_scores, len(live))
        results.append(
            StrategyScore(
                symbol=c.symbol,
                families=families,
                composite=_composite(families, weights),
                rank=None,
                data_completeness=(
                    round(present_count / applicable_count, 4) if applicable_count else 0.0
                ),
                weight_covered=round(
                    sum(weights[f] for f, s in families.items() if s is not None), 4
                ),
                metrics_present=present_count,
                metrics_applicable=applicable_count,
                metric_details=details,
            )
        )

    # Rank the composite across the universe so the gates get an honest 0-100 unit. The
    # mapping is monotone, so this cannot disagree with `rank` below.
    scored = {s.symbol: s.composite for s in results if s.composite is not None}
    pct_by_symbol = percentile_rank(scored, inverse=False) if scored else {}

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
                data_completeness=s.data_completeness,
                composite_percentile=pct_by_symbol.get(s.symbol),
                weight_covered=s.weight_covered,
                metrics_present=s.metrics_present,
                metrics_applicable=s.metrics_applicable,
                metric_details=s.metric_details,
            )
        )
    return ranked_results
