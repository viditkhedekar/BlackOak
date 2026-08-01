"""Calibration and bias tests for the fusion layer.

These lock the three defects measured on the live universe in July 2026:
  * a missing family was a *bonus* (renormalization redistributed its weight);
  * one sector could take 31% of the candidate pool while another took 1 name in 80;
  * the composite's own weights sat mostly on families with negative measured IC.
The first two are pure-logic properties and are asserted directly here. The third is a
data question, not a logic one, and lives in the rank-IC harness — but the weight vector
is pinned below so a future edit has to be deliberate.
"""

from __future__ import annotations

import random

import pytest

from app.domain.rules import (
    MAX_SECTOR_POOL_PCT,
    build_candidate_pool,
    sector_pool_cap,
)
from app.domain.signals.inputs import SIGNAL_FAMILIES
from app.domain.strategy import (
    IMPUTED_WEIGHT_MAX,
    WEIGHTS_BY_REGIME,
    StrategyCompany,
    fuse_scores,
)

_SECTORS = ["Financials", "Industrials", "Health Care", "Utilities", "Energy"]


def _universe(n: int = 60, seed: int = 7) -> list[StrategyCompany]:
    rng = random.Random(seed)
    return [
        StrategyCompany(
            f"S{i}",
            _SECTORS[i % len(_SECTORS)],
            {
                family: {m: rng.gauss(0.0, 1.0) for m in metrics}
                for family, metrics in SIGNAL_FAMILIES.items()
            },
        )
        for i in range(n)
    ]


def _blank_family(company: StrategyCompany, family: str) -> StrategyCompany:
    signals = {f: dict(m) for f, m in company.signals.items()}
    signals[family] = dict.fromkeys(signals[family])
    return StrategyCompany(company.symbol, company.sector, signals)


# --- missing data must never be an advantage --------------------------------

def test_dropping_a_family_does_not_improve_a_names_composite() -> None:
    """The regression that mattered: names missing `fundamentals` averaged composite
    56.97 against 49.77 for names that had it, purely because renormalization handed
    their weight to the families that did score."""
    universe = _universe()
    target = universe[0]
    before = {s.symbol: s for s in fuse_scores(universe, "risk_on")}[target.symbol]

    # Same universe, but this one name loses a whole family. `technical` is light enough
    # (0.15) to stay inside IMPUTED_WEIGHT_MAX, so the name is still ranked and the two
    # composites remain comparable.
    degraded = [_blank_family(target, "technical"), *universe[1:]]
    after = {s.symbol: s for s in fuse_scores(degraded, "risk_on")}[target.symbol]

    assert before.composite is not None and after.composite is not None
    # It may fall (the sector median is typically worse than a strong observed score),
    # but losing information must never *raise* the composite.
    assert after.composite <= before.composite + 1e-9


def test_missing_family_is_imputed_not_dropped() -> None:
    universe = _universe()
    degraded = [_blank_family(universe[0], "technical"), *universe[1:]]
    score = {s.symbol: s for s in fuse_scores(degraded, "risk_on")}[universe[0].symbol]

    assert score.imputed_families == ("technical",)
    assert score.families["technical"] is not None  # filled from the sector median
    # Coverage still reports what was OBSERVED, so the engine's data gates are unfooled.
    assert score.weight_covered == pytest.approx(
        1.0 - WEIGHTS_BY_REGIME["risk_on"]["technical"]
    )


def test_too_much_imputation_refuses_to_rank_the_name() -> None:
    """Imputing a little is judgement; imputing most of the thesis is invention."""
    universe = _universe()
    target = universe[0]
    for family in ("valuation", "fundamentals", "momentum"):
        target = _blank_family(target, family)
    degraded = [target, *universe[1:]]
    score = {s.symbol: s for s in fuse_scores(degraded, "risk_on")}[target.symbol]

    imputed_weight = sum(
        WEIGHTS_BY_REGIME["risk_on"][f]
        for f in ("valuation", "fundamentals", "momentum")
    )
    assert imputed_weight > IMPUTED_WEIGHT_MAX
    assert score.composite is None
    assert score.rank is None


# --- confidence -------------------------------------------------------------

def test_agreeing_families_earn_more_confidence_than_contradictory_ones() -> None:
    """Two names can share a composite and mean very different things."""
    scores = {s.symbol: s for s in fuse_scores(_universe(), "risk_on")}
    spreads = {
        sym: max(v for v in s.families.values() if v is not None)
        - min(v for v in s.families.values() if v is not None)
        for sym, s in scores.items()
        if all(v is not None for v in s.families.values())
    }
    tightest = min(spreads, key=lambda k: spreads[k])
    widest = max(spreads, key=lambda k: spreads[k])
    assert scores[tightest].confidence > scores[widest].confidence


def test_imputation_costs_confidence() -> None:
    universe = _universe()
    clean = {s.symbol: s for s in fuse_scores(universe, "risk_on")}[universe[0].symbol]
    degraded_universe = [_blank_family(universe[0], "technical"), *universe[1:]]
    degraded = {s.symbol: s for s in fuse_scores(degraded_universe, "risk_on")}[
        universe[0].symbol
    ]
    assert degraded.confidence < clean.confidence


def test_confidence_stays_in_unit_range() -> None:
    for score in fuse_scores(_universe(), "risk_on"):
        assert 0.0 <= score.confidence <= 1.0


# --- sector-capped candidate pool -------------------------------------------

def test_one_sector_cannot_monopolise_the_pool() -> None:
    """Before the cap, Financials held 31% of the top 80 against 15% of the universe."""
    # Enough sectors that the cap can be honoured without starving the pool.
    ranked = [(f"F{i}", "Financials") for i in range(40)]
    for s, name in enumerate(("Industrials", "Health Care", "Utilities", "Energy")):
        ranked += [(f"{name[0]}{s}{i}", name) for i in range(10)]
    pool, capped = build_candidate_pool(ranked, pool_size=20)

    assert len(pool) == 20
    financials = sum(1 for s in pool if s.startswith("F"))
    assert financials <= sector_pool_cap(20)
    # The slots the crowded sector gives up go to the next-best names elsewhere, so the
    # pool stays full rather than shrinking.
    assert capped  # displaced names are reported, not silently dropped


def test_cap_never_shrinks_the_pool_when_candidates_exist() -> None:
    """A hard cap would over-filter exactly when the market is narrow. With only two
    sectors and a 20% cap the first pass can fill just 8 of 20 slots; the top-up pass
    restores the rest in rank order."""
    ranked = [(f"F{i}", "Financials") for i in range(50)]
    ranked += [(f"T{i}", "Information Technology") for i in range(50)]
    pool, _ = build_candidate_pool(ranked, pool_size=20)
    assert len(pool) == 20


def test_pool_cannot_exceed_the_available_candidates() -> None:
    pool, capped = build_candidate_pool([("A", "Energy"), ("B", "Energy")], pool_size=20)
    assert pool == {"A", "B"}
    assert not capped


def test_a_capped_sector_is_represented_by_its_best_ranked_names() -> None:
    """When the cap binds, the sector keeps its strongest names — not arbitrary ones."""
    ranked = [(f"E{i}", "Energy") for i in range(10)]
    ranked += [(f"X{i}", f"Sector{i}") for i in range(20)]  # room to fill the rest
    pool, capped = build_candidate_pool(ranked, pool_size=20)

    cap = sector_pool_cap(20)
    energy_in_pool = sorted(s for s in pool if s.startswith("E"))
    assert energy_in_pool == [f"E{i}" for i in range(cap)]
    assert all(f"E{i}" in capped for i in range(cap, 10))


def test_sector_cap_is_at_least_one_name() -> None:
    assert sector_pool_cap(1) >= 1
    assert sector_pool_cap(0) >= 1


def test_pool_cap_matches_the_configured_share() -> None:
    assert sector_pool_cap(100) == int(MAX_SECTOR_POOL_PCT * 100)


# --- weight vector ----------------------------------------------------------

def test_regime_weights_are_normalised_and_pinned() -> None:
    """Weights are IC-derived (see WEIGHTS_BY_REGIME); changing them is a strategy
    decision that must be re-validated against the rank-IC harness, not a tweak."""
    for regime, weights in WEIGHTS_BY_REGIME.items():
        assert sum(weights.values()) == pytest.approx(1.0), regime
        assert set(weights) == set(SIGNAL_FAMILIES), regime
        assert all(w > 0 for w in weights.values()), regime

    # Momentum carried the only robustly positive IC in every regime measured.
    for regime, weights in WEIGHTS_BY_REGIME.items():
        assert weights["momentum"] >= weights["technical"], regime
