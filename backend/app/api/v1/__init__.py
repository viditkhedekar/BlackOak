from fastapi import APIRouter

from app.api.v1 import (
    backtests,
    companies,
    health,
    screener,
    strategy,
    system,
    trading,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(companies.router)
api_router.include_router(screener.router)
api_router.include_router(strategy.router)
api_router.include_router(trading.router)
api_router.include_router(backtests.router)
api_router.include_router(system.router)
