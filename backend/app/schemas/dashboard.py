from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class StrategyFamilies(BaseModel):
    valuation: float | None = None
    fundamentals: float | None = None
    momentum: float | None = None
    technical: float | None = None
    risk: float | None = None


class RankingRow(BaseModel):
    rank: int | None
    symbol: str
    name: str
    sector: str | None
    composite: float | None
    families: StrategyFamilies
    data_completeness: float


class RankingsResponse(BaseModel):
    ts: datetime | None
    regime: str | None
    items: list[RankingRow]


class RegimeResponse(BaseModel):
    ts: datetime | None
    label: str | None
    raw_label: str | None
    bearish_count: int | None
    features: dict[str, Any] | None
    weights: dict[str, Any] | None


class DecisionRow(BaseModel):
    ts: datetime
    cycle_id: str
    symbol: str
    action: str
    reason: str
    regime: str
    evidence: dict[str, Any]


class PositionRow(BaseModel):
    symbol: str
    shares: float
    avg_entry_price: float
    stop_price: float | None
    target_price: float | None
    entry_composite: float | None


class PortfolioResponse(BaseModel):
    ts: datetime | None
    equity: float | None
    cash: float | None
    regime: str | None
    positions: list[PositionRow]


class EquityPoint(BaseModel):
    ts: datetime
    equity: float
    cash: float
    regime: str
    positions: int


class PerformanceResponse(BaseModel):
    points: list[EquityPoint]
    spy: list[float]
    start_equity: float | None
    total_return: float | None
    spy_return: float | None


class BacktestSummary(BaseModel):
    id: str
    start_date: date
    end_date: date
    config_version: str
    universe_size: int
    metrics: dict[str, Any]
    created_at: datetime


class BacktestEquityPoint(BaseModel):
    day: date
    equity: float
    regime: str


class BacktestTradeRow(BaseModel):
    symbol: str
    side: str
    trade_date: date
    shares: float
    price: float
    reason: str
    realized_pnl: float


class BacktestDetail(BaseModel):
    summary: BacktestSummary
    equity_curve: list[BacktestEquityPoint]
    trades: list[BacktestTradeRow]


class JobRunRow(BaseModel):
    job_name: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    records_processed: int | None
    error: str | None


class FeedFreshness(BaseModel):
    feed: str
    as_of: str | None


class SystemHealthResponse(BaseModel):
    jobs: list[JobRunRow]
    feeds: list[FeedFreshness]
