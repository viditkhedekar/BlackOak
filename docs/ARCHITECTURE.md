# BlackOak Architecture

How the system is put together and why. Consequential decisions have full trade-off write-ups in [adr/](adr/).

## 1. Opinionated Stack Decisions (with trade-offs)

| Decision | Choice | Alternatives & why not |
|---|---|---|
| Repo layout | **Monorepo** (`frontend/` + `backend/`) | Two repos = double CI config, version drift between API and client types. Monorepo keeps the OpenAPI-generated TS client in lockstep. |
| Auth | **Clerk** | Supabase Auth is fine, but Clerk's Next.js components + JWKS-verified JWTs in FastAPI is the cleanest cross-stack story and looks polished in a showcase. Trade-off: vendor lock-in (acceptable — auth is behind an interface). |
| Background jobs | **APScheduler in a dedicated worker process** | Celery needs Redis + broker ops for what is fundamentally a cron workload. APScheduler in *one* worker (never inside the API process — multi-worker API would double-fire jobs) is sufficient. Migration path to Celery/Arq documented in an ADR if we ever need distributed task fan-out. |
| Charts | **Apache ECharts** (`echarts-for-react`) + TradingView `lightweight-charts` for price/candlestick panes | Recharts is pleasant but weak at candlesticks, big series, and synced crosshairs. ECharts handles heatmaps/treemaps/large series; lightweight-charts gives the "terminal" feel for price charts. |
| Market data | **Provider abstraction (port/adapter)**. v1 adapters: **Alpaca Market Data** (free IEX feed, comes with the paper account) for OHLCV/quotes; **yfinance** for fundamentals + benchmark history (free, no key); **Financial Modeling Prep** adapter stubbed as the paid upgrade path for clean fundamentals/news | No single free source is good at everything. The abstraction is the architectural point: swapping providers must never touch domain code. |
| Deployment | **Vercel** (frontend) + **Railway** (API + worker + Postgres) | Railway over Fly/Render: bundled Postgres, simplest multi-service (API + worker) story, good DX for a solo project. |
| Optimizer | **v1: deterministic score-tilted inverse-volatility weighting with iterative constraint projection. v2 (Phase 8+): mean-variance via PyPortfolioOpt (Ledoit-Wolf shrinkage)** | Raw MVO first would be unstable (garbage-in expected returns) and unexplainable. Deterministic rules are auditable and demo well; MVO/HRP become an optional "optimizer mode" later. |
| AI | **Claude API** (`claude-sonnet-5` for analyst agents), structured outputs via tool-use → Pydantic | AI explains and flags; it never changes scores and never triggers trades in v1. |
| Money/quantities | `NUMERIC(18,6)` + Python `Decimal` everywhere; UUID PKs; all timestamps `timestamptz` UTC; market times via `exchange_calendars` (XNYS) | Floats for money is how fintech projects lose credibility. |
| Cadence | **Daily/EOD system, not real-time.** Intraday = hourly quote refresh only | Real-time streaming is deferred; it multiplies infra complexity for zero portfolio-project value. State this in the README as a deliberate design decision. |

---

## 2. System Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │                  Vercel                     │
                         │  Next.js (App Router, TS, Tailwind,         │
                         │  React Query, ECharts/lightweight-charts)   │
                         └──────────────┬──────────────────────────────┘
                                        │ HTTPS + Clerk JWT
                                        ▼
┌─────────────┐          ┌─────────────────────────────────────────────┐
│    Clerk    │◄────────►│              FastAPI (Railway)              │
│ (auth/JWKS) │          │  api/v1 routers → services → domain         │
└─────────────┘          │  (thin controllers, DTOs at the boundary)   │
                         └───────┬─────────────────────┬───────────────┘
                                 │                     │
                    ┌────────────▼──────────┐   ┌──────▼────────────────────┐
                    │      PostgreSQL       │   │   Adapters (ports impl)   │
                    │  (Railway, Alembic)   │   │  • MarketDataProvider     │
                    └────────────▲──────────┘   │    (Alpaca / yfinance /   │
                                 │              │     FMP)                  │
                    ┌────────────┴──────────┐   │  • BrokerClient (Alpaca   │
                    │  Worker (Railway,     │   │    paper)                 │
                    │  APScheduler)         │──►│  • LLMClient (Claude API) │
                    │  ingest / score /     │   │  • Notifier (email)       │
                    │  snapshot / rebalance │   └───────────────────────────┘
                    │  / reconcile / AI     │
                    └───────────────────────┘
```

**Module communication rules (clean architecture):**
- `domain/` — pure Python: scoring math, optimizer, metrics, order-planning logic. **No I/O, no SQLAlchemy, no HTTP.** Takes dataclasses/DataFrames in, returns results out. This is what makes the whole system unit-testable.
- `services/` — use-case orchestration ("run daily ingest", "build rebalance plan", "execute rebalance"). Calls domain functions, repositories, and adapter ports.
- `adapters/` — implementations of `Protocol` interfaces (`MarketDataProvider`, `BrokerClient`, `LLMClient`, `Notifier`) defined next to the services that consume them. Swappable, individually mockable.
- `api/` and `jobs/` are both thin entry layers over the same `services/` — the scheduler and the REST API never duplicate logic.
- Frontend talks **only** to FastAPI via a generated typed client (`openapi-typescript`); it never holds provider/broker keys.
- DB is the only shared state between API and worker. No message bus in v1 (ADR documents when one would be justified).

---

## 3. Repository Folder Structure

```
blackoak/
├── frontend/
│   ├── src/app/                    # App Router: (dashboard)/, research/, portfolio/,
│   │   │                           #   company/[symbol]/, trades/, performance/,
│   │   │                           #   risk/, settings/, sign-in/
│   │   ├── layout.tsx              # shell: sidebar nav, command palette, theme
│   │   └── providers.tsx           # Clerk + React Query providers
│   ├── src/components/
│   │   ├── ui/                     # primitives (shadcn/ui base)
│   │   ├── charts/                 # ECharts + lightweight-charts wrappers
│   │   └── features/               # feature-scoped components (portfolio/, research/…)
│   ├── src/lib/
│   │   ├── api/                    # generated OpenAPI client + fetch wrapper w/ auth
│   │   └── hooks/                  # React Query hooks per resource
│   └── e2e/                        # Playwright
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI factory, middleware, router mounting
│   │   ├── core/                   # config (pydantic-settings), logging, security deps
│   │   ├── api/v1/                 # routers: companies, screener, portfolio, orders,
│   │   │                           #   rebalance, analytics, watchlists, settings, admin
│   │   ├── schemas/                # Pydantic DTOs (request/response) — API contract
│   │   ├── services/               # ingest, scoring, portfolio, trading, analytics,
│   │   │                           #   ai_research, notification  (+ ports.py Protocols)
│   │   ├── domain/                 # PURE: factors.py, scoring.py, optimizer.py,
│   │   │                           #   metrics.py, rebalance_planner.py, order_planner.py
│   │   ├── adapters/               # alpaca_market_data.py, yfinance_data.py, fmp_data.py,
│   │   │                           #   alpaca_broker.py, claude_llm.py, email_notifier.py
│   │   ├── db/                     # models.py (SQLAlchemy 2.0), session.py, repositories/
│   │   └── jobs/                   # scheduler.py + one module per scheduled job
│   ├── worker.py                   # APScheduler entrypoint (separate Railway service)
│   ├── alembic/
│   ├── tests/                      # unit/ integration/ api/  + golden/ fixtures
│   └── pyproject.toml              # uv, ruff, mypy, pytest config
├── docs/                           # ARCHITECTURE.md, SCHEMA.md, ROADMAP.md, adr/ (ADRs)
├── .github/workflows/              # ci.yml, deploy.yml
├── docker-compose.yml              # local Postgres 16
└── README.md                       # flagship-quality: screenshots, architecture, decisions
```

---

## 6. Data Pipeline Design (ETL)

- **Fetch:** worker-scheduled, provider-abstracted. Prices: Alpaca bulk bars (batches of ~200 symbols/call). Fundamentals: yfinance, nightly rotating slices (~100 symbols/night → full universe weekly) to stay inside informal rate limits. News: per held/watchlisted symbol nightly.
- **Validate before insert:** OHLC coherence (low ≤ open/close ≤ high), positive prices, volume ≥ 0, date is XNYS session, |daily move| > 50% flagged for split-check rather than inserted blind. Invalid rows → quarantine log + job_runs error count, never partial-insert.
- **Dedup:** natural keys + `ON CONFLICT DO UPDATE` upserts everywhere (prices PK, fundamentals unique triple, news content_hash). Re-running any job is always safe — idempotency is the core pipeline invariant.
- **Caching:** Postgres is the cache (we own the data after ingest; API reads never hit providers). In-process TTL cache only for intraday quotes (60s). Redis deferred until measured need (ADR).
- **Retries:** tenacity — exponential backoff + jitter, 3 attempts, retry only on transport/429 errors; per-symbol isolation; >20% symbol failure rate → job marked failed → alert.
- **Error handling:** every run bracketed in job_runs; structured logs w/ run ID; failure notification (Phase 7); stale-data guard — scoring refuses to run on prices older than last session and surfaces *why*.

---

## 8. Portfolio Engine Spec (Phase 4)

1. **Universe filter:** composite ≥ 60th pct, avg $volume ≥ $5M/day, data completeness ≥ 80%, price ≥ $5.
2. **Selection:** top N by composite (N from risk profile: 12/18/25) with greedy sector-cap awareness.
3. **Base weights:** `w_i ∝ composite_i × (1/σ_i)` (score conviction tilted by inverse vol).
4. **Constraint projection (iterative clip-and-redistribute to convergence):** max position (default 10%), sector cap (default 30%), min position (2% — else dropped and weights recycled), target cash by profile (15/10/5%).
5. **Output:** target weights + machine-readable rationale per position (which constraints bound it).

Rebalance triggers: calendar (weekly proposal) + drift (any |actual−target| > 3% absolute or 20% relative) + exit rule (composite falls below 40th pct → flagged). Turnover control: no-trade band (skip diffs < 0.5% weight or < $50). v2 optimizer mode (post-Phase 8): PyPortfolioOpt MVO w/ Ledoit-Wolf shrinkage + same constraint set, offered as an alternative the UI can A/B against the deterministic engine — good README material. HRP noted as a third mode in Future.

---

## 9. Trading Engine Spec (Phase 5)

- **Auth:** keys server-side env only, never in DB or frontend in v1 (single user). If multi-user BYO-keys later: pgcrypto/KMS envelope encryption (ADR).
- **Consistency model:** DB owns *intent* (orders), broker owns *truth* (positions/fills). Every order gets our UUID as Alpaca `client_order_id` → resubmits are idempotent; unknown-state failures resolved by querying broker by client_order_id.
- **Execution:** sells before buys (frees cash), market orders, fractional shares, regular-hours only, submitted 09:35 ET (skip opening auction noise).
- **Lifecycle:** poller advances local status until terminal; rejects recorded w/ reason + alert + rebalance event marked partial; partial fills at day-end → cancel remainder, record actuals, fold residual into next drift check.
- **Reconciliation (nightly + on-demand):** diff broker vs local positions/orders → audit_log every discrepancy → correct local from broker → alert if material (>$1 or >0.001 qty).

---

## 13. AI Layer Spec (Phase 8)

All agents: Claude API, temperature 0, structured output via tool schema → Pydantic: `{stance: bullish|neutral|bearish, confidence: 0–1, key_points: [{claim, data_ref}], risks: []}`. **Every claim must carry a `data_ref` to a metric we passed in; prompts forbid outside knowledge of the company; refusal to fabricate is tested.** Inputs come only from our DB.

| Agent | Inputs | Focus |
|---|---|---|
| Value Analyst | value+profitability factors, 5y valuation trend | Is the price justified by fundamentals? |
| Growth Analyst | growth factors, revenue/EPS trajectory | Durability & quality of growth |
| Risk Manager | risk/vol factors, drawdown, β, position context | What kills this position? (veto-flavored: its bearish flags weighted 1.5×) |
| News Analyst | last 14d headlines | Material events vs noise |
| Macro Analyst | sector ETF trends, rates level, SPY regime | Sector/market context (shared run/day, cached) |
| PM Synthesizer | all agent outputs + composite score + position status | Final thesis, confidence-weighted |

**Disagreement resolution:** PM computes stance spread; if max-confidence agents conflict (e.g., Value bullish 0.8 vs Risk bearish 0.7) the thesis is labeled **Contested** and both cases are presented — disagreement is surfaced as product honesty, not averaged away. PM confidence = weighted mean × (1 − disagreement penalty). AI output never mutates scores or triggers trades.

---

## 11. Frontend Pages (what's on each)

- **Dashboard:** equity + day P&L hero; equity-vs-SPY sparkline; allocation donut; top movers in portfolio; pending-rebalance banner; AI market summary card (Phase 8); recent activity feed.
- **Portfolio:** positions table (qty, value, weight vs target w/ drift bars, unrealized P&L, composite score); constraint compliance panel; rebalance preview/execute flow.
- **Research (screener):** score-sortable universe table w/ heat-cells per category; sector/score filters; watchlist stars; saved views.
- **Company page:** header (price, day move, sector, market cap); candlestick chart w/ ranges; score radar + factor drill-down (raw → percentile → score); fundamentals table & trend charts; news list; AI thesis tab (per-agent stances, confidence, disagreements); position/order info if held.
- **Trade History:** orders + fills, status chips, reject reasons, link to originating rebalance event and its narrative.
- **Performance:** metric cards (all §10); equity curve vs benchmark; drawdown chart; monthly-returns heatmap; period selector.
- **Sector Analysis:** allocation vs SPY sector weights (over/underweight bars); sector contribution to return; sector score heatmap.
- **Risk Analysis:** beta, vol, VaR(95, historical), concentration gauges, drawdown table, correlation matrix of holdings.
- **Settings:** risk profile, constraint sliders w/ live validation, auto-rebalance toggle, notifications, (BYO-keys placeholder), danger zone.
- **Benchmark comparison** lives inside Performance (not a separate page — avoids nav sprawl).

---

## 12. Scheduled Jobs (worker, XNYS-calendar-aware, all logged to job_runs)

| When (ET) | Job |
|---|---|
| 08:30 trading days | Pre-market: sync account, reconcile positions, check corporate actions/splits, data-freshness gate |
| 09:35 trading days | Execute approved/auto rebalance orders |
| Hourly 10–15 | Refresh quotes (held + watchlist), advance open-order statuses |
| 16:30 trading days | EOD: ingest bars → snapshot portfolio → compute metrics → drift check → propose rebalance if triggered |
| 02:00 daily | Fundamentals slice, news ingest, rescore universe, refresh stale/changed AI theses |
| Sunday 18:00 | Universe maintenance, data-quality audit, weekly rebalance proposal + narrative, summary email, DB backup |

### Equity-curve snapshots

`portfolio_snapshots` is written by three paths, tagged in its `source` column. The curve
was previously fed only by the decision cycle, which made it hostage to that job: a
rejected order raised before the write and cost the run its point entirely, and a worker
that was down over a session left no marks at all.

| `source` | Written by | Carries |
|---|---|---|
| `cycle` | The decision cycle, in a `finally` so a failed run still marks where equity stood | equity, cash, positions, regime, holdings |
| `poll` | The 15-minute intraday poll — equity moves with the market, not only with trades | equity, cash, positions, regime, holdings |
| `backfill` | `cli backfill-equity`, reading the broker's own account history | equity only |

Only equity is knowable for every source, so the rest are nullable rather than filled with
plausible-looking zeros. `PortfolioSnapshotRepository.latest()` (which the dashboard reads
for cash and regime) skips `backfill` rows for that reason; the performance endpoint uses
all of them.

Backfill is gap-fill only and idempotent — a timestamp that already has a live row keeps
it. Alpaca constrains timeframe by period (a period over 30 days must use `1D`):

```
uv run python -m app.cli backfill-equity --period 1M --timeframe 1D
uv run python -m app.cli backfill-equity --period 1W --timeframe 15Min
```

---

## 14. API Surface (REST, `/api/v1`, OpenAPI → generated TS client)

```
GET    /health
GET    /companies?query&sector&sort&page          GET /companies/{symbol}
GET    /companies/{symbol}/prices?range           GET /companies/{symbol}/fundamentals
GET    /companies/{symbol}/scores                 GET /companies/{symbol}/news
GET    /companies/{symbol}/ai-thesis
GET    /screener?minScore&sector&sortBy…
GET|PUT /me/settings
GET|POST /watchlists    POST|DELETE /watchlists/{id}/items/{symbol}
GET    /portfolio        GET /portfolio/positions
GET    /portfolio/performance?range   GET /portfolio/allocation
POST   /rebalance/preview   POST /rebalance/{id}/approve   POST /rebalance/{id}/execute
GET    /rebalance?status    GET /rebalance/{id}
GET    /orders?status    POST /orders    DELETE /orders/{id}
GET    /trades?range
GET    /analytics/metrics?range   /analytics/benchmark   /analytics/risk   /analytics/sectors
GET    /admin/jobs?name&status      (admin-gated)
POST   /webhooks/clerk              (svix-verified)
```

---

## 15. Security

- Secrets: env-only (Railway/Vercel/GH-Actions secrets); `.env` gitignored from commit #1; exposed Alpaca keys rotated; no broker/LLM keys ever reach the browser.
- AuthN: Clerk JWT verified via JWKS in a FastAPI dependency. AuthZ: repository-level user_id scoping (cross-user access structurally impossible), admin endpoints role-gated.
- Rate limiting: slowapi per-user/IP (60/min read, 10/min mutating). Strict CORS (exact Vercel origins). Standard security headers.
- Audit: audit_log on every order, execution, settings change, rebalance approval, reconciliation correction.
- Trading safety rails: `paper=True` asserted in the adapter, base URL allowlist (`paper-api.alpaca.markets` only), per-order notional cap, per-day order-count cap.

---

## 16. Testing Strategy

- **Unit (largest layer):** all of `domain/` — pure functions, golden files for scoring/metrics/optimizer, Hypothesis property tests (score bounds, weight sums, constraint satisfaction, drawdown sign).
- **Integration:** services against real Postgres (testcontainers) + respx-mocked providers; ingest idempotency; reconciliation drift-injection.
- **API:** httpx AsyncClient suite per router incl. authz-isolation matrix; schemathesis fuzz against OpenAPI in CI.
- **Frontend:** Vitest + Testing Library for logic-bearing components; Playwright e2e for the 4 golden paths (sign-in→dashboard, screener→company, rebalance preview→execute vs mocked API, settings save).
- **Paper trading:** live-Alpaca marked suite (tiny notional) run nightly + pre-release, not on every PR.
- **Regression:** goldens for every domain engine; `engine_version` bump required to change them (reviewable diffs).
- **Load:** Locust, Phase 9 — 50 concurrent read-users, p95 < 300ms.

---

## 17. CI/CD

- **ci.yml (every PR):** ruff+mypy+pytest (Postgres service container) ∥ eslint+tsc+vitest+build ∥ `alembic upgrade head` on empty DB + no-pending-migrations check; schemathesis; goldens.
- **deploy.yml (merge to main):** backend → Railway (migrations run as release step **before** new code serves traffic → migrations must be backward-compatible with previous release: additive first, cleanup later); frontend → Vercel auto; Sentry release tagging.
- **Rollback:** Railway one-click redeploy previous image + Vercel instant rollback; DB rollback strategy is *roll forward* (down-migrations exist but the discipline is compatible-migrations, documented in ADR).
- **Monitoring:** Sentry (both stacks), structlog JSON → Railway logs, `/health` uptime pings (UptimeRobot), job_runs panel as the pipeline health UI.

---

## 21. Modularity Rules (enforced from day 1)

1. `domain/` imports nothing from services/adapters/db — CI-enforced via import-linter contract.
2. All I/O behind `Protocol` ports; adapters are leaf nodes; every port has a fake for tests.
3. API & jobs are thin shells over shared services — logic is never defined in a router or a job.
4. Pydantic DTOs at every boundary; SQLAlchemy models never serialized to the wire.
5. Frontend consumes only the generated OpenAPI client — type drift is a build failure.
6. ADRs (`docs/adr/`) for every consequential decision — starting with the ones in §1.
7. Conventional commits + PR-per-issue even solo: the git history is part of the portfolio.

---

## Execution Plan for the First Session (upon approval)

Scope: **Phase 0 only** (plus repo docs). Steps:

1. Write `.gitignore` (`.env`, node_modules, __pycache__, .venv, etc.) → `git init` → initial commit. Remind user to rotate the Alpaca keys currently in `.env`.
2. Materialize this plan into `docs/` (ROADMAP.md, ARCHITECTURE.md, SCHEMA.md, adr/0001-0006 for §1 decisions) and a flagship-grade README skeleton.
3. Scaffold `backend/` (uv, FastAPI, settings, structlog, SQLAlchemy+Alembic w/ migration 001, `/health` with DB check, pytest+ruff+mypy) and `docker-compose.yml` (Postgres 16).
4. Scaffold `frontend/` (Next.js, TS, Tailwind, shadcn/ui dark shell, React Query, generated API client, status page hitting `/health`).
5. `.github/workflows/ci.yml` (both stacks + migration check).
6. Keep `start.py` briefly as a smoke-test reference, then fold its check into `backend/app/adapters/` in Phase 5 and delete it.

### Verification (Phase 0 gate)
- `docker compose up -d` → `uvicorn` → `curl localhost:8000/health` returns `{"status":"ok","db":"ok"}`.
- `cd backend && pytest && ruff check . && mypy .` all pass.
- `cd frontend && npm run build && npm test` pass; dev server page renders live health data from the API (verified in the browser pane).
- `git log` shows clean initial commits with `.env` absent from tracking (`git ls-files | grep -c "^\.env$"` → 0).
- (Deploy to Railway/Vercel needs the user's accounts — I'll prepare configs and document the exact steps; actual account hookup is a user action.)
