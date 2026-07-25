from __future__ import annotations

from datetime import date

from pydantic import BaseModel

CATEGORY_FIELDS = (
    "financial_health", "growth", "value", "quality",
    "profitability", "momentum", "volatility", "risk",
)


class CategoryScores(BaseModel):
    financial_health: float | None = None
    growth: float | None = None
    value: float | None = None
    quality: float | None = None
    profitability: float | None = None
    momentum: float | None = None
    volatility: float | None = None
    risk: float | None = None


class ScreenerRow(BaseModel):
    symbol: str
    name: str
    sector: str | None
    composite: float | None
    data_completeness: float
    categories: CategoryScores


class ScreenerResponse(BaseModel):
    items: list[ScreenerRow]
    total: int
    limit: int
    offset: int
    profile: str
    as_of: date | None


class FactorBreakdownItem(BaseModel):
    factor: str
    raw: float | None
    score: float | None
    inverse: bool


class CategoryBreakdown(BaseModel):
    category: str
    score: float | None
    factors: list[FactorBreakdownItem]


class CompanyScoreDetail(BaseModel):
    symbol: str
    profile: str
    as_of: date
    composite: float | None
    data_completeness: float
    engine_version: str
    categories: CategoryScores
    breakdown: list[CategoryBreakdown]
