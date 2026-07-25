from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.schemas.health import HealthResponse

router = APIRouter()
log = structlog.get_logger()


@router.get("/health", response_model=HealthResponse)
async def health(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        log.exception("health.db_check_failed")
        db_status = "unreachable"
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        environment=settings.environment,
    )
