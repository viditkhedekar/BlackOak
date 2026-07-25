"""Raw fundamentals record — the adapter's output and the DB's input.

Distinct from factors.FundamentalSnapshot (which is the float-based *compute* input):
this mirrors DB columns with Decimals and a real fiscal_date for storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Column names shared by the adapter, the repository, and the upsert set.
AMOUNT_FIELDS = (
    "revenue", "gross_profit", "ebitda", "ebit", "operating_income", "net_income",
    "eps_diluted", "interest_expense",
    "total_assets", "current_assets", "current_liabilities", "total_debt", "cash",
    "equity", "shares_out", "operating_cf", "capex",
)


@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    fiscal_date: date
    period: str  # "FY" | "Q"
    revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    ebitda: Decimal | None = None
    ebit: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    eps_diluted: Decimal | None = None
    interest_expense: Decimal | None = None
    total_assets: Decimal | None = None
    current_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    total_debt: Decimal | None = None
    cash: Decimal | None = None
    equity: Decimal | None = None
    shares_out: Decimal | None = None
    operating_cf: Decimal | None = None
    capex: Decimal | None = None


@dataclass(frozen=True, slots=True)
class EstimateRecord:
    """Forward-looking estimates (the weakest data — yfinance `info` scalars).
    Signal families renormalize when these are missing."""

    as_of_date: date
    forward_eps: Decimal | None = None
    forward_pe: Decimal | None = None
    peg: Decimal | None = None
