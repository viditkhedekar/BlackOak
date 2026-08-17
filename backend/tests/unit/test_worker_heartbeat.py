"""Worker-alive staleness check behind the dashboard's "worker not running" banner.

Regression for a false alarm on the free-tier deploy: GitHub Actions cron replaces the
persistent app.worker process there, and GitHub's own cron is documented to run 5-15+ min
late under platform load. Two slow-but-healthy 15-min heartbeats in a row can leave a 30+
min gap with nothing actually wrong. The threshold was tuned for the persistent worker's
tight cadence (20 min) and flagged a working free-tier deploy as down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.v1.trading import HEARTBEAT_STALE_MINUTES, _is_worker_running

NOW = datetime(2026, 8, 17, 17, 0, tzinfo=UTC)


def test_no_heartbeat_ever_is_not_running() -> None:
    assert _is_worker_running(NOW, None) is False


def test_recent_heartbeat_is_running() -> None:
    assert _is_worker_running(NOW, NOW - timedelta(minutes=5)) is True


def test_gh_actions_cron_slop_is_still_running() -> None:
    """The exact gap observed on the free-tier deploy: two on-time-ish but GH-Actions-slow
    15-min polls in a row, ~25 min apart, while decision_cycle kept running successfully."""
    assert _is_worker_running(NOW, NOW - timedelta(minutes=25)) is True


def test_genuinely_stale_is_not_running() -> None:
    assert _is_worker_running(NOW, NOW - timedelta(minutes=HEARTBEAT_STALE_MINUTES + 1)) is False


def test_exactly_at_threshold_is_running() -> None:
    assert _is_worker_running(NOW, NOW - timedelta(minutes=HEARTBEAT_STALE_MINUTES)) is True
