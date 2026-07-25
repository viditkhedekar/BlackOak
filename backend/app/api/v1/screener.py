from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, ResearchScore
from app.db.repositories.scores import SORTABLE, ScoreRepository
from app.db.session import get_db_session
from app.domain.scoring import PROFILE_WEIGHTS
from app.schemas.scores import (
    CategoryScores,
    ScreenerResponse,
    ScreenerRow,
)

router = APIRouter(prefix="/screener", tags=["research"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _categories(score: ResearchScore) -> CategoryScores:
    return CategoryScores(
        financial_health=_num(score.financial_health),
        growth=_num(score.growth),
        value=_num(score.value),
        quality=_num(score.quality),
        profitability=_num(score.profitability),
        momentum=_num(score.momentum),
        volatility=_num(score.volatility),
        risk=_num(score.risk),
    )


def _num(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


@router.get("", response_model=ScreenerResponse)
async def screen(
    session: SessionDep,
    profile: str = "balanced",
    min_score: Annotated[float | None, Query(ge=0, le=100, alias="minScore")] = None,
    sector: str | None = None,
    sort_by: Annotated[str, Query(alias="sortBy")] = "composite",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ScreenerResponse:
    if profile not in PROFILE_WEIGHTS:
        raise HTTPException(422, f"Unknown profile: {profile}")
    if sort_by not in SORTABLE:
        raise HTTPException(422, f"Cannot sort by: {sort_by}")

    repo = ScoreRepository(session)
    as_of = await repo.latest_as_of()
    if as_of is None:
        return ScreenerResponse(
            items=[], total=0, limit=limit, offset=offset, profile=profile, as_of=None
        )

    rows, total = await repo.screener(
        profile=profile,
        as_of=as_of,
        min_score=min_score,
        sector=sector,
        sort_by=sort_by,
        descending=(order == "desc"),
        limit=limit,
        offset=offset,
    )
    items = []
    for row in rows:
        company: Company = row[0]
        score: ResearchScore = row[1]
        items.append(
            ScreenerRow(
                symbol=company.symbol,
                name=company.name,
                sector=company.sector,
                composite=_num(score.composite),
                data_completeness=float(score.data_completeness),
                categories=_categories(score),
            )
        )
    return ScreenerResponse(
        items=items, total=total, limit=limit, offset=offset, profile=profile, as_of=as_of
    )
