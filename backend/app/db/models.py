import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, Numeric, String, Text
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
