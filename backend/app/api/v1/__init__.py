from fastapi import APIRouter

from app.api.v1 import companies, health, screener

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(companies.router)
api_router.include_router(screener.router)
