"""Golden-file tests: fixed inputs → exact expected scores.

These are the regression lock for the scoring engine. Changing any number here must
be a deliberate act accompanied by an ENGINE_VERSION bump (docs/ROADMAP.md Phase 2 gate).
"""

import math

from app.domain.scoring import CompanyFactors, score_universe

# Evenly-spaced 3-company sector: hand-verifiable z-scores.
#   roe (direct):        A=0.30 B=0.10 C=0.20  → mean .20, pstdev .081650
#   vol_252d (inverse):  A=0.20 B=0.40 C=0.30  → A best (lowest)
# z(best)=+1.22474 → Φ=0.88966 → 88.966 ; z(median)=0 → 50 ; z(worst) → 11.034
_TOY = [
    CompanyFactors("A", "Tech", {"roe": 0.30, "vol_252d": 0.20}),
    CompanyFactors("B", "Tech", {"roe": 0.10, "vol_252d": 0.40}),
    CompanyFactors("C", "Tech", {"roe": 0.20, "vol_252d": 0.30}),
]


def test_golden_percentiles_and_direction() -> None:
    scores = {cs.symbol: cs for cs in score_universe(_TOY, "balanced")}

    # Direct factor: highest roe → highest score.
    assert scores["A"].factor_details["roe"].score == 88.966
    assert scores["C"].factor_details["roe"].score == 50.0
    assert scores["B"].factor_details["roe"].score == 11.034

    # Inverse factor: lowest vol → highest score.
    assert scores["A"].factor_details["vol_252d"].score == 88.966
    assert scores["B"].factor_details["vol_252d"].score == 11.034


def test_golden_category_and_completeness() -> None:
    scores = {cs.symbol: cs for cs in score_universe(_TOY, "balanced")}

    # profitability has 1/4 factors present (<50%) → dropped.
    assert scores["A"].categories["profitability"] is None
    # volatility has 1/2 present (>=50%) → kept.
    assert scores["A"].categories["volatility"] == 88.966
    # composite = only surviving category (volatility).
    assert scores["A"].composite == 88.966
    assert scores["A"].data_completeness == round(2 / 30, 4)


def test_symmetry_of_normal_cdf_mapping() -> None:
    scores = {cs.symbol: cs for cs in score_universe(_TOY, "balanced")}
    best = scores["A"].factor_details["roe"].score
    worst = scores["B"].factor_details["roe"].score
    assert best is not None and worst is not None
    assert math.isclose(best + worst, 100.0, abs_tol=0.01)


def test_zero_variance_group_is_neutral() -> None:
    same = [
        CompanyFactors("X", "Tech", {"roe": 0.15}),
        CompanyFactors("Y", "Tech", {"roe": 0.15}),
    ]
    for cs in score_universe(same, "balanced"):
        assert cs.factor_details["roe"].score == 50.0


def test_profiles_reweight_composite() -> None:
    # HG dominates growth + momentum; LG dominates financial_health + risk.
    # Full categories so none are dropped by the >50%-missing rule.
    growth = {"revenue_cagr_3y", "eps_cagr_3y", "fcf_growth_3y", "revenue_acceleration"}
    momentum = {"ret_12_1", "ret_6m", "pct_above_200dma", "high_52w_proximity"}
    health = {"current_ratio", "debt_to_equity", "interest_coverage", "altman_z"}
    risk = {"max_drawdown_1y", "beta_distance", "downside_deviation", "net_debt_ebitda"}

    def make(strong: set[str], weak: set[str]) -> dict[str, float]:
        return {**dict.fromkeys(strong, 0.9), **dict.fromkeys(weak, 0.1)}

    comps = [
        CompanyFactors("HG", "Tech", make(growth | momentum, health | risk)),
        CompanyFactors("LG", "Tech", make(health | risk, growth | momentum)),
    ]
    aggressive = {cs.symbol: cs for cs in score_universe(comps, "aggressive")}
    conservative = {cs.symbol: cs for cs in score_universe(comps, "conservative")}

    assert aggressive["HG"].composite is not None
    assert conservative["HG"].composite is not None
    # Growth/momentum are weighted far higher under aggressive → HG scores better there.
    assert aggressive["HG"].composite > conservative["HG"].composite
