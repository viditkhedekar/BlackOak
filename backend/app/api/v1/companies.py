from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.companies import CompanyRepository
from app.db.repositories.prices import PriceRepository
from app.db.repositories.scores import ScoreRepository
from app.db.session import get_db_session
from app.domain.factors import FACTOR_CATEGORIES
from app.domain.ranges import VALID_RANGES, range_to_start
from app.domain.scoring import INVERSE_FACTORS, PROFILE_WEIGHTS
from app.schemas.companies import (
    CompanyDetail,
    CompanyList,
    CompanySummary,
    PricePoint,
    PriceSeries,
)
from app.schemas.scores import (
    CategoryBreakdown,
    CategoryScores,
    CompanyScoreDetail,
    FactorBreakdownItem,
)

router = APIRouter(prefix="/companies", tags=["companies"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=CompanyList)
async def list_companies(
    session: SessionDep,
    query: Annotated[str | None, Query(description="symbol or name substring")] = None,
    sector: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyList:
    repo = CompanyRepository(session)
    rows = await repo.search(query, sector, limit, offset)
    total = await repo.count(query, sector)
    return CompanyList(
        items=[CompanySummary.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{symbol}", response_model=CompanyDetail)
async def get_company(symbol: str, session: SessionDep) -> CompanyDetail:
    company = await CompanyRepository(session).get_by_symbol(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol.upper()}")
    return CompanyDetail.model_validate(company)


@router.get("/{symbol}/prices", response_model=PriceSeries)
async def get_company_prices(
    symbol: str,
    session: SessionDep,
    range: Annotated[str, Query(description=f"one of {', '.join(VALID_RANGES)}")] = "1Y",
) -> PriceSeries:
    if range.upper() not in VALID_RANGES:
        raise HTTPException(status_code=422, detail=f"Invalid range: {range}")

    companies = CompanyRepository(session)
    company = await companies.get_by_symbol(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol.upper()}")

    start = range_to_start(range, datetime.now(UTC).date())
    rows = await PriceRepository(session).get_series(company.id, start, None)
    return PriceSeries(
        symbol=company.symbol,
        range=range.upper(),
        points=[PricePoint.model_validate(r) for r in rows],
    )


@router.get("/{symbol}/scores", response_model=CompanyScoreDetail)
async def get_company_scores(
    symbol: str, session: SessionDep, profile: str = "balanced"
) -> CompanyScoreDetail:
    if profile not in PROFILE_WEIGHTS:
        raise HTTPException(status_code=422, detail=f"Unknown profile: {profile}")

    company = await CompanyRepository(session).get_by_symbol(symbol)
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol.upper()}")

    scores = ScoreRepository(session)
    as_of = await scores.latest_as_of()
    score = await scores.get_for_company(company.id, profile, as_of) if as_of else None
    if score is None:
        raise HTTPException(status_code=404, detail=f"No scores yet for {company.symbol}")

    def num(value: object) -> float | None:
        return float(value) if value is not None else None  # type: ignore[arg-type]

    inputs = score.inputs or {}
    breakdown = [
        CategoryBreakdown(
            category=category,
            score=num(getattr(score, category)),
            factors=[
                FactorBreakdownItem(
                    factor=name,
                    raw=(inputs.get(name) or {}).get("raw"),
                    score=(inputs.get(name) or {}).get("score"),
                    inverse=name in INVERSE_FACTORS,
                )
                for name in factor_names
            ],
        )
        for category, factor_names in FACTOR_CATEGORIES.items()
    ]
    return CompanyScoreDetail(
        symbol=company.symbol,
        profile=profile,
        as_of=score.as_of_date,
        composite=num(score.composite),
        data_completeness=float(score.data_completeness),
        engine_version=score.engine_version,
        categories=CategoryScores(
            financial_health=num(score.financial_health),
            growth=num(score.growth),
            value=num(score.value),
            quality=num(score.quality),
            profitability=num(score.profitability),
            momentum=num(score.momentum),
            volatility=num(score.volatility),
            risk=num(score.risk),
        ),
        breakdown=breakdown,
    )
