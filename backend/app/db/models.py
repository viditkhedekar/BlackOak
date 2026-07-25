import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Money/price/quantity precision (see docs/SCHEMA.md conventions).
Money = Numeric(18, 6)
# Balance-sheet/statement absolutes reach into the trillions (big-bank total assets),
# which overflow Money's 12-digit integer part — give fundamentals room.
BigMoney = Numeric(24, 4)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    clerk_user_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))


class JobRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "job_runs"
    __table_args__ = (Index("ix_job_runs_name_started", "job_name", "started_at"),)

    job_name: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    records_processed: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Investable universe. See docs/SCHEMA.md."""

    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_sector", "sector"),
        Index("ix_companies_active_universe", "is_active", "universe"),
    )

    symbol: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    exchange: Mapped[str | None] = mapped_column(String(32))
    sector: Mapped[str | None] = mapped_column(String(80))
    industry: Mapped[str | None] = mapped_column(String(120))
    market_cap: Mapped[Decimal | None] = mapped_column(Money)
    universe: Mapped[str] = mapped_column(String(32), default="SP500")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    delisted_at: Mapped[date | None] = mapped_column(Date)


class PriceDaily(Base):
    """EOD OHLCV + adjusted close. Composite PK (company_id, date); upsert on conflict."""

    __tablename__ = "prices_daily"
    __table_args__ = (
        Index("ix_prices_daily_date_brin", "date", postgresql_using="brin"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    adj_close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))


class BarIntraday(Base):
    """Intraday OHLCV (15-min default). Composite PK (company_id, ts, interval);
    ~120-day retention via the nightly prune — this is working data for the
    strategy engine, not an archive (daily history lives in prices_daily)."""

    __tablename__ = "bars_intraday"
    __table_args__ = (
        Index("ix_bars_intraday_ts_brin", "ts", postgresql_using="brin"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    interval: Mapped[str] = mapped_column(String(8), primary_key=True, default="15Min")
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))


class MacroSeries(Base):
    """Macro observations keyed by (series_id, date): FEDFUNDS, T10Y2Y, CPIAUCSL, VIX."""

    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6))


class Benchmark(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Reference series (SPY, later sector ETFs) for alpha/beta/relative charts."""

    __tablename__ = "benchmarks"

    symbol: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class BenchmarkPrice(Base):
    __tablename__ = "benchmark_prices"
    __table_args__ = (
        Index("ix_benchmark_prices_date_brin", "date", postgresql_using="brin"),
    )

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("benchmarks.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    adj_close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))


class Fundamental(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One fiscal period's statement snapshot. Raw inputs to the scoring engine."""

    __tablename__ = "fundamentals"
    __table_args__ = (
        UniqueConstraint("company_id", "period", "fiscal_date", name="uq_fundamentals_period"),
        Index("ix_fundamentals_company_date", "company_id", "fiscal_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")
    )
    period: Mapped[str] = mapped_column(String(4))  # "FY" or "Q"
    fiscal_date: Mapped[date] = mapped_column(Date)
    reported_at: Mapped[date | None] = mapped_column(Date)

    # Income statement
    revenue: Mapped[Decimal | None] = mapped_column(BigMoney)
    gross_profit: Mapped[Decimal | None] = mapped_column(BigMoney)
    ebitda: Mapped[Decimal | None] = mapped_column(BigMoney)
    ebit: Mapped[Decimal | None] = mapped_column(BigMoney)
    operating_income: Mapped[Decimal | None] = mapped_column(BigMoney)
    net_income: Mapped[Decimal | None] = mapped_column(BigMoney)
    eps_diluted: Mapped[Decimal | None] = mapped_column(Money)
    interest_expense: Mapped[Decimal | None] = mapped_column(BigMoney)
    # Balance sheet
    total_assets: Mapped[Decimal | None] = mapped_column(BigMoney)
    current_assets: Mapped[Decimal | None] = mapped_column(BigMoney)
    current_liabilities: Mapped[Decimal | None] = mapped_column(BigMoney)
    total_debt: Mapped[Decimal | None] = mapped_column(BigMoney)
    cash: Mapped[Decimal | None] = mapped_column(BigMoney)
    equity: Mapped[Decimal | None] = mapped_column(BigMoney)
    shares_out: Mapped[Decimal | None] = mapped_column(BigMoney)
    # Cash flow
    operating_cf: Mapped[Decimal | None] = mapped_column(BigMoney)
    capex: Mapped[Decimal | None] = mapped_column(BigMoney)

    source: Mapped[str] = mapped_column(String(32))


class Estimate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Forward-looking estimates (forward EPS/PE, PEG) — a rolling snapshot log keyed
    by (company_id, as_of_date). The weakest data source; signals renormalize on nulls."""

    __tablename__ = "estimates"
    __table_args__ = (
        UniqueConstraint("company_id", "as_of_date", name="uq_estimates_asof"),
        Index("ix_estimates_company_date", "company_id", "as_of_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")
    )
    as_of_date: Mapped[date] = mapped_column(Date)
    forward_eps: Mapped[Decimal | None] = mapped_column(Money)
    forward_pe: Mapped[Decimal | None] = mapped_column(Money)
    peg: Mapped[Decimal | None] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(32))


class ResearchScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Deterministic engine output. `inputs` holds every raw factor value so any
    score is fully reproducible (docs/SCHEMA.md §7)."""

    __tablename__ = "research_scores"
    __table_args__ = (
        UniqueConstraint("company_id", "as_of_date", "profile", name="uq_scores_asof"),
        Index("ix_scores_asof_composite", "as_of_date", "composite"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")
    )
    as_of_date: Mapped[date] = mapped_column(Date)
    profile: Mapped[str] = mapped_column(String(16))  # conservative|balanced|aggressive

    financial_health: Mapped[float | None] = mapped_column(Numeric(6, 3))
    growth: Mapped[float | None] = mapped_column(Numeric(6, 3))
    value: Mapped[float | None] = mapped_column(Numeric(6, 3))
    quality: Mapped[float | None] = mapped_column(Numeric(6, 3))
    profitability: Mapped[float | None] = mapped_column(Numeric(6, 3))
    momentum: Mapped[float | None] = mapped_column(Numeric(6, 3))
    volatility: Mapped[float | None] = mapped_column(Numeric(6, 3))
    risk: Mapped[float | None] = mapped_column(Numeric(6, 3))
    composite: Mapped[float | None] = mapped_column(Numeric(6, 3))

    data_completeness: Mapped[float] = mapped_column(Numeric(5, 4), default=0)
    engine_version: Mapped[str] = mapped_column(String(16))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
