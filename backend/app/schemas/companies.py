from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    sector: str | None
    industry: str | None


class CompanyDetail(CompanySummary):
    exchange: str | None
    market_cap: Decimal | None
    universe: str
    is_active: bool


class CompanyList(BaseModel):
    items: list[CompanySummary]
    total: int
    limit: int
    offset: int


class PricePoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal
    volume: int


class PriceSeries(BaseModel):
    symbol: str
    range: str
    points: list[PricePoint]
