"""APScheduler wiring for the worker (docs/ARCHITECTURE.md §12).

One scheduler in one process. This is deliberately NOT started inside the API: uvicorn
runs multiple workers, and each would carry its own scheduler and double-fire every job.

Cron only filters weekdays; market holidays are weekdays too, so each job re-checks
``is_trading_day`` itself. Every job here is idempotent — ingests upsert, orders carry a
deterministic client id — so a coalesced misfire re-runs safely.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.jobs.eod_ingest import run_eod_ingest
from app.jobs.intraday_cycle import run_intraday_cycle
from app.jobs.intraday_poll import run_intraday_poll
from app.jobs.nightly import run_nightly
from app.jobs.order_sync import run_order_sync
from app.services.schedule import ET, WEEKDAYS, cycle_trigger

log = structlog.get_logger()

# A job that misfires (worker asleep, host suspended) still runs if the wake-up is within
# this window, and repeated misfires collapse into one run rather than a burst.
MISFIRE_GRACE_SECONDS = 300


def _add(
    scheduler: AsyncIOScheduler,
    func: Callable[..., Awaitable[None]],
    job_id: str,
    trigger: CronTrigger,
    **kwargs: object,
) -> None:
    scheduler.add_job(
        func,
        trigger=trigger,
        id=job_id,
        name=job_id,
        kwargs=kwargs or None,
        max_instances=1,  # a slow cycle must never overlap the next one
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        replace_existing=True,
    )


def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=ET)

    # The autonomous decision cycle — reconcile, decide, journal, execute.
    _add(
        scheduler,
        run_intraday_cycle,
        "intraday_cycle",
        cycle_trigger(settings.cycle_interval_minutes),
    )

    # Keep intraday bars fresh so the engine never decides on stale prices.
    _add(
        scheduler,
        run_intraday_poll,
        "intraday_poll",
        CronTrigger(day_of_week=WEEKDAYS, hour="9-16", minute="0,15,30,45", timezone=ET),
    )

    # Advance open orders so late fills reach the ledger. Runs half past the hour, between
    # cycles, and once after the close for orders that filled near the bell.
    _add(
        scheduler,
        run_order_sync,
        "order_sync",
        CronTrigger(day_of_week=WEEKDAYS, hour="10-16", minute=30, timezone=ET),
    )

    # Pre-open pass picks up the vendor's overnight restatements; post-close ingests today.
    _add(
        scheduler,
        run_eod_ingest,
        "eod_ingest_preopen",
        CronTrigger(day_of_week=WEEKDAYS, hour=8, minute=30, timezone=ET),
        job_name="eod_ingest_preopen",
    )
    _add(
        scheduler,
        run_eod_ingest,
        "eod_ingest_postclose",
        CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=30, timezone=ET),
        job_name="eod_ingest_postclose",
    )

    # Fundamentals slice + rescore. Runs every day; fundamentals don't respect weekends.
    _add(
        scheduler,
        run_nightly,
        "nightly",
        CronTrigger(hour=2, minute=0, timezone=ET),
    )

    return scheduler
