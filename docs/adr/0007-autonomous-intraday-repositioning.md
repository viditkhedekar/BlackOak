# ADR-0007: Repositioning to a fully autonomous intraday strategy

**Status:** Accepted · 2026-07-25 · supersedes ADR-0002 (Clerk auth) and ADR-0006 (daily/EOD cadence) for the v2 product

## Context
Phases 0–2 delivered an EOD research platform: daily bars, an 8-category deterministic research score, and a screener. The owner has repositioned the product from a multi-user research tool into a **single-user, fully autonomous intraday paper-trading strategy** that picks and exits positions by itself, with no approval gates and no user-created strategies. The objective is to beat the S&P 500 via weighted scoring over six signal families (valuation, fundamentals, momentum, technical, risk, macro), with explainability as a hard requirement. Sentiment is excluded by design.

This changes three decisions locked earlier: EOD cadence (ADR-0006), Clerk auth on the critical path (ADR-0002), and the human-in-the-loop rebalance approval flow (v1 Phase 4/5).

## Decision
- **Cadence:** the engine decides every 30 minutes during regular trading hours (09:45–15:45 ET, 13 cycles/day). Bars are ingested at 15-minute granularity for finer indicator resolution; the engine acts on every other poll. This supersedes ADR-0006's EOD-only cadence.
- **Autonomy:** the strategy places and closes paper orders with no human approval. Safety is enforced by layered fuses (cycle staleness halt, daily-loss halt, drawdown de-risk) and adapter-level caps, not by a person clicking approve.
- **Single user:** the owner is the only user. Clerk auth and multi-user row scoping (ADR-0002) leave the critical path and are postponed; the API is single-tenant for v2.
- **Explainability preserved:** every cycle persists a `trade_decisions` record (full evidence) before acting. The engine and the backtester call identical pure domain functions (see ADR-0008).
- **Honesty:** performance is measured against SPY **and** equal-weight RSP with costs modeled. Beating SPY is treated as an experiment; the auditable engineering is the guaranteed deliverable.

## Consequences
- Intraday storage returns (the `bars_intraday` table, ~120-day retention) — the opposite of ADR-0006's "Postgres-as-cache, no intraday storage" stance, justified by the new cadence.
- The old `research_scores` engine stays frozen and running until the dashboard switches to `strategy_scores`, then it retires. Its golden tests remain valid (engine unchanged).
- Deferred by this repositioning: Clerk/multi-user, watchlists, approval-gated rebalancing, the AI explanation layer, and the weekly portfolio-rebalance engine.
- No real money, ever, in this product: the broker adapter hard-asserts the Alpaca paper endpoint.
