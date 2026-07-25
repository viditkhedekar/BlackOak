"""Fundamentals adapter transform test — fake statements, no network."""

from decimal import Decimal

import pandas as pd

from app.adapters import yfinance_fundamentals
from app.adapters.yfinance_fundamentals import YFinanceFundamentals


class _FakeTicker:
    def __init__(self, income: pd.DataFrame, balance: pd.DataFrame, cashflow: pd.DataFrame):
        self.income_stmt = income
        self.balance_sheet = balance
        self.cashflow = cashflow


def _frame(rows: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    cols = pd.to_datetime(dates)
    return pd.DataFrame({c: [rows[label][i] for label in rows] for i, c in enumerate(cols)},
                        index=list(rows.keys()))


def _install(monkeypatch, income, balance, cashflow) -> None:
    ticker = _FakeTicker(income, balance, cashflow)
    monkeypatch.setattr(yfinance_fundamentals.yf, "Ticker", lambda _s: ticker)


def test_maps_labels_and_orders_ascending(monkeypatch) -> None:
    dates = ["2024-09-30", "2023-09-30"]  # provider returns newest-first
    income = _frame(
        {"Total Revenue": [400.0, 380.0], "Net Income": [100.0, 90.0],
         "Diluted EPS": [6.1, 5.5], "Gross Profit": [180.0, 170.0], "EBITDA": [130.0, 120.0]},
        dates,
    )
    balance = _frame(
        {"Total Assets": [350.0, 330.0], "Stockholders Equity": [70.0, 65.0],
         "Total Debt": [100.0, 95.0], "Ordinary Shares Number": [15.0, 15.5]},
        dates,
    )
    cashflow = _frame(
        {"Operating Cash Flow": [110.0, 100.0], "Capital Expenditure": [-12.0, -11.0]}, dates
    )
    _install(monkeypatch, income, balance, cashflow)

    records = YFinanceFundamentals().fetch_annual_fundamentals("AAPL")

    assert [r.fiscal_date.year for r in records] == [2023, 2024]  # ascending
    latest = records[-1]
    assert latest.revenue == Decimal("400.0")
    assert latest.equity == Decimal("70.0")
    assert latest.capex == Decimal("-12.0")
    assert latest.eps_diluted == Decimal("6.1")


def test_missing_label_yields_none(monkeypatch) -> None:
    dates = ["2024-09-30"]
    income = _frame({"Total Revenue": [400.0]}, dates)  # no EBITDA, no EPS
    empty = pd.DataFrame()
    _install(monkeypatch, income, empty, empty)

    r = YFinanceFundamentals().fetch_annual_fundamentals("X")[0]
    assert r.revenue == Decimal("400.0")
    assert r.ebitda is None
    assert r.total_assets is None


def test_empty_income_returns_no_records(monkeypatch) -> None:
    _install(monkeypatch, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert YFinanceFundamentals().fetch_annual_fundamentals("X") == []
