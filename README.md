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

## Design decisions & trade-offs

Deliberate choices, documented in [ADRs](docs/adr/): monorepo; deterministic scoring first with AI as an explanation layer only; daily/EOD cadence instead of real-time streaming; APScheduler over Celery; broker-as-source-of-truth reconciliation model; roll-forward migrations.
