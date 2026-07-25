"""Bracket every pipeline run in a job_runs row so failures are never silent."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobRun

log = structlog.get_logger()


@dataclass
class JobContext:
    """Mutable handle a job uses to report progress into its job_runs row."""

    run_id: uuid.UUID
    records_processed: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


@asynccontextmanager
async def track_job(session: AsyncSession, job_name: str) -> AsyncIterator[JobContext]:
    run = JobRun(job_name=job_name, started_at=datetime.now(UTC), status="running")
    session.add(run)
    await session.flush()
    ctx = JobContext(run_id=run.id)
    bound = log.bind(job=job_name, run_id=str(run.id))
    bound.info("job.started")
    try:
        yield ctx
    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(UTC)
        run.records_processed = ctx.records_processed
        run.meta = ctx.meta or None
        await session.commit()
        bound.exception("job.failed")
        raise
    else:
        run.status = "success"
        run.finished_at = datetime.now(UTC)
        run.records_processed = ctx.records_processed
        run.meta = ctx.meta or None
        await session.commit()
        bound.info("job.finished", records=ctx.records_processed)
