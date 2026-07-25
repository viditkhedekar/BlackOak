"""BlackOak scheduled worker.

Runs APScheduler in its own process (never inside the API — see ADR-0003).
Phase 0 ships a heartbeat only; ingest/scoring/trading jobs arrive in Phases 1+.
"""

import asyncio

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.logging import configure_logging

log = structlog.get_logger()


def heartbeat() -> None:
    log.info("worker.heartbeat")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.environment)

    scheduler = AsyncIOScheduler(timezone="America/New_York")
    scheduler.add_job(heartbeat, "interval", minutes=15, id="heartbeat")
    scheduler.start()
    log.info("worker.started", environment=settings.environment, jobs=len(scheduler.get_jobs()))
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
