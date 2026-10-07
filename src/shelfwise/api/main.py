"""FastAPI application. Routes stay thin; logic lives in the shelfwise package."""

import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import Connection, Engine

from shelfwise import __version__
from shelfwise.config import Settings, get_settings
from shelfwise.logging import configure_logging
from shelfwise.pipeline import SearchRequest, SearchResponse, SearchService, build_service


class _Resources:
    """The database engine and search service, created on first use so the app starts (and
    /health answers) without a database or a model in memory."""

    def __init__(
        self, settings: Settings, engine: Engine | None, service: SearchService | None
    ) -> None:
        self.settings = settings
        self._engine = engine
        self._service = service
        self._lock = threading.Lock()

    def connection(self) -> Iterator[Connection]:
        with self._lock:
            if self._engine is None:
                from shelfwise.catalog.db import make_engine

                self._engine = make_engine(self.settings.sqlalchemy_url)
            engine = self._engine
        with engine.connect() as conn:
            yield conn

    def service(self, conn: Connection) -> SearchService:
        with self._lock:
            if self._service is None:
                dense = self.settings.embedding_model if self.settings.search_dense else None
                self._service = build_service(dense, conn)
            return self._service


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    service: SearchService | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    resources = _Resources(settings, engine, service)

    def search_service(
        conn: Annotated[Connection, Depends(resources.connection)],
    ) -> SearchService:
        return resources.service(conn)

    app = FastAPI(title="Shelfwise", version=__version__)
    app.state.resources = resources  # tests override resources.connection
    v1 = APIRouter(prefix="/api/v1")

    @v1.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "profile": settings.profile}

    @v1.post("/search")
    def search(
        request: SearchRequest,
        conn: Annotated[Connection, Depends(resources.connection)],
        service: Annotated[SearchService, Depends(search_service)],
    ) -> SearchResponse:
        """Stateless search: parsed filters, ranked books with live availability, and, when
        nothing matches every hard filter, which one to drop and how many books that gives."""
        return service.search(conn, request)

    app.include_router(v1)
    return app


app = create_app()
