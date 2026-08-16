"""The trading schedule, in one place (docs/ARCHITECTURE.md §12).

Both entry layers sit on this: ``jobs/scheduler.py`` turns these into APScheduler triggers,
and the API reads ``next_cycle_at`` so the dashboard can count down to the next cycle. The
definition lives here rather than in either shell so the countdown can never drift from
what the worker actually runs.

Cron alone would fire on market holidays (they are weekdays), so ``next_cycle_at`` walks
forward over non-sessions the same way the jobs skip them at run time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.domain.calendar import is_trading_day

ET = ZoneInfo("America/New_York")

# RTH is 09:30-16:00 ET. The decision cycle wakes on the hour from 10:00 to 15:00 - after
# the opening auction has settled, and never so late that a fill straddles the close.
CYCLE_HOURS = "10-15"
WEEKDAYS = "mon-fri"

# Enough lookahead to clear the longest market-holiday stretch without unbounded looping.
MAX_LOOKAHEAD_DAYS = 14


def minute_expr(interval_minutes: int) -> str:
    """Cron minute field for an every-N-minutes cadence within the hour."""
    if not 1 <= interval_minutes <= 60 or 60 % interval_minutes != 0:
        raise ValueError(
            f"cycle_interval_minutes must divide 60 evenly (got {interval_minutes})"
        )
    return ",".join(str(m) for m in range(0, 60, interval_minutes))


def cycle_trigger(interval_minutes: int) -> CronTrigger:
    return CronTrigger(
        day_of_week=WEEKDAYS,
        hour=CYCLE_HOURS,
        minute=minute_expr(interval_minutes),
        timezone=ET,
    )


def in_trading_hour_range(now: datetime, start_hour: int, end_hour: int) -> bool:
    """Weekday + trading-calendar + ET-hour gate (inclusive both ends).

    Exists for the free-tier deploy: GitHub Actions cron only understands UTC and can't
    shift for DST, so each ``.github/workflows/schedule-*.yml`` brackets a UTC window wide
    enough to cover both EST and EDT for a job's true ET window, firing it up to an hour
    more often than intended. This narrows that bracket back to the real window so the
    extra firing is a no-op rather than an extra trade or ingest.
    """
    et_now = now.astimezone(ET)
    return (
        et_now.weekday() < 5
        and is_trading_day(et_now.date())
        and start_hour <= et_now.hour <= end_hour
    )


def in_et_hour(now: datetime, hour: int) -> bool:
    """Same DST-bracket narrowing for a once-daily job with no weekday gate (nightly)."""
    return now.astimezone(ET).hour == hour


def next_cycle_at(interval_minutes: int, now: datetime | None = None) -> datetime | None:
    """When the next decision cycle actually runs, skipping market holidays.

    Returns None if no session falls inside the lookahead window (only reachable with an
    implausible calendar, but the caller should not have to assume).
    """
    trigger = cycle_trigger(interval_minutes)
    cursor = now.astimezone(ET) if now else datetime.now(ET)

    for _ in range(MAX_LOOKAHEAD_DAYS):
        fire: datetime | None = trigger.get_next_fire_time(None, cursor)
        if fire is None:
            return None
        if is_trading_day(fire.date()):
            return fire
        # A holiday invalidates every fire time that day, so jump the whole day.
        cursor = (fire + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return None
