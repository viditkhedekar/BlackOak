"""Pure factor computations (docs/SCHEMA.md §7).

Every function takes plain numbers and returns ``float | None`` (None = the inputs to
compute it are missing). No I/O, no DB, no provider types — this is the auditable core
that the scoring layer ranks cross-sectionally. Directions (higher-vs-lower better) live
in ``scoring.py``; here we only produce raw factor values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.stats import (
    annualized_vol,
    beta,
    cagr,
    daily_returns,
    downside_deviation,
    max_drawdown,
    safe_div,
    sma,
    stdev_or_none,
)

# Trading-day windows.
_YEAR = 252
_HALF = 126
_MONTH = 21
_QUARTER = 63


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    """One fiscal year's figures. All optional — real filings have gaps."""

    fiscal_year: int
    revenue: float | None = None
    gross_profit: float | None = None
    ebitda: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    interest_expense: float | None = None
    total_assets: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    total_debt: float | None = None
    cash: float | None = None
    equity: float | None = None
    shares_out: float | None = None
    operating_cf: float | None = None
    capex: float | None = None

    @property
    def fcf(self) -> float | None:
        if self.operating_cf is None or self.capex is None:
            return None
        return self.operating_cf - abs(self.capex)


@dataclass(frozen=True, slots=True)
class FactorInputs:
    """Everything needed to score one company at one point in time."""

    symbol: str
    sector: str
    prices: list[float]  # adjusted closes, ascending by date
    current_price: float | None = None
    market_returns: list[float] = field(default_factory=list)  # SPY daily returns, aligned tail
    annual: list[FundamentalSnapshot] = field(default_factory=list)  # ascending by fiscal_year


# ---------------------------------------------------------------------------
# Category → ordered factor names. This is the authoritative catalogue that the
# scoring engine and the DB `inputs` payload both key off of.
# ---------------------------------------------------------------------------
FACTOR_CATEGORIES: dict[str, list[str]] = {
    "financial_health": ["current_ratio", "debt_to_equity", "interest_coverage", "altman_z"],
    "growth": ["revenue_cagr_3y", "eps_cagr_3y", "fcf_growth_3y", "revenue_acceleration"],
    "value": ["earnings_yield", "fcf_yield", "ev_ebitda", "price_to_book"],
    "quality": ["roic", "gross_margin_stability", "accruals_ratio", "asset_turnover"],
    "profitability": ["roe", "roa", "net_margin", "fcf_margin"],
    "momentum": ["ret_12_1", "ret_6m", "pct_above_200dma", "high_52w_proximity"],
    "volatility": ["vol_252d", "vol_90d"],
    "risk": ["max_drawdown_1y", "beta_distance", "downside_deviation", "net_debt_ebitda"],
}


def _market_cap(inputs: FactorInputs, snap: FundamentalSnapshot) -> float | None:
    return (
        inputs.current_price * snap.shares_out
        if inputs.current_price is not None and snap.shares_out
        else None
    )


def _financial_health(snap: FundamentalSnapshot, inputs: FactorInputs) -> dict[str, float | None]:
    total_liabilities = (
        snap.total_assets - snap.equity
        if snap.total_assets is not None and snap.equity is not None
        else None
    )
    working_capital = (
        snap.current_assets - snap.current_liabilities
        if snap.current_assets is not None and snap.current_liabilities is not None
        else None
    )
    mcap = _market_cap(inputs, snap)
    altman = None
    if snap.total_assets and snap.total_assets > 0 and total_liabilities and total_liabilities > 0:
        # Modified Altman Z: retained earnings proxied by equity (imperfect, documented).
        terms = [
            1.2 * (working_capital / snap.total_assets) if working_capital is not None else None,
            1.4 * (snap.equity / snap.total_assets) if snap.equity is not None else None,
            3.3 * (snap.ebitda / snap.total_assets) if snap.ebitda is not None else None,
            0.6 * (mcap / total_liabilities) if mcap is not None else None,
            1.0 * (snap.revenue / snap.total_assets) if snap.revenue is not None else None,
        ]
        present = [t for t in terms if t is not None]
        altman = sum(present) if len(present) >= 4 else None
    return {
        "current_ratio": safe_div(snap.current_assets, snap.current_liabilities),
        "debt_to_equity": safe_div(snap.total_debt, snap.equity),
        "interest_coverage": safe_div(snap.ebitda, snap.interest_expense),
        "altman_z": altman,
    }


def _growth(annual: list[FundamentalSnapshot]) -> dict[str, float | None]:
    if len(annual) < 4:
        latest = annual[-1] if annual else None
        oldest = annual[0] if annual else None
        years = (latest.fiscal_year - oldest.fiscal_year) if latest and oldest else 0
    else:
        latest, oldest = annual[-1], annual[-4]
        years = 3
    rev_cagr = eps_cagr = fcf_g = accel = None
    if latest and oldest and years > 0:
        rev_cagr = cagr(oldest.revenue, latest.revenue, years)
        eps_cagr = cagr(oldest.eps_diluted, latest.eps_diluted, years)
        fcf_g = cagr(oldest.fcf, latest.fcf, years)
    if len(annual) >= 3:
        a, b, c = annual[-3], annual[-2], annual[-1]
        yoy_recent = safe_div(
            (c.revenue - b.revenue) if c.revenue is not None and b.revenue is not None else None,
            b.revenue,
        )
        yoy_prior = safe_div(
            (b.revenue - a.revenue) if b.revenue is not None and a.revenue is not None else None,
            a.revenue,
        )
        if yoy_recent is not None and yoy_prior is not None:
            accel = yoy_recent - yoy_prior
    return {
        "revenue_cagr_3y": rev_cagr,
        "eps_cagr_3y": eps_cagr,
        "fcf_growth_3y": fcf_g,
        "revenue_acceleration": accel,
    }


def _value(snap: FundamentalSnapshot, inputs: FactorInputs) -> dict[str, float | None]:
    mcap = _market_cap(inputs, snap)
    ev = None
    if mcap is not None and snap.total_debt is not None and snap.cash is not None:
        ev = mcap + snap.total_debt - snap.cash
    return {
        "earnings_yield": safe_div(snap.net_income, mcap),
        "fcf_yield": safe_div(snap.fcf, mcap),
        "ev_ebitda": safe_div(ev, snap.ebitda),
        "price_to_book": safe_div(mcap, snap.equity),
    }


def _quality(annual: list[FundamentalSnapshot], snap: FundamentalSnapshot) -> dict[str, float | None]:
    invested_capital = (
        (snap.total_debt or 0) + snap.equity if snap.equity is not None else None
    )
    margins = [
        gp / rev
        for s in annual
        if (gp := s.gross_profit) is not None and (rev := s.revenue) not in (None, 0)
    ]
    accruals = None
    if snap.net_income is not None and snap.operating_cf is not None:
        accruals = safe_div(snap.net_income - snap.operating_cf, snap.total_assets)
    return {
        "roic": safe_div(snap.net_income, invested_capital),
        "gross_margin_stability": stdev_or_none(margins),
        "accruals_ratio": accruals,
        "asset_turnover": safe_div(snap.revenue, snap.total_assets),
    }


def _profitability(snap: FundamentalSnapshot) -> dict[str, float | None]:
    return {
        "roe": safe_div(snap.net_income, snap.equity),
        "roa": safe_div(snap.net_income, snap.total_assets),
        "net_margin": safe_div(snap.net_income, snap.revenue),
        "fcf_margin": safe_div(snap.fcf, snap.revenue),
    }


def _momentum(prices: list[float]) -> dict[str, float | None]:
    last = prices[-1] if prices else None
    ret_12_1 = ret_6m = above_200 = high_prox = None
    if last is not None and len(prices) > _YEAR:
        p_12m, p_1m = prices[-_YEAR], prices[-_MONTH]
        ret_12_1 = (p_1m / p_12m - 1.0) if p_12m > 0 else None
    if last is not None and len(prices) > _HALF:
        p_6m = prices[-_HALF]
        ret_6m = (last / p_6m - 1.0) if p_6m > 0 else None
    sma200 = sma(prices, 200)
    if last is not None and sma200:
        above_200 = last / sma200 - 1.0
    if last is not None and len(prices) >= _YEAR:
        window_high = max(prices[-_YEAR:])
        high_prox = last / window_high if window_high > 0 else None
    return {
        "ret_12_1": ret_12_1,
        "ret_6m": ret_6m,
        "pct_above_200dma": above_200,
        "high_52w_proximity": high_prox,
    }


def _volatility(prices: list[float]) -> dict[str, float | None]:
    rets = daily_returns(prices)
    return {
        "vol_252d": annualized_vol(rets[-_YEAR:]),
        "vol_90d": annualized_vol(rets[-_QUARTER:]),
    }


def _risk(inputs: FactorInputs, snap: FundamentalSnapshot) -> dict[str, float | None]:
    rets = daily_returns(inputs.prices)
    b = beta(rets, inputs.market_returns) if inputs.market_returns else None
    net_debt = (
        snap.total_debt - snap.cash
        if snap.total_debt is not None and snap.cash is not None
        else None
    )
    return {
        "max_drawdown_1y": max_drawdown(inputs.prices[-_YEAR:]),
        "beta_distance": abs(b - 1.0) if b is not None else None,
        "downside_deviation": downside_deviation(rets[-_YEAR:]),
        "net_debt_ebitda": safe_div(net_debt, snap.ebitda),
    }


def compute_factors(inputs: FactorInputs) -> dict[str, float | None]:
    """Compute every raw factor for one company. Missing inputs → None (never raises)."""
    snap = inputs.annual[-1] if inputs.annual else FundamentalSnapshot(fiscal_year=0)
    result: dict[str, float | None] = {}
    result.update(_financial_health(snap, inputs))
    result.update(_growth(inputs.annual))
    result.update(_value(snap, inputs))
    result.update(_quality(inputs.annual, snap))
    result.update(_profitability(snap))
    result.update(_momentum(inputs.prices))
    result.update(_volatility(inputs.prices))
    result.update(_risk(inputs, snap))
    return result
