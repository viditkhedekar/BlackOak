"""Signal pipeline (docs/ROADMAP.md R2): raw signals → regime → fused strategy_scores.

Assembles SignalInputs for the S&P 500 from the DB, classifies the market regime, runs
the pure fusion, and persists one regime_snapshot + one strategy_scores row per company
(with weights_used + raw inputs for full reproducibility). Ranking is universe-wide.

The two-speed split in the plan (slow families nightly, fast families each cycle) is an
optimisation for R4's decision loop; here we run the full fusion so R2 can be verified
end-to-end. R4 will call ``fuse_scores`` on a fast-refreshed subset via the same code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Fundamental
from app.db.repositories.companies import CompanyRepository
from app.db.repositories.estimates import EstimatesRepository
from app.db.repositories.fundamentals import FundamentalsRepository
from app.db.repositories.macro import MacroRepository
from app.db.repositories.prices import PriceRepository
from app.db.repositories.strategy import RegimeRepository, StrategyScoreRepository
from app.domain.factors import FundamentalSnapshot
from app.domain.regime import DMA_LONG, build_features, classify_raw, resolve
from app.domain.signals import EstimateValues, SignalInputs, compute_signals
from app.domain.stats import sma
from app.domain.strategy import (
    ENGINE_VERSION,
    WEIGHTS_BY_REGIME,
    StrategyCompany,
    fuse_scores,
)
from app.services.job_tracking import track_job

log = structlog.get_logger()


@dataclass
class PipelineReport:
    ts: datetime
    regime: str
    scored: int
    breadth: float


def _f(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


def _to_snapshot(f: Fundamental) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        fiscal_year=f.fiscal_date.year,
        revenue=_f(f.revenue), gross_profit=_f(f.gross_profit), ebitda=_f(f.ebitda),
        ebit=_f(f.ebit), operating_income=_f(f.operating_income),
        net_income=_f(f.net_income), eps_diluted=_f(f.eps_diluted),
        interest_expense=_f(f.interest_expense), total_assets=_f(f.total_assets),
        current_assets=_f(f.current_assets), current_liabilities=_f(f.current_liabilities),
        total_debt=_f(f.total_debt), cash=_f(f.cash), equity=_f(f.equity),
        shares_out=_f(f.shares_out), operating_cf=_f(f.operating_cf), capex=_f(f.capex),
    )


async def run_signal_pipeline(session: AsyncSession) -> PipelineReport:
    async with track_job(session, "signal_pipeline") as ctx:
        companies_repo = CompanyRepository(session)
        prices_repo = PriceRepository(session)
        funds_repo = FundamentalsRepository(session)
        est_repo = EstimatesRepository(session)
        macro_repo = MacroRepository(session)
        scores_repo = StrategyScoreRepository(session)
        regime_repo = RegimeRepository(session)

        spy = await companies_repo.get_by_symbol("SPY")
        spy_closes = (
            [float(p.adj_close) for p in await prices_repo.get_series(spy.id, None, None)]
            if spy else []
        )

        targets = await companies_repo.active_symbols("SP500")
        # Canonical daily timestamp so re-runs upsert rather than duplicate.
        latest = await prices_repo.latest_date(spy.id) if spy else None
        if latest is None and targets:
            latest = await prices_repo.latest_date(targets[0][0])
        if latest is None:
            raise RuntimeError("no price history — run a backfill first")
        ts = datetime.combine(latest, time(20, 0), tzinfo=UTC)

        strategy_companies: list[StrategyCompany] = []
        above_200 = 0
        breadth_denom = 0

        for company_id, symbol in targets:
            company = await companies_repo.get_by_symbol(symbol)
            if company is None:
                continue
            px = await prices_repo.get_series(company_id, None, None)
            if not px:
                continue
            closes = [float(p.adj_close) for p in px]

            funds = await funds_repo.get_annual(company_id)
            est_row = await est_repo.latest(company_id)
            estimates = (
                EstimateValues(
                    forward_pe=_f(est_row.forward_pe), peg=_f(est_row.peg),
                    forward_eps=_f(est_row.forward_eps),
                )
                if est_row else None
            )

            inputs = SignalInputs(
                symbol=symbol,
                sector=company.sector or "Unknown",
                closes=closes,
                highs=[float(p.high) for p in px],
                lows=[float(p.low) for p in px],
                volumes=[float(p.volume) for p in px],
                opens=[float(p.open) for p in px],
                current_price=closes[-1],
                market_closes=spy_closes,
                annual=[_to_snapshot(f) for f in funds],
                estimates=estimates,
            )
            signals = compute_signals(inputs)
            strategy_companies.append(
                StrategyCompany(symbol=symbol, sector=inputs.sector, signals=signals)
            )

            ma200 = sma(closes, DMA_LONG)
            if ma200 is not None:
                breadth_denom += 1
                if closes[-1] > ma200:
                    above_200 += 1

        breadth = above_200 / breadth_denom if breadth_denom else None

        # --- regime classification -------------------------------------------------
        vix = [float(p.value) for p in await macro_repo.get_series("VIX")]
        t10y2y_row = await macro_repo.latest("T10Y2Y")
        t10y2y = float(t10y2y_row.value) if t10y2y_row else None
        features = build_features(vix, t10y2y, spy_closes, breadth)

        prev = await regime_repo.latest()
        raw_history = await regime_repo.recent_raw_labels(limit=4)
        # Provisional classify to append today's raw label before confirmation.
        today_raw, _, _ = classify_raw(features)
        regime = resolve(features, [*raw_history, today_raw], prev.label if prev else None)
        weights = WEIGHTS_BY_REGIME[regime.label]

        await regime_repo.insert(
            {
                "ts": ts,
                "label": regime.label,
                "raw_label": regime.raw_label,
                "bearish_count": regime.bearish_count,
                "features": {
                    "vix_level": features.vix_level,
                    "vix_slope_10d": features.vix_slope_10d,
                    "t10y2y": features.t10y2y,
                    "spy_vs_200dma": features.spy_vs_200dma,
                    "breadth": features.breadth,
                    "flags": regime.flags,
                },
                "weights": weights,
            }
        )

        # --- fusion + persistence --------------------------------------------------
        results = fuse_scores(strategy_companies, regime.label)
        id_by_symbol = {sym: cid for cid, sym in targets}
        rows: list[dict[str, object]] = []
        for s in results:
            rows.append(
                {
                    "company_id": id_by_symbol[s.symbol],
                    "ts": ts,
                    "regime": regime.label,
                    "valuation": s.families["valuation"],
                    "fundamentals": s.families["fundamentals"],
                    "momentum": s.families["momentum"],
                    "technical": s.families["technical"],
                    "risk": s.families["risk"],
                    "composite": s.composite,
                    "rank": s.rank,
                    "data_completeness": s.data_completeness,
                    "engine_version": ENGINE_VERSION,
                    "weights_used": weights,
                    "inputs": {
                        m: {"raw": d.raw, "score": d.score}
                        for m, d in s.metric_details.items()
                    },
                }
            )
        written = await scores_repo.upsert_scores(rows)

        ctx.records_processed = written
        ctx.meta = {
            "ts": ts.isoformat(),
            "regime": regime.label,
            "raw_regime": regime.raw_label,
            "bearish_count": regime.bearish_count,
            "scored": written,
            "breadth": breadth,
        }
        return PipelineReport(
            ts=ts, regime=regime.label, scored=written, breadth=breadth or 0.0
        )
