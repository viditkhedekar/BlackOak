# BlackOak Roadmap

The full journey from empty repo to polished v1.0, in gated phases. A phase is *done* only when its gate passes — no skipping ahead.

## 5. Phased Roadmap

> Complexity: S/M/L/XL. Timeline assumes solo, ~10–15 focused hrs/week. Every phase ends with a **gate** — do not proceed until it passes.

### Phase 0 — Foundations & Walking Skeleton (S, ~1 week)
- **Objectives:** monorepo scaffold, tooling, CI, deploy pipeline proven end-to-end with a trivial slice.
- **Outcome:** `GET /health` returns DB-checked 200 in production; Next.js page renders API data; CI green.
- **Backend:** uv + FastAPI skeleton, pydantic-settings config, structlog JSON logging, SQLAlchemy 2.0 + Alembic (migration 001: users, job_runs), docker-compose Postgres, ruff/mypy/pytest.
- **Frontend:** Next.js + TS + Tailwind + shadcn/ui shell (dark "terminal" theme), React Query provider, generated API client wired to `/health`.
- **Infra:** `.gitignore` **before** `git init` (protect `.env`; rotate the exposed Alpaca keys), GitHub repo, GitHub Actions CI (lint+type+test both stacks), deploy skeleton to Railway + Vercel, Sentry DSNs wired.
- **Testing:** one real unit test each side; CI enforces lint/type/test.
- **Gate:** production URL renders data fetched from the deployed API.

### Phase 1 — Market Data Foundation (M, ~2 weeks) — ✅ BUILT
- **Status:** implemented & verified. 503 S&P 500 constituents seeded (11 GICS sectors); provider abstraction with yfinance + Alpaca IEX adapters; idempotent upsert pipeline with per-symbol isolation + failure-ratio abort; XNYS-aware 16:30 ET EOD job; `/companies`, `/companies/{symbol}`, `/companies/{symbol}/prices`; React research search + lightweight-charts candlestick company page. 27 backend tests green. Representative backfill run: 25 symbols × 1y batched, 6,250 rows, zero failures, re-run produced zero duplicates. Remaining before Phase 2: full 503 × 2y production backfill + observe 3 consecutive green nightly runs.
- **Objectives:** universe + prices flowing on a schedule through the provider abstraction.
- **DB:** companies, prices_daily, benchmarks(+prices), job_runs usage.
- **Backend:** `MarketDataProvider` Protocol; Alpaca + yfinance adapters; universe seeder (S&P 500 constituents); backfill CLI (2y daily bars, batched, rate-limited); EOD ingest service (validation: OHLC sanity, non-negative volume, gap detection vs XNYS calendar; dedupe via upsert on PK; per-symbol retry w/ tenacity exponential backoff; symbol-level failure isolation — one bad ticker never kills the run); worker process with APScheduler running the 16:30 ET job; `/companies`, `/companies/{symbol}/prices` endpoints.
- **Frontend:** company search + company page v1 with candlestick chart (lightweight-charts) + range selector.
- **Testing:** adapter tests against recorded HTTP fixtures (respx); validation unit tests (bad rows quarantined, not inserted); idempotency test (re-run ingest → zero dupes).
- **Gate:** 500 symbols × 2y backfilled; nightly job runs green 3 consecutive days; job_runs visible.

### Phase 2 — Deterministic Research Engine (L, ~2–3 weeks)
- **Objectives:** the platform's brain — 8-category scoring, fully explainable. **No AI.**
- **DB:** fundamentals, research_scores.
- **Backend:** fundamentals ingest (yfinance adapter, nightly rotating batches); `domain/factors.py` (pure factor computations) + `domain/scoring.py` (winsorize 1/99 → sector-relative z-score → percentile 0–100 → weighted composite; weights per risk profile); scoring job after EOD ingest; screener endpoint (filter/sort on scores); scores + factor breakdown endpoints.
- **Scoring spec (§7 below is the contract).**
- **Frontend:** Research/screener page (sortable score table, sector filter, score heat cells); company page adds score radar chart + factor drill-down table showing *raw metric → sector percentile → score* (the money shot for explainability).
- **Testing:** **golden-file tests** — fixed input fixtures → exact expected scores, committed; property tests (scores always 0–100, monotonic in inputs); regression suite reruns goldens on every engine change; `engine_version` bumps recorded.
- **Gate:** scores for full universe reproducible from `inputs jsonb`; goldens locked in CI.

### Phase 3 — Auth & User Preferences (S, ~1 week)
- **Objectives:** Clerk auth end-to-end; user settings + watchlists.
- **DB:** user_settings, watchlists, watchlist_items; users synced via Clerk webhook.
- **Backend:** JWKS JWT verification dependency (`get_current_user`), row-level scoping in every user repo (queries always filter by user_id), settings + watchlist CRUD.
- **Frontend:** sign-in/up, protected layout, Settings page (risk profile + constraint sliders), watchlist star on company/screener rows.
- **Testing:** authz tests are the point — user A must 404/403 on user B's resources; unauthenticated → 401.
- **Gate:** two test users fully isolated in prod.

### Phase 4 — Portfolio Construction Engine (L, ~2 weeks)
- **Objectives:** deterministic target portfolio from scores + user constraints; rebalance planner (dry-run only — no broker yet).
- **DB:** portfolios, rebalance_events.
- **Backend:** `domain/optimizer.py` v1 (spec §8); `domain/rebalance_planner.py` (current vs target → trade list with no-trade bands + min-trade-size); preview endpoint returning full plan + per-position rationale strings ("AAPL 8.2%: composite 87, capped by 10% max position…").
- **Frontend:** Portfolio page v1: proposed allocation (donut + table), constraint compliance readout, rebalance preview modal with the trade list and rationale per line.
- **Testing:** heavy unit coverage of constraint math (each constraint individually + combined; infeasible-constraint detection with clear errors); golden allocations for fixed score fixtures; property test: weights sum to 1−cash within ε, all constraints satisfied.
- **Gate:** for any settings combo, engine emits valid, explainable allocation or a human-readable infeasibility reason.

### Phase 5 — Trading Engine: Alpaca Integration (L, ~2 weeks)
- **Objectives:** execute rebalance plans as real paper orders; local DB never drifts from broker.
- **DB:** positions, orders, executions; audit_log live.
- **Backend:** `BrokerClient` Protocol + Alpaca adapter (`paper=True` **hard-asserted at adapter construction** — refuses live URLs); order lifecycle (spec §9); execute-rebalance service (sells first, then buys, market orders, fractional, regular hours only); order status poller job; **nightly reconciliation**: Alpaca positions/orders vs local → discrepancies audited + local corrected from broker; cancel endpoint; manual paper order endpoint.
- **Frontend:** Trade History page (orders + fills, status chips, reject reasons); Portfolio page switches to live positions w/ unrealized P&L; "Execute rebalance" flow with confirm step.
- **Testing:** order state machine unit tests (every transition incl. reject/partial/cancel); integration tests against Alpaca paper (CI-gated, marker `alpaca`, small notional); reconciliation tests (inject drift → detected + corrected); idempotency (double-submit same client_order_id → one broker order).
- **Gate:** full rebalance executes on paper account; kill worker mid-execution → recovery run reconciles cleanly.

### Phase 6 — Analytics & Performance (M, ~2 weeks)
- **Objectives:** every metric in §10, benchmark-relative, from daily snapshots.
- **DB:** portfolio_snapshots.
- **Backend:** EOD snapshot job; `domain/metrics.py` (pure, spec §10); analytics endpoints (metrics by range, equity curve vs SPY, drawdown series, sector allocation, concentration, per-lot win/loss via FIFO matching of executions).
- **Frontend:** Dashboard (real numbers), Performance page (equity vs benchmark, drawdown chart, metric cards, monthly return heatmap), Sector & Risk analysis pages (§11).
- **Testing:** metrics golden tests against hand-computed known series (the classic Sharpe-off-by-√252 class of bug); TWR test with mid-period cash flow; property: max drawdown ≤ 0.
- **Gate:** metrics match hand-verified spreadsheet on a known fixture series.

### Phase 7 — Full Automation & Notifications (M, ~1 week)
- **Objectives:** hands-off daily loop; failures never silent.
- **Backend:** complete job suite (§12) incl. drift-triggered rebalance proposals (auto-execute only if user opted in); `Notifier` port + email adapter (Resend); weekly summary email; job-failure alerts; admin job-runs endpoint.
- **Frontend:** notification prefs in Settings; job status panel (admin); "proposed rebalance awaiting approval" banner + approve flow.
- **Testing:** time-freeze tests for scheduling (holiday/half-day handling via calendar); job idempotency (double-fire = no double effects); e2e dry-run of full daily cycle against staging.
- **Gate:** 5 consecutive trading days fully hands-off, correct snapshots/metrics, zero silent failures.

### Phase 8 — AI Research Layer (L, ~2–3 weeks)
- **Objectives:** multi-agent explanation engine (spec §13). AI explains; deterministic engine still decides.
- **DB:** ai_recommendations (+ news_articles ingest live).
- **Backend:** `LLMClient` port + Claude adapter (structured outputs via tool-use → Pydantic, temperature 0); agents: Value, Growth, Risk, News, Macro + PM synthesizer; news ingest job; AI thesis job (only for held/watchlisted/top-decile names, regenerated only on material change — score Δ>10, stance-relevant news, or 7-day staleness → cost control); rebalance narrative generation; token/cost tracking in job_runs.
- **Frontend:** company page AI thesis tab (stance, confidence, per-agent breakdown incl. disagreements shown honestly, "generated by model X on date Y from the data shown on this page"); Dashboard AI market-summary card; rebalance modal gains narrative.
- **Testing:** contract tests on mocked LLM (malformed JSON → retry w/ repair prompt → skip+log, never crash pipeline); prompt regression fixtures; cost ceiling test (run refuses if projected tokens exceed budget).
- **Gate:** theses cite only real DB numbers (spot-audited), pipeline survives LLM outage (analytics unaffected), monthly AI cost projection < $15 at v1 scale.

### Phase 9 — Production Hardening & Showcase Polish (M, ~1–2 weeks)
- **Objectives:** the "this person can ship" phase.
- **Backend:** rate limiting (slowapi), security headers, strict CORS, request-ID logging correlation, uptime monitor, load test (Locust: 50 concurrent users on read endpoints), pg_dump backup job + restore drill.
- **Frontend:** loading/error/empty states everywhere, command palette (⌘K symbol search), responsive pass, Lighthouse ≥ 90, **read-only demo mode** (recruiters explore without signing up — highest-ROI showcase feature).
- **Docs:** README with architecture diagram + screenshots + honest "design decisions & trade-offs" section; ADRs; CONTRIBUTING.
- **Gate:** cold visitor → demo mode → understands the product in 2 minutes; Sentry quiet for a week.

**Total: ~16–19 weeks part-time.**

---

## 18. Milestones (GitHub Projects)

M0 Walking skeleton deployed → M1 Data pipeline live (500×2y, 3 green nightly runs) → M2 Scoring engine + screener → M3 Auth & preferences → M4 Portfolio engine (dry-run) → M5 First automated paper trade → M6 Analytics complete → M7 Fully autonomous week → M8 AI research live → M9 v1.0 public (demo mode + README). One milestone per phase; issues = the phase's task bullets; labels: `domain`, `pipeline`, `frontend`, `infra`, `ai`.

---

## 19. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Free data providers break/limit (esp. yfinance) | Provider port makes swaps a 1-file change; FMP adapter stubbed as paid fallback; quarantine+alerting catches silent schema drift |
| Bad data → bad scores/trades silently | Validation gates, stale-data refusal in scoring, golden regression suite, `inputs jsonb` auditability |
| Local/broker state drift | client_order_id idempotency + nightly reconciliation with broker-as-truth |
| Timezone/calendar bugs (classic) | exchange_calendars everywhere, UTC storage, time-frozen tests incl. holidays/half-days |
| LLM cost creep | Change-triggered regeneration only, per-run token budget with hard refusal, cost logged per run |
| Hallucinated AI claims undermine credibility | data_ref-required schema, no-outside-knowledge prompts, spot-audit tests |
| Scope creep kills flagship polish | Phase gates; deferred list (§20) is a contract; new ideas → GitHub issues, not detours |
| Solo-dev burnout mid-roadmap | Every phase ends deployed & demoable — the project is showcase-worthy from M2 onward, not only at M9 |
| Alpaca outage during execution window | Orders idempotent + resumable; execution job re-runnable; partial rebalance folds into next drift check |

---

## 20. Deferred to Post-v1 (deliberately)

Backtesting engine (biggest one — schema's immutable events/snapshots are designed so it's buildable later without rework), options/crypto paper trading, ETF portfolios, Monte Carlo simulation, factor-investing module & regime detection, custom strategy builder, portfolio replay, mobile app, real-time streaming quotes/websockets, Redis, Celery, multi-portfolio-per-user UI (schema already allows it), BYO Alpaca keys, MVO/HRP optimizer modes (fast-follow after Phase 8).
