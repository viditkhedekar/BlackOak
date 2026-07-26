"""BlackOak scheduled worker.

Runs APScheduler in its own process (never inside the API — see ADR-0003).
Phase 0 ships a heartbeat only; ingest/scoring/trading jobs arrive in Phases 1+.
"""

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.eod_ingest import run_eod_ingest
from app.jobs.intraday_cycle import run_intraday_cycle
from app.jobs.intraday_poll import run_intraday_poll
from app.jobs.nightly import run_nightly

log = structlog.get_logger()


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="America/New_York")
    # Intraday bar poll: every 15 min during RTH (job skips non-trading days).
    scheduler.add_job(
        run_intraday_poll,
        CronTrigger(day_of_week="mon-fri", hour="9-16", minute="0,15,30,45"),
        id="intraday_poll",
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    # Autonomous decision cycle: every 30 min, 09:45-15:45 ET (job skips holidays).
    scheduler.add_job(
        run_intraday_cycle,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="15,45"),
        id="intraday_cycle",
        misfire_grace_time=300,
        coalesce=True,
        max_instances=1,
    )
    # EOD: 16:30 ET on weekdays — ingest prices then rescore (job skips holidays).
    scheduler.add_job(
        run_eod_ingest,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30),
        id="eod_ingest",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    # Nightly 02:00 ET — rotating fundamentals refresh + rescore.
    scheduler.add_job(
        run_nightly,
        CronTrigger(hour=2, minute=0),
        id="nightly",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    return scheduler


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.environment)

    scheduler = build_scheduler()
    scheduler.start()
    log.info(
        "worker.started",
        environment=settings.environment,
        jobs=[j.id for j in scheduler.get_jobs()],
    )
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
