"""Risk family: beta distance, 90d vol, 1y max drawdown, book correlation, earnings gap."""

from __future__ import annotations

from app.domain.signals.inputs import RS_WINDOW, YEAR, SignalInputs
from app.domain.stats import (
    annualized_vol,
    beta,
    correlation,
    daily_returns,
    max_drawdown,
)


def compute(inputs: SignalInputs) -> dict[str, float | None]:
    returns = daily_returns(inputs.closes)
    market_returns = daily_returns(inputs.market_closes)

    b = beta(returns, market_returns)
    beta_distance = abs(b - 1.0) if b is not None else None

    vol_90d = annualized_vol(returns[-RS_WINDOW:]) if len(returns) >= 2 else None
    max_dd_1y = max_drawdown(inputs.closes[-YEAR:])

    corr_to_holdings: float | None = None
    if inputs.holdings_returns and len(returns) >= 2:
        corrs = [
            c for h in inputs.holdings_returns if (c := correlation(returns, h)) is not None
        ]
        if corrs:
            corr_to_holdings = sum(corrs) / len(corrs)

    days = float(inputs.days_to_earnings) if inputs.days_to_earnings is not None else None

    return {
        "beta_distance": beta_distance,
        "vol_90d": vol_90d,
        "max_drawdown_1y": max_dd_1y,
        "corr_to_holdings": corr_to_holdings,
        "days_to_earnings": days,
    }
