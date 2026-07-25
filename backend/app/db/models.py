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
    revenue: Mapped[Decimal | None] = mapped_column(Money)
    gross_profit: Mapped[Decimal | None] = mapped_column(Money)
    ebitda: Mapped[Decimal | None] = mapped_column(Money)
    net_income: Mapped[Decimal | None] = mapped_column(Money)
    eps_diluted: Mapped[Decimal | None] = mapped_column(Money)
    interest_expense: Mapped[Decimal | None] = mapped_column(Money)
    # Balance sheet
    total_assets: Mapped[Decimal | None] = mapped_column(Money)
    current_assets: Mapped[Decimal | None] = mapped_column(Money)
    current_liabilities: Mapped[Decimal | None] = mapped_column(Money)
    total_debt: Mapped[Decimal | None] = mapped_column(Money)
    cash: Mapped[Decimal | None] = mapped_column(Money)
    equity: Mapped[Decimal | None] = mapped_column(Money)
    shares_out: Mapped[Decimal | None] = mapped_column(Money)
    # Cash flow
    operating_cf: Mapped[Decimal | None] = mapped_column(Money)
    capex: Mapped[Decimal | None] = mapped_column(Money)

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
