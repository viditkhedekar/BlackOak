"""Unit tests for pure factor computations against hand-computed values."""

import math

from app.domain.factors import (
    FACTOR_CATEGORIES,
    FactorInputs,
    FundamentalSnapshot,
    compute_factors,
)


def _snap(year: int, **kw: float) -> FundamentalSnapshot:
    return FundamentalSnapshot(fiscal_year=year, **kw)


def test_ratios_from_single_snapshot() -> None:
    snap = _snap(
        2025, revenue=1000, net_income=100, equity=500, total_assets=2000,
        current_assets=600, current_liabilities=300, total_debt=250, cash=50, ebitda=200,
        interest_expense=20, operating_cf=180, capex=-30,
    )
    f = compute_factors(FactorInputs("X", "Tech", prices=[10.0], current_price=10.0, annual=[snap]))
    assert f["current_ratio"] == 2.0  # 600/300
    assert f["debt_to_equity"] == 0.5  # 250/500
    assert f["roe"] == 0.2  # 100/500
    assert f["roa"] == 0.05  # 100/2000
    assert f["net_margin"] == 0.1  # 100/1000
    assert f["interest_coverage"] == 10.0  # 200/20
    assert f["fcf_margin"] == 0.15  # (180-30)/1000


def test_fcf_normalizes_capex_sign() -> None:
    pos = _snap(2025, operating_cf=100, capex=40)
    neg = _snap(2025, operating_cf=100, capex=-40)
    assert pos.fcf == 60 and neg.fcf == 60


def test_growth_cagr_three_years() -> None:
    annual = [
        _snap(2022, revenue=1000, eps_diluted=1.0),
        _snap(2023, revenue=1100, eps_diluted=1.1),
        _snap(2024, revenue=1200, eps_diluted=1.2),
        _snap(2025, revenue=1331, eps_diluted=2.0),
    ]
    f = compute_factors(FactorInputs("X", "Tech", prices=[10.0], annual=annual))
    # revenue 1000 -> 1331 over 3y = 10% CAGR exactly.
    assert math.isclose(f["revenue_cagr_3y"], 0.10, abs_tol=1e-9)


def test_missing_inputs_yield_none_not_error() -> None:
    f = compute_factors(FactorInputs("X", "Tech", prices=[], annual=[]))
    assert f["roe"] is None
    assert f["ret_6m"] is None
    # Every catalogued factor key is present even when unset.
    all_names = {n for names in FACTOR_CATEGORIES.values() for n in names}
    assert set(f) == all_names


def test_momentum_needs_a_year_of_prices() -> None:
    rising = [float(100 + i) for i in range(260)]  # ascending
    f = compute_factors(FactorInputs("X", "Tech", prices=rising, current_price=rising[-1]))
    assert f["ret_6m"] is not None and f["ret_6m"] > 0
    assert f["high_52w_proximity"] is not None and f["high_52w_proximity"] <= 1.0
    assert f["pct_above_200dma"] is not None and f["pct_above_200dma"] > 0
