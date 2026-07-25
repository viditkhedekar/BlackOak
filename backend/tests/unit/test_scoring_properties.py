"""Property tests for invariants the scoring engine must always uphold."""

import random

from app.domain.factors import FACTOR_CATEGORIES
from app.domain.scoring import PROFILE_WEIGHTS, CompanyFactors, score_universe

_ALL_FACTORS = [f for fs in FACTOR_CATEGORIES.values() for f in fs]


def _random_universe(n: int, seed: int) -> list[CompanyFactors]:
    rng = random.Random(seed)
    sectors = ["Tech", "Health", "Energy"]
    comps = []
    for i in range(n):
        factors = {
            f: (rng.uniform(-1, 5) if rng.random() > 0.2 else None) for f in _ALL_FACTORS
        }
        comps.append(CompanyFactors(f"S{i}", rng.choice(sectors), factors))
    return comps


def test_all_scores_within_bounds() -> None:
    for cs in score_universe(_random_universe(40, seed=1), "balanced"):
        for cat, val in cs.categories.items():
            assert val is None or 0.0 <= val <= 100.0, cat
        assert cs.composite is None or 0.0 <= cs.composite <= 100.0
        for name, detail in cs.factor_details.items():
            assert detail.score is None or 0.0 <= detail.score <= 100.0, name


def test_profile_weights_sum_to_one() -> None:
    for profile, weights in PROFILE_WEIGHTS.items():
        assert set(weights) == set(FACTOR_CATEGORIES), profile
        assert abs(sum(weights.values()) - 1.0) < 1e-9, profile


def test_monotonic_in_a_direct_factor() -> None:
    # Raising one company's direct factor never lowers its percentile for that factor.
    base = [
        CompanyFactors("A", "Tech", {"roe": 0.10}),
        CompanyFactors("B", "Tech", {"roe": 0.20}),
        CompanyFactors("C", "Tech", {"roe": 0.30}),
    ]
    raised = [
        CompanyFactors("A", "Tech", {"roe": 0.40}),  # now the highest
        CompanyFactors("B", "Tech", {"roe": 0.20}),
        CompanyFactors("C", "Tech", {"roe": 0.30}),
    ]
    a_before = {c.symbol: c for c in score_universe(base, "balanced")}["A"]
    a_after = {c.symbol: c for c in score_universe(raised, "balanced")}["A"]
    assert a_after.factor_details["roe"].score >= a_before.factor_details["roe"].score


def test_empty_company_scores_to_none() -> None:
    comps = [CompanyFactors("EMPTY", "Tech", dict.fromkeys(_ALL_FACTORS, None))]
    result = score_universe(comps, "balanced")[0]
    assert result.composite is None
    assert result.data_completeness == 0.0
    assert all(v is None for v in result.categories.values())
