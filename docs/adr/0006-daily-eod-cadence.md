# ADR-0006: Daily/EOD cadence, not real-time

**Status:** Accepted · 2026-07-25

## Context
Real-time streaming (websockets, tick data, live order books) multiplies infrastructure complexity — connection management, backpressure, intraday storage — while adding nothing to a research-driven, low-turnover strategy that rebalances at most weekly.

## Decision
BlackOak is an end-of-day system. Daily bars are ingested after close; scoring, snapshots, and metrics are computed nightly; orders execute once at 09:35 ET. Intraday freshness is limited to an hourly quote refresh for held and watchlisted symbols with a 60-second in-process cache.

## Consequences
- No Redis, no websockets, no streaming infra in v1; Postgres is the cache.
- The UI shows hourly-fresh (not tick-fresh) prices during market hours — an honest, documented trade-off.
- Related deferrals: roll-forward migration discipline (down-migrations exist, but recovery strategy is redeploy + roll forward) and `prices_daily` partitioning (deferred until >10M rows) are recorded here as operational simplicity choices in the same spirit.
