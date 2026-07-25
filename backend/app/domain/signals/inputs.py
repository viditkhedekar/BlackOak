"""Shared inputs + metric catalogue for the six signal families (docs/ROADMAP.md R1).

Each family is a pure function taking ``SignalInputs`` and returning raw metric values
(``float | None``, None = insufficient data). Direction (higher-vs-lower better) and the
cross-sectional percentile ranking live in R2's ``strategy.py`` — here we only produce raw
numbers, exactly as ``domain/factors.py`` does for the v1 engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.factors import FundamentalSnapshot

# Trading-day windows.
YEAR = 252
DMA_SHORT = 20
DMA_MID = 50
DMA_LONG = 200
RS_WINDOW = 63  # ~90 calendar days
MONTH = 21


@dataclass(frozen=True, slots=True)
class EstimateValues:
    """Forward estimates for one company (the weakest data; often None)."""

    forward_pe: float | None = None
    peg: float | None = None
    forward_eps: float | None = None


@dataclass(frozen=True, slots=True)
class SignalInputs:
    """Everything a family needs to evaluate one symbol at one point in time.

    Daily series are ascending by date. Market series is SPY's aligned tail (for
    relative strength). Portfolio-aware inputs (``holdings_returns``) and
    ``days_to_earnings`` are optional — absent ones make their metric None so the
    family renormalizes, which is how a single-name run still scores."""

    symbol: str
    sector: str
    closes: list[float]
    highs: list[float]
    lows: list[float]
    volumes: list[float]
    opens: list[float] = field(default_factory=list)
    current_price: float | None = None
    market_closes: list[float] = field(default_factory=list)
    annual: list[FundamentalSnapshot] = field(default_factory=list)
    estimates: EstimateValues | None = None
    days_to_earnings: int | None = None
    # Each inner list is one current holding's daily returns (aligned tail); empty
    # until R4 supplies the live book.
    holdings_returns: list[list[float]] = field(default_factory=list)

    @property
    def latest_fundamentals(self) -> FundamentalSnapshot | None:
        return self.annual[-1] if self.annual else None


# family -> ordered metric names. Authoritative catalogue the fusion engine keys off.
SIGNAL_FAMILIES: dict[str, list[str]] = {
    "valuation": ["ev_ebitda", "forward_pe", "peg", "price_to_book", "fcf_yield"],
    "fundamentals": [
        "revenue_growth_3y", "eps_growth_3y", "ebit_growth_3y",
        "gross_margin", "operating_margin", "roic", "roe",
        "debt_to_equity", "interest_coverage",
    ],
    "momentum": ["ma_stack", "pct_above_200dma", "rs_vs_spy", "ret_12_1", "breakout_strength"],
    "technical": ["rsi_14", "macd_hist", "volume_spike", "atr_pct", "sr_position", "candle_signal"],
    "risk": ["beta_distance", "vol_90d", "max_drawdown_1y", "corr_to_holdings", "days_to_earnings"],
}


def windowed_return(closes: list[float], lookback: int, skip: int = 0) -> float | None:
    """Return over ``lookback`` bars ending ``skip`` bars ago. None if not enough history."""
    end = len(closes) - 1 - skip
    start = end - lookback
    if start < 0 or end < 0 or closes[start] <= 0:
        return None
    return closes[end] / closes[start] - 1.0
