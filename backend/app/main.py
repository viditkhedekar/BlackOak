from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1 import health as health_module
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.environment)

    application = FastAPI(
        title="BlackOak API",
        version="0.1.0",
        docs_url="/docs" if settings.environment == "local" else None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix="/api/v1")
    # Unversioned health alias so infra probes don't depend on the API version.
    application.include_router(health_module.router, tags=["system"])
    return application


app = create_app()
