# ADR-0003: APScheduler in a dedicated worker, not Celery

**Status:** Accepted · 2026-07-25

## Context
All background work is cron-shaped (EOD ingest, nightly scoring, scheduled execution, reconciliation). Celery would add a broker (Redis), result backend, and operational surface for a capability we don't need: distributed task fan-out.

## Decision
APScheduler running in a single dedicated worker process (`backend/worker.py`), deployed as its own Railway service. **Never inside the API process** — a multi-worker API would double-fire every job. The DB is the only shared state between API and worker; jobs are idempotent, so a duplicate or re-run is always safe.

## Consequences
- Zero extra infrastructure; jobs are plain Python calling the same `services/` layer as the API.
- Single point of scheduling: if the worker is down, jobs are missed (mitigated by idempotent catch-up logic on next run and job_runs alerting).
- Revisit (migrate to Celery/Arq + Redis) only if we need parallel task fan-out or sub-minute latency — e.g., a future backtesting engine.
