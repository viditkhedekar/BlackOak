"""yfinance fundamentals adapter — annual income/balance/cashflow → FundamentalRecord.

yfinance line-item labels are messy and version-sensitive, so the label→field mapping
lives here and nowhere else (ADR-0004). Missing line items simply stay None.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
import structlog
import yfinance as yf
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.domain.fundamentals import EstimateRecord, FundamentalRecord


def _scalar(info: dict[str, object], key: str) -> Decimal | None:
    value = info.get(key)
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return None if result.is_nan() else result

log = structlog.get_logger()

# field name -> yfinance row label (per statement)
_INCOME = {
    "revenue": "Total Revenue",
    "gross_profit": "Gross Profit",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "operating_income": "Operating Income",
    "net_income": "Net Income",
    "eps_diluted": "Diluted EPS",
    "interest_expense": "Interest Expense",
}
_BALANCE = {
    "total_assets": "Total Assets",
    "current_assets": "Current Assets",
    "current_liabilities": "Current Liabilities",
    "total_debt": "Total Debt",
    "cash": "Cash And Cash Equivalents",
    "equity": "Stockholders Equity",
    "shares_out": "Ordinary Shares Number",
}
_CASHFLOW = {
    "operating_cf": "Operating Cash Flow",
    "capex": "Capital Expenditure",
}


def _cell(frame: pd.DataFrame, label: str, col: object) -> Decimal | None:
    # A period present in one statement may be absent from another; guard both axes.
    if frame is None or frame.empty or label not in frame.index or col not in frame.columns:
        return None
    value = frame.at[label, col]
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class YFinanceFundamentals:
    name = "yfinance"

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch_annual_fundamentals(self, symbol: str) -> list[FundamentalRecord]:
        ticker = yf.Ticker(symbol)
        income = ticker.income_stmt
        balance = ticker.balance_sheet
        cashflow = ticker.cashflow

        if income is None or income.empty:
            log.info("yfinance.fundamentals.no_data", symbol=symbol)
            return []

        # Union of period-end dates across statements, oldest first.
        columns: set[object] = set(income.columns)
        for frame in (balance, cashflow):
            if frame is not None and not frame.empty:
                columns |= set(frame.columns)

        records: list[FundamentalRecord] = []
        for col in sorted(columns, key=lambda c: pd.Timestamp(c)):
            fields: dict[str, Decimal | None] = {}
            for field, label in _INCOME.items():
                fields[field] = _cell(income, label, col)
            for field, label in _BALANCE.items():
                fields[field] = _cell(balance, label, col)
            for field, label in _CASHFLOW.items():
                fields[field] = _cell(cashflow, label, col)
            records.append(
                FundamentalRecord(
                    fiscal_date=pd.Timestamp(col).date(),
                    period="FY",
                    **fields,
                )
            )
        return records

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def fetch_estimates(self, symbol: str) -> EstimateRecord | None:
        """Forward EPS / forward P/E / PEG from yfinance `info` scalars, stamped today.

        These are point-in-time snapshots (yfinance exposes only the current value), so
        as_of_date is ingest day — the estimates table is a rolling log, not history."""
        info = yf.Ticker(symbol).info
        if not info:
            log.info("yfinance.estimates.no_data", symbol=symbol)
            return None
        return EstimateRecord(
            as_of_date=datetime.now(UTC).date(),
            forward_eps=_scalar(info, "forwardEps"),
            forward_pe=_scalar(info, "forwardPE"),
            peg=_scalar(info, "trailingPegRatio") or _scalar(info, "pegRatio"),
        )
