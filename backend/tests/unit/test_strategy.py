"""Tests for the v2 fusion (strategy.py) and regime classifier (regime.py)."""

from __future__ import annotations

import random
from itertools import pairwise

from app.domain.regime import (
    NEUTRAL,
    RISK_OFF,
    RISK_ON,
    RegimeFeatures,
    classify_raw,
    confirmed_regime,
    resolve,
)
from app.domain.signals.inputs import SIGNAL_FAMILIES
from app.domain.strategy import (
    MIN_COMPOSITE_PERCENTILE,
    MIN_DATA_COMPLETENESS,
    MIN_WEIGHT_COVERAGE,
    WEIGHTS_BY_REGIME,
    StrategyCompany,
    fuse_scores,
    score_attribution,
    weakest_metrics,
)

_SECTORS = ["Tech", "Health", "Financials", "Energy", "Staples"]


def _universe(n: int = 500, seed: int = 7) -> list[StrategyCompany]:
    """A realistically correlated cross-section: each name has a latent quality that all
    its metrics load on, plus idiosyncratic noise."""
    rng = random.Random(seed)
    companies = []
    for i in range(n):
        latent = rng.gauss(0.0, 1.0)
        signals = {
            family: {m: latent * 0.6 + rng.gauss(0.0, 0.8) for m in metrics}
            for family, metrics in SIGNAL_FAMILIES.items()
        }
        companies.append(StrategyCompany(f"S{i}", _SECTORS[i % len(_SECTORS)], signals))
    return companies


def _company(symbol: str, sector: str, bump: float) -> StrategyCompany:
    """A company whose every metric is a constant offset — higher bump = better raw
    (except inverse metrics, handled by direction). Enough spread across companies to
    make z-scores non-degenerate."""
    signals = {
        family: {metric: bump for metric in metrics}
        for family, metrics in SIGNAL_FAMILIES.items()
    }
    return StrategyCompany(symbol=symbol, sector=sector, signals=signals)


# --- fusion ---------------------------------------------------------------

def test_weights_sum_to_one_each_regime() -> None:
    for regime, weights in WEIGHTS_BY_REGIME.items():
        assert abs(sum(weights.values()) - 1.0) < 1e-9, regime
        assert set(weights) == set(SIGNAL_FAMILIES)


def test_scores_bounded_and_ranked() -> None:
    companies = [_company(f"S{i}", "Tech", float(i)) for i in range(10)]
    scores = fuse_scores(companies, "neutral")
    for s in scores:
        assert s.composite is not None
        assert 0.0 <= s.composite <= 100.0
        for fam in s.families.values():
            assert fam is None or 0.0 <= fam <= 100.0
    ranks = sorted(s.rank for s in scores)
    assert ranks == list(range(1, 11))  # dense 1..N, no gaps


def test_rank_follows_composite() -> None:
    companies = [_company(f"S{i}", "Tech", float(i)) for i in range(10)]
    scores = {s.symbol: s for s in fuse_scores(companies, "neutral")}
    best = min(scores.values(), key=lambda s: s.rank or 999)
    # S9 has the highest raw across all non-inverse metrics → should rank at or near top.
    assert best.symbol in {"S9", "S8"}


def test_empty_family_when_all_metrics_missing() -> None:
    companies = []
    for i in range(5):
        sig = {family: {m: float(i) for m in ms} for family, ms in SIGNAL_FAMILIES.items()}
        sig["valuation"] = {m: None for m in SIGNAL_FAMILIES["valuation"]}
        companies.append(StrategyCompany(f"S{i}", "Tech", sig))
    scores = fuse_scores(companies, "neutral")
    assert all(s.families["valuation"] is None for s in scores)
    # Composite still computes from the remaining families.
    assert all(s.composite is not None for s in scores)


def test_regime_reweighting_changes_composite() -> None:
    # Two companies that differ only in momentum vs fundamentals strength.
    momentum_star = StrategyCompany(
        "MOM", "Tech",
        {f: {m: (9.0 if f == "momentum" else 1.0) for m in ms}
         for f, ms in SIGNAL_FAMILIES.items()},
    )
    fundamentals_star = StrategyCompany(
        "FUN", "Tech",
        {f: {m: (9.0 if f == "fundamentals" else 1.0) for m in ms}
         for f, ms in SIGNAL_FAMILIES.items()},
    )
    pair = [momentum_star, fundamentals_star]
    on = {s.symbol: s.composite for s in fuse_scores(pair, "risk_on")}
    off = {s.symbol: s.composite for s in fuse_scores(pair, "risk_off")}
    # Risk-on over-weights momentum; risk-off over-weights fundamentals.
    assert on["MOM"] > off["MOM"]
    assert off["FUN"] > on["FUN"]


# --- calibration: the gate's unit must match the gate's threshold ----------

def test_raw_composite_clusters_near_neutral() -> None:
    """The composite is a MEAN of percentiles, so averaging collapses its spread.

    This pins the property that made an absolute threshold of 70 unreachable: with 30
    metrics the composite concentrates near 50 and never approaches the extremes. Any
    future gate compared against the raw composite has to respect this scale."""
    scores = fuse_scores(_universe(), "neutral")
    composites = [s.composite for s in scores if s.composite is not None]
    assert len(composites) == 500
    assert max(composites) < 70.0  # the old MIN_COMPOSITE, mathematically out of reach
    assert 45.0 < sum(composites) / len(composites) < 55.0


def test_composite_percentile_spans_the_full_range() -> None:
    scores = fuse_scores(_universe(), "neutral")
    pcts = [s.composite_percentile for s in scores if s.composite_percentile is not None]
    assert len(pcts) == 500
    assert min(pcts) < 5.0 and max(pcts) > 95.0


def test_min_composite_percentile_admits_a_slice_in_every_regime() -> None:
    """The regression lock for the calibration bug.

    The entry gate must admit a workable candidate pool in every regime. Before the fix
    zero names cleared it in all three, so the journal collapsed onto one reason code."""
    for regime in WEIGHTS_BY_REGIME:
        scores = fuse_scores(_universe(), regime)
        passing = [
            s for s in scores
            if s.composite_percentile is not None
            and s.composite_percentile >= MIN_COMPOSITE_PERCENTILE
        ]
        # ~30% of the universe by construction; allow slack for the normal-CDF mapping.
        assert 100 <= len(passing) <= 200, f"{regime}: {len(passing)} passed"


def test_composite_percentile_agrees_with_rank_ordering() -> None:
    """The percentile is a monotone transform of the composite, so it cannot contradict
    the rank the engine sorts on."""
    scores = [s for s in fuse_scores(_universe(n=120), "risk_on") if s.rank is not None]
    by_rank = sorted(scores, key=lambda s: s.rank or 0)
    pcts = [s.composite_percentile for s in by_rank]
    # Non-strict: winsorizing at 1/99 clamps the tails, so the extremes tie rather than
    # strictly decreasing.
    assert all(
        a is not None and b is not None and a >= b for a, b in pairwise(pcts)
    )


# --- completeness measures applicable metrics ------------------------------

def _with_missing(missing: dict[str, list[str]], sectors: set[str] | None = None,
                  n: int = 40) -> list[StrategyCompany]:
    """Universe where `missing` metrics are None — for every name, or only in `sectors`."""
    rng = random.Random(3)
    companies = []
    for i in range(n):
        sector = _SECTORS[i % len(_SECTORS)]
        signals: dict[str, dict[str, float | None]] = {
            family: {m: rng.gauss(0.0, 1.0) for m in metrics}
            for family, metrics in SIGNAL_FAMILIES.items()
        }
        if sectors is None or sector in sectors:
            for family, metrics in missing.items():
                for m in metrics:
                    signals[family][m] = None
        companies.append(StrategyCompany(f"S{i}", sector, signals))
    return companies


def test_universally_absent_metric_leaves_the_denominator() -> None:
    """corr_to_holdings and days_to_earnings are never populated, so charging every name
    for them capped completeness below the 0.80 floor no matter how good the data was."""
    full = fuse_scores(_with_missing({}), "neutral")
    assert all(s.metrics_applicable == 30 for s in full)
    assert all(s.data_completeness == 1.0 for s in full)

    starved = fuse_scores(
        _with_missing({"risk": ["corr_to_holdings", "days_to_earnings"]}), "neutral"
    )
    assert all(s.metrics_applicable == 28 for s in starved)
    assert all(s.data_completeness == 1.0 for s in starved)


def test_sector_inapplicable_metric_only_excused_for_that_sector() -> None:
    """Banks have no EBITDA or gross margin. That is inapplicable, not missing — and it
    must not excuse the same gap in a sector whose peers do report it."""
    scores = {
        s.symbol: s
        for s in fuse_scores(
            _with_missing(
                {"valuation": ["ev_ebitda"], "fundamentals": ["gross_margin"]},
                sectors={"Financials"},
            ),
            "neutral",
        )
    }
    banks = [s for sym, s in scores.items() if int(sym[1:]) % len(_SECTORS) == 2]
    others = [s for sym, s in scores.items() if int(sym[1:]) % len(_SECTORS) != 2]

    assert banks and others
    # Both families are sector-relative, so the two metrics leave only the bank cohort.
    assert all(s.metrics_applicable == 28 for s in banks)
    assert all(s.metrics_applicable == 30 for s in others)
    # And nobody is penalised: every name has all of what its own peers have.
    assert all(s.data_completeness == 1.0 for s in scores.values())
    assert all(s.data_completeness >= MIN_DATA_COMPLETENESS for s in banks)


def test_weight_covered_tracks_the_families_that_scored() -> None:
    """weight_covered is what the data gate compares against: the share of the strategy's
    thesis the engine could actually evaluate."""
    full = fuse_scores(_with_missing({}), "neutral")
    assert all(abs(s.weight_covered - 1.0) < 1e-9 for s in full)

    # Wipe valuation for everyone → the family is dropped and its weight goes uncovered.
    no_valuation = fuse_scores(
        _with_missing({"valuation": SIGNAL_FAMILIES["valuation"]}), "neutral"
    )
    expected = 1.0 - WEIGHTS_BY_REGIME["neutral"]["valuation"]
    assert all(abs(s.weight_covered - expected) < 1e-9 for s in no_valuation)
    assert all(s.families["valuation"] is None for s in no_valuation)


def test_bank_shaped_name_falls_below_the_coverage_floor() -> None:
    """The JPM case end to end.

    Banks report no EBITDA, gross margin, FCF or interest coverage, but they share the
    Financials sector with payment networks that report all of them — so GICS sector is
    too coarse a cohort to excuse the gap, and a flat metric-count floor misfires on
    exactly this name. Weight coverage gets it right: both fundamental families collapse,
    so the name is held out rather than waved through on momentum alone.
    """
    rng = random.Random(11)
    bank_gaps = {
        "valuation": ["ev_ebitda", "fcf_yield", "price_to_book", "forward_pe"],
        "fundamentals": ["gross_margin", "operating_margin", "roic", "interest_coverage",
                         "ebit_growth_3y"],
    }
    companies = []
    for i in range(40):
        sector = _SECTORS[i % len(_SECTORS)]
        signals: dict[str, dict[str, float | None]] = {
            family: {m: rng.gauss(0.0, 1.0) for m in metrics}
            for family, metrics in SIGNAL_FAMILIES.items()
        }
        # A minority of the Financials cohort; its peers still report everything.
        is_bank = sector == "Financials" and i % 15 == 2
        if is_bank:
            for family, metrics in bank_gaps.items():
                for m in metrics:
                    signals[family][m] = None
        companies.append(
            StrategyCompany(f"{'BANK' if is_bank else 'S'}{i}", sector, signals)
        )

    scores = fuse_scores(companies, "risk_on")
    banks = [s for s in scores if s.symbol.startswith("BANK")]
    peers = [s for s in scores if not s.symbol.startswith("BANK")]
    assert banks and peers

    # The metrics stay applicable (the cohort's payment networks report them), so both
    # families fall under the >=50% rule. They are no longer dropped — dropping them
    # renormalized the remaining weight and paid the name a bonus for its own data gap —
    # they are imputed from the sector median and flagged.
    assert all(set(s.imputed_families) == {"valuation", "fundamentals"} for s in banks)
    assert all(s.families["valuation"] is not None for s in banks)
    assert all(s.families["fundamentals"] is not None for s in banks)
    assert all(not s.imputed_families for s in peers)

    # The name is still held out rather than waved through on momentum alone: coverage
    # reports OBSERVED weight only, and 0.15 + 0.20 of imputed weight breaches the cap,
    # so the composite refuses to rank it at all.
    assert all(s.weight_covered < MIN_WEIGHT_COVERAGE for s in banks)
    assert all(abs(s.weight_covered - 1.0) < 1e-9 for s in peers)
    assert all(s.composite is None for s in banks)
    assert all(s.composite is not None for s in peers)


def test_family_survives_when_half_its_applicable_metrics_are_present() -> None:
    """The >=50% family rule counts applicable metrics, not the catalogue.

    Against the catalogue a Financials cohort missing 4 of 9 fundamentals could never
    reach 5-of-9, so the family would be dropped for every bank in the universe."""
    inapplicable = ["ev_ebitda", "forward_pe", "peg"]  # 3 of 5 valuation metrics
    scores = fuse_scores(
        _with_missing({"valuation": inapplicable}, sectors={"Financials"}), "neutral"
    )
    banks = [s for s in scores if int(s.symbol[1:]) % len(_SECTORS) == 2]
    assert banks
    # 2 applicable, 2 present → survives. Against the catalogue it would be 2 of 5 → None.
    assert all(s.families["valuation"] is not None for s in banks)


def test_completeness_is_zero_when_nothing_is_reported() -> None:
    empty = [
        StrategyCompany(
            f"S{i}", "Tech",
            {f: {m: None for m in ms} for f, ms in SIGNAL_FAMILIES.items()},
        )
        for i in range(5)
    ]
    scores = fuse_scores(empty, "neutral")
    assert all(s.data_completeness == 0.0 for s in scores)
    assert all(s.composite is None and s.composite_percentile is None for s in scores)
    assert all(s.rank is None for s in scores)


# --- attribution: which signals pulled it down -----------------------------

def test_attribution_orders_worst_family_first_and_sums_to_deviation() -> None:
    weak_momentum = StrategyCompany(
        "WEAK", "Tech",
        {f: {m: (0.0 if f == "momentum" else 9.0) for m in ms}
         for f, ms in SIGNAL_FAMILIES.items()},
    )
    peers = [_company(f"P{i}", "Tech", float(i)) for i in range(1, 10)]
    scores = {s.symbol: s for s in fuse_scores([weak_momentum, *peers], "risk_on")}

    contributions = score_attribution(scores["WEAK"], WEIGHTS_BY_REGIME["risk_on"])
    assert contributions[0].family == "momentum"
    assert contributions[0].contribution < 0
    # Contributions decompose the composite's distance from neutral.
    total = sum(c.contribution for c in contributions)
    assert abs(total - ((scores["WEAK"].composite or 0.0) - 50.0)) < 0.05


def test_weakest_metrics_reports_only_below_neutral_worst_first() -> None:
    weak_momentum = StrategyCompany(
        "WEAK", "Tech",
        {f: {m: (0.0 if f == "momentum" else 9.0) for m in ms}
         for f, ms in SIGNAL_FAMILIES.items()},
    )
    peers = [_company(f"P{i}", "Tech", float(i)) for i in range(1, 10)]
    scores = {s.symbol: s for s in fuse_scores([weak_momentum, *peers], "risk_on")}

    worst = weakest_metrics(scores["WEAK"], limit=5)
    assert worst, "a name this weak must report detractors"
    assert all(score < 50.0 for _, score in worst)
    assert [s for _, s in worst] == sorted(s for _, s in worst)
    assert all(m in SIGNAL_FAMILIES["momentum"] for m, _ in worst)


# --- regime ---------------------------------------------------------------

def _feat(vix: float, curve: float, spy: float, breadth: float) -> RegimeFeatures:
    return RegimeFeatures(
        vix_level=vix, vix_slope_10d=0.0, t10y2y=curve, spy_vs_200dma=spy, breadth=breadth
    )


def test_classify_risk_off_when_three_bearish() -> None:
    # elevated VIX, inverted curve, SPY below 200dma, healthy breadth (3 bearish)
    label, count, _ = classify_raw(_feat(vix=30, curve=-0.2, spy=-0.05, breadth=0.7))
    assert label == RISK_OFF
    assert count == 3


def test_classify_risk_on_when_calm() -> None:
    label, count, _ = classify_raw(_feat(vix=13, curve=0.5, spy=0.08, breadth=0.7))
    assert label == RISK_ON
    assert count == 0


def test_classify_neutral_when_two_bearish() -> None:
    label, count, _ = classify_raw(_feat(vix=25, curve=-0.1, spy=0.02, breadth=0.7))
    assert label == NEUTRAL
    assert count == 2


def test_two_day_confirmation_holds_then_switches() -> None:
    # Confirmed risk_on; one risk_off print does not switch.
    assert confirmed_regime(["risk_on", "risk_off"], "risk_on") == "risk_on"
    # Two consecutive risk_off prints switch.
    assert confirmed_regime(["risk_off", "risk_off"], "risk_on") == "risk_off"
    # No prior → take today's raw.
    assert confirmed_regime(["neutral"], None) == "neutral"


def test_resolve_includes_flags_and_confirmed_label() -> None:
    result = resolve(
        _feat(vix=30, curve=-0.2, spy=-0.05, breadth=0.3),
        raw_history=["risk_off", "risk_off"],
        prev_confirmed="risk_on",
    )
    assert result.raw_label == RISK_OFF
    assert result.label == RISK_OFF  # confirmed after 2 prints
    assert result.bearish_count == 4
    assert result.flags["curve_inverted"] is True
