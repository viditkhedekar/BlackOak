"""Fundamentals family: growth (revenue/EPS/EBIT 3y), margins, ROIC, ROE, leverage."""

from __future__ import annotations

from app.domain.factors import FundamentalSnapshot
from app.domain.signals.inputs import SignalInputs
from app.domain.stats import cagr, safe_div


def _growth_3y(annual: list[FundamentalSnapshot], attr: str) -> float | None:
    """3-year CAGR of ``attr`` using the oldest and newest of up to the last 4 years.

    Falls back to the available span (min 2 points) so a company with only 2-3 years of
    history still scores — the span is whatever the data supports, labelled '3y' for the
    metric name but honest about gaps."""
    series = [getattr(s, attr) for s in annual[-4:] if getattr(s, attr) is not None]
    if len(series) < 2:
        return None
    years = len(series) - 1
    return cagr(series[0], series[-1], years)


def compute(inputs: SignalInputs) -> dict[str, float | None]:
    snap = inputs.latest_fundamentals
    if snap is None:
        return {k: None for k in (
            "revenue_growth_3y", "eps_growth_3y", "ebit_growth_3y", "gross_margin",
            "operating_margin", "roic", "roe", "debt_to_equity", "interest_coverage",
        )}

    invested_capital = None
    if snap.equity is not None:
        invested_capital = (snap.total_debt or 0.0) + snap.equity

    return {
        "revenue_growth_3y": _growth_3y(inputs.annual, "revenue"),
        "eps_growth_3y": _growth_3y(inputs.annual, "eps_diluted"),
        "ebit_growth_3y": _growth_3y(inputs.annual, "ebit"),
        "gross_margin": safe_div(snap.gross_profit, snap.revenue),
        "operating_margin": safe_div(snap.operating_income, snap.revenue),
        "roic": safe_div(snap.ebit, invested_capital),
        "roe": safe_div(snap.net_income, snap.equity),
        "debt_to_equity": safe_div(snap.total_debt, snap.equity),
        "interest_coverage": safe_div(snap.ebit, snap.interest_expense),
    }
