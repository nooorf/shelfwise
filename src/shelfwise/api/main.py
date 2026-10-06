"""FastAPI application. Routes stay thin; logic lives in the shelfwise package."""

from fastapi import APIRouter, FastAPI

from shelfwise import __version__
from shelfwise.config import Settings, get_settings
from shelfwise.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(title="Shelfwise", version=__version__)
    v1 = APIRouter(prefix="/api/v1")

    @v1.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "profile": settings.profile}

    app.include_router(v1)
    return app


app = create_app()
