# BlackOak

**An AI-powered investment research, portfolio construction, and paper trading platform** — a miniature quantitative hedge fund that ingests market data, scores companies with a fully deterministic factor engine, builds constraint-aware portfolios, executes on Alpaca Paper Trading, and uses AI to *explain* every decision (never to make them).

> ⚠️ Paper trading only. BlackOak never touches real money and is not investment advice.

## What it does

- **Ingests** EOD prices, fundamentals, and news for the S&P 500 universe on a schedule
- **Scores** every company across 8 factor categories (Health, Growth, Value, Quality, Profitability, Momentum, Volatility, Risk) — sector-relative, reproducible, every input auditable
- **Constructs** portfolios deterministically from scores + your constraints (max position, sector caps, min position, cash target, risk profile)
- **Executes** rebalances automatically via Alpaca Paper Trading, with idempotent orders and nightly broker reconciliation
- **Tracks** CAGR, Sharpe, Sortino, max drawdown, alpha/beta vs SPY, and more from immutable daily snapshots
- **Explains** each position with a multi-agent AI research desk (Value / Growth / Risk / News / Macro analysts + a PM synthesizer) that may only cite data from the database — disagreements are surfaced, not averaged away

## Architecture

```
Next.js (Vercel) ──JWT──▶ FastAPI (Railway) ──▶ PostgreSQL
                              │    ▲
                 Adapters ◀───┘    └─── APScheduler worker
          (Alpaca · yfinance · Claude API)   (ingest · score · trade · reconcile)
```

Clean architecture: pure `domain/` (scoring, optimizer, metrics — no I/O) ← `services/` (use-cases) ← thin `api/` + `jobs/` shells, with all I/O behind `Protocol` ports. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Stack

Next.js · TypeScript · Tailwind · React Query · ECharts + lightweight-charts · FastAPI · SQLAlchemy 2.0 · Alembic · PostgreSQL · Clerk · APScheduler · Alpaca Paper API · Claude API · Railway + Vercel

## Status

🚧 **Phase 0 — walking skeleton.** Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md). Design decisions with trade-offs: [docs/adr/](docs/adr/).

## Local development

```bash
# backend
docker compose up -d            # Postgres 16
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000/health

# frontend
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

Copy `backend/.env.example` → `backend/.env` and fill in keys (never committed).

## Deployment (free tier)

The architecture diagram above assumes Railway for the API + worker, matching [ADR-0003](docs/adr/0003-apscheduler-worker.md). Railway's free tier is now a small one-time trial credit rather than an ongoing free plan, so a genuinely $0/month deploy swaps two pieces:

| Piece | Free host | Note |
|---|---|---|
| Frontend | [Vercel](https://vercel.com) | Auto-detects Next.js, zero config beyond an env var |
| Database | [Neon](https://neon.tech) | Serverless Postgres, 0.5GB free tier |
| API | [Render](https://render.com) free web service | Spins down after 15 min idle, ~30s cold start on wake |
| Worker | **GitHub Actions cron**, not a persistent process | Replaces `app.worker`'s APScheduler loop — see below |

**Why not a persistent worker?** No major host gives away 24/7 compute for free. Instead, `.github/workflows/schedule-*.yml` fire `uv run python -m app.cli schedule-job <job>` on a cron matching the ADR's original schedule. GitHub Actions cron is UTC-only and can't shift for Daylight Saving, so each workflow's cron brackets a UTC window wide enough to cover both EST and EDT for the job's true ET window, then `app/services/schedule.py`'s `in_trading_hour_range`/`in_et_hour` re-check the real window before doing anything — an extra firing outside the true window is a no-op, not an extra trade. All jobs are idempotent (upserts, deterministic order IDs), so this degrades the same way the ADR already accepts a worker outage degrading: a missed or late run catches up next time.

Steps:

1. **Database** — create a Neon project, copy its connection string. It arrives as `postgresql://...?sslmode=require`; the app's `DATABASE_URL` needs the `postgresql+asyncpg://` scheme instead of plain `postgresql://` (asyncpg handles the `sslmode`/`channel_binding` query params automatically — see `app/db/session.py`). Run `uv run alembic upgrade head` once against it locally (point `DATABASE_URL` at Neon temporarily) to create the schema, or let Render's start command do it on first deploy.
2. **API** — import this repo at [render.com/select-repo](https://dashboard.render.com/select-repo); it reads `render.yaml` automatically. Fill in `DATABASE_URL`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` in the Render dashboard's Environment tab (left blank in the blueprint on purpose).
3. **Frontend** — import the repo at [vercel.com/new](https://vercel.com/new), set root directory to `frontend`, add env var `NEXT_PUBLIC_API_URL` = the Render service's URL.
4. **Close the loop** — update `CORS_ORIGINS` on Render to the real Vercel URL (it starts as `[]`, which blocks everything).
5. **Scheduled jobs** — in the repo's GitHub Settings → Secrets and variables → Actions, add `DATABASE_URL`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (same values as Render). The five `schedule-*.yml` workflows pick them up automatically; each also has a `workflow_dispatch` trigger for a manual test run from the Actions tab.

## Design decisions & trade-offs

Deliberate choices, documented in [ADRs](docs/adr/): monorepo; deterministic scoring first with AI as an explanation layer only; daily/EOD cadence instead of real-time streaming; APScheduler over Celery; broker-as-source-of-truth reconciliation model; roll-forward migrations.
