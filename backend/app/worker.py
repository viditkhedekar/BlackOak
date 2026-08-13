"""Worker entrypoint (docs/ARCHITECTURE.md §12) — the process that trades on a schedule.

    uv run python -m app.worker

Runs as its own service alongside the API. Keep exactly one instance: the jobs are
idempotent, but two workers would double the order flow before idempotency could help.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.scheduler import build_scheduler

log = structlog.get_logger()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.environment)

    scheduler = build_scheduler()
    scheduler.start()
    for job in scheduler.get_jobs():
        log.info("worker.job_registered", job=job.id, next_run=str(job.next_run_time))
    log.info(
        "worker.started",
        environment=settings.environment,
        cycle_interval_minutes=settings.cycle_interval_minutes,
    )

    # Park until a signal arrives; APScheduler drives everything from here.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    log.info("worker.stopping")
    scheduler.shutdown(wait=True)  # let an in-flight cycle finish rather than orphan orders
    log.info("worker.stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
