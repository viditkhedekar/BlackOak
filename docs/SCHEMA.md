# BlackOak Data & Computation Specs

The database schema, the deterministic scoring contract, and the performance-metric formulas. These are specifications: implementations in `backend/app/domain/` must match this document, and changes here require an `engine_version` bump plus golden-file updates.

## 4. Database Schema (PostgreSQL, Alembic-managed)

Conventions: UUID PKs, `created_at/updated_at timestamptz` on all tables, `NUMERIC(18,6)` for money/qty, user-scoped tables always indexed on `user_id`. Single-user-first but every user-owned table carries `user_id` so multi-user is a config change, not a migration nightmare.

### Reference / market data (global, no user_id)
| Table | Purpose & key columns | Indexes |
|---|---|---|
| `companies` | Investable universe. `symbol` (unique), name, exchange, `sector`, `industry`, market_cap, `is_active`, `universe` (e.g. SP500), delisted_at | unique(symbol); (sector); (is_active, universe) |
| `prices_daily` | EOD OHLCV + adjusted close. FK company_id, `date`, o/h/l/c, `adj_close`, volume, `source` | **PK (company_id, date)**; BRIN(date). Partitioning deferred until >10M rows (ADR). |
| `fundamentals` | Statement snapshots. company_id, `period` (Q/FY), `fiscal_date`, `reported_at`, revenue, net_income, eps_diluted, total_assets, total_debt, equity, operating_cf, capex, shares_out, gross_profit, ebitda, `source` | unique(company_id, period, fiscal_date); (company_id, fiscal_date desc) |
| `news_articles` | Headlines for AI/news analyst. company_id (nullable = macro), headline, url, source, published_at, `content_hash` (dedupe), sentiment (nullable, filled later) | unique(content_hash); (company_id, published_at desc) |
| `benchmarks` + `benchmark_prices` | SPY (+ sector ETFs later) for alpha/beta/relative charts. Same shape as prices_daily | PK (benchmark_id, date) |
| `research_scores` | Output of deterministic engine. company_id, `as_of_date`, 8 category scores (0–100) + `composite`, `inputs jsonb` (raw factor values → full auditability of every score), engine_version | unique(company_id, as_of_date); (as_of_date, composite desc) for screener |

### User & portfolio (user-scoped)
| Table | Purpose & key columns | Indexes |
|---|---|---|
| `users` | Mirror of Clerk identity: `clerk_user_id` (unique), email, display_name | unique(clerk_user_id) |
| `user_settings` | Risk profile (conservative/balanced/aggressive), max_position_pct, max_sector_pct, min_position_pct, target_cash_pct, universe choice, auto_rebalance bool, notification prefs | unique(user_id) |
| `portfolios` | One per user in v1 (schema allows many later). name, alpaca_account_id, base_currency | (user_id) |
| `positions` | **Local mirror of Alpaca positions** (broker = source of truth, reconciled nightly). portfolio_id, company_id, qty, avg_entry_price, `last_synced_at` | unique(portfolio_id, company_id) |
| `orders` | **Intent ledger** (DB = source of truth for intent). portfolio_id, company_id, side, type, qty/notional, status enum (`draft→submitted→accepted→partially_filled→filled│canceled│rejected│expired`), `client_order_id` (our UUID, sent to Alpaca → idempotency), alpaca_order_id, reject_reason, rebalance_event_id (nullable FK) | unique(client_order_id); (portfolio_id, status); (alpaca_order_id) |
| `executions` | Fills (trade history). order_id, fill_qty, fill_price, filled_at, alpaca_execution_id | (order_id); unique(alpaca_execution_id) |
| `portfolio_snapshots` | Daily EOD state → all performance math. portfolio_id, `date`, equity_value, cash, `net_flows` (deposits/withdrawals for TWR), positions jsonb (weights that day) | unique(portfolio_id, date) |
| `rebalance_events` | Every rebalance: trigger (drift/calendar/manual), status (proposed→approved→executing→completed/failed), `plan jsonb` (target weights + diffs), summary text (AI-written later) | (portfolio_id, created_at desc) |
| `watchlists` + `watchlist_items` | User lists feeding screener/AI attention | unique(watchlist_id, company_id) |
| `ai_recommendations` | Per-company AI output: company_id, as_of_date, `stance` (bullish/neutral/bearish), confidence, thesis_md, risks_md, `agent_outputs jsonb` (each agent's structured verdict), model_id, prompt_version, token_cost | (company_id, as_of_date desc) |
| `audit_log` | Append-only: actor (user/system/job), action, entity, before/after jsonb — every order, settings change, rebalance approval | (entity_type, entity_id); BRIN(created_at) |
| `job_runs` | Pipeline observability: job_name, started/finished, status, records_processed, error text, meta jsonb | (job_name, started_at desc) |

Why each exists, in one line: prices/fundamentals/news are the raw inputs; research_scores is the deterministic brain's output (with `inputs jsonb` making every number reproducible); orders/executions/positions implement the intent-vs-broker-truth split that keeps Alpaca and the DB consistent; snapshots make performance math trivial and immutable; rebalance_events + audit_log give the "explain every decision" property at the data layer; job_runs turns silent pipeline failures into visible ones.

---

## 7. Deterministic Scoring Spec (the contract for Phase 2)

Method: per metric → winsorize at 1st/99th pct → z-score **within sector** → map to percentile 0–100 → category = weighted mean of its metrics → composite = risk-profile-weighted mean of categories. Every raw input stored in `research_scores.inputs`.

| Category | Metrics (equal-weight within category unless noted) |
|---|---|
| Financial Health | current ratio; debt/equity (inv); interest coverage; Altman Z |
| Growth | revenue CAGR 3y; EPS CAGR 3y; FCF growth 3y; revenue acceleration (yoy Δ) |
| Value | earnings yield; FCF yield; EV/EBITDA (inv); P/B (inv) |
| Quality | ROIC; gross-margin 5y stability (inv std); accruals ratio (inv); asset turnover |
| Profitability | ROE; ROA; net margin; FCF margin |
| Momentum | 12−1 month return (skip last month); 6m return; % above 200-DMA; 52w-high proximity |
| Volatility | 252d annualized σ (inv); 90d σ (inv) |
| Risk | 1y max drawdown (inv); β vs SPY (distance from 1, inv); downside deviation (inv); net debt/EBITDA (inv) |

Composite weights by profile — Conservative: Health/Quality/Risk-heavy (~55% combined); Balanced: even; Aggressive: Growth/Momentum-heavy (~45% combined). Exact weight tables live in `domain/scoring.py` constants + docs/SCHEMA.md. Missing metric → excluded and category renormalized; >50% of a category missing → category null → composite penalized (data-completeness gate feeds Phase 4 universe filter).

---

## 10. Performance Metrics (Phase 6) — formulas

Daily portfolio returns from snapshots, flow-adjusted (TWR): `r_t = (V_t − V_{t−1} − flows_t)/V_{t−1}`. rf = 3M T-bill constant, configurable.

- **CAGR** `(Π(1+r_t))^(252/n) − 1` · **Annual return** calendar-year compounded r_t · **Volatility** `σ(r_t)·√252`
- **Sharpe** `(mean(r−rf_d)/σ(r))·√252` · **Sortino** same but downside deviation (returns < rf_d) in denominator
- **Max drawdown** `min_t(V_t/max_{s≤t}V_s − 1)` on the equity curve
- **Beta** `cov(r_p,r_b)/var(r_b)` vs SPY · **Alpha** (Jensen, annualized) `R_p − [rf + β(R_b − rf)]`
- **Sector allocation** Σ weights by GICS sector · **Concentration** HHI `Σw_i²` + effective N `1/HHI`
- **Win rate** winning closed round-trips / total (FIFO lot matching over executions) · **Profit factor** gross profit / gross loss on closed lots
