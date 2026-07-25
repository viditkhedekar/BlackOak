"""Tests for the v2 fusion (strategy.py) and regime classifier (regime.py)."""

from __future__ import annotations

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
    WEIGHTS_BY_REGIME,
    StrategyCompany,
    fuse_scores,
)


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
