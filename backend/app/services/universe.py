"""Seed the investable universe from the bundled S&P 500 constituent list."""

from __future__ import annotations

import csv
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.services.job_tracking import track_job

log = structlog.get_logger()

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "sp500.csv"


def load_seed_rows(path: Path = _SEED_PATH) -> list[dict[str, object]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return [
            {
                "symbol": row["symbol"].strip().upper(),
                "name": row["name"].strip(),
                "sector": row["sector"].strip() or None,
                "industry": row["industry"].strip() or None,
                "universe": "SP500",
                "is_active": True,
            }
            for row in reader
        ]


async def seed_universe(session: AsyncSession) -> int:
    """Upsert the S&P 500 universe. Idempotent — safe to re-run on constituent changes."""
    async with track_job(session, "seed_universe") as ctx:
        rows = load_seed_rows()
        repo = CompanyRepository(session)
        count = await repo.upsert_many(rows)
        ctx.records_processed = count
        ctx.meta = {"universe": "SP500", "symbols": count}
        return count
