from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, StrategyScore
from app.db.repositories.strategy import RegimeRepository, StrategyScoreRepository
from app.db.repositories.trading import TradeDecisionRepository
from app.db.session import get_db_session
from app.schemas.dashboard import (
    DecisionRow,
    RankingRow,
    RankingsResponse,
    RegimeResponse,
    StrategyFamilies,
)

router = APIRouter(prefix="/strategy", tags=["strategy"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _num(v: object) -> float | None:
    return float(v) if v is not None else None  # type: ignore[arg-type]


@router.get("/rankings", response_model=RankingsResponse)
async def rankings(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> RankingsResponse:
    repo = StrategyScoreRepository(session)
    ts = await repo.latest_ts()
    if ts is None:
        return RankingsResponse(ts=None, regime=None, items=[])
    rows = await repo.top_ranked(ts, limit=limit)
    regime_row = await RegimeRepository(session).latest()
    items: list[RankingRow] = []
    for row in rows:
        company: Company = row[0]
        s: StrategyScore = row[1]
        items.append(
            RankingRow(
                rank=s.rank, symbol=company.symbol, name=company.name, sector=company.sector,
                composite=_num(s.composite), data_completeness=float(s.data_completeness),
                families=StrategyFamilies(
                    valuation=_num(s.valuation), fundamentals=_num(s.fundamentals),
                    momentum=_num(s.momentum), technical=_num(s.technical), risk=_num(s.risk),
                ),
            )
        )
    return RankingsResponse(
        ts=ts, regime=regime_row.label if regime_row else None, items=items
    )


@router.get("/regime", response_model=RegimeResponse)
async def regime(session: SessionDep) -> RegimeResponse:
    row = await RegimeRepository(session).latest()
    if row is None:
        return RegimeResponse(
            ts=None, label=None, raw_label=None, bearish_count=None, features=None, weights=None
        )
    return RegimeResponse(
        ts=row.ts, label=row.label, raw_label=row.raw_label,
        bearish_count=row.bearish_count, features=row.features, weights=row.weights,
    )


@router.get("/decisions", response_model=list[DecisionRow], tags=["decisions"])
async def decisions(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action: str | None = None,
    symbol: str | None = None,
) -> list[DecisionRow]:
    rows = await TradeDecisionRepository(session).recent(limit, action, symbol)
    return [
        DecisionRow(
            ts=d.ts, cycle_id=str(d.cycle_id), symbol=d.symbol, action=d.action,
            reason=d.reason, regime=d.regime, evidence=d.evidence,
        )
        for d in rows
    ]
