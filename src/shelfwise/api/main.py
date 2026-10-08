"""FastAPI application. Routes stay thin; logic lives in the shelfwise package."""

import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from sqlalchemy import Connection, Engine

from shelfwise import __version__
from shelfwise.config import Settings, get_settings
from shelfwise.conversation.service import (
    ConversationService,
    SessionNotFound,
    TurnRequest,
    TurnResponse,
)
from shelfwise.logging import configure_logging
from shelfwise.pipeline import SearchRequest, SearchResponse, SearchService, build_service

NARRATE_TIMEOUT_S = 60.0  # a whole reply; past it the reply falls back to templates


class _Resources:
    """The database engine and search service, created on first use so the app starts (and
    /health answers) without a database or a model in memory."""

    def __init__(
        self,
        settings: Settings,
        engine: Engine | None,
        service: SearchService | None,
        conversation: ConversationService | None = None,
    ) -> None:
        self.settings = settings
        self._engine = engine
        self._service = service
        self._conversation = conversation
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
                llm = self.settings.llm_model if self.settings.query_parser == "cascade" else None
                self._service = build_service(dense, conn, self.settings.rerank_model, llm)
            return self._service

    def conversation(self, conn: Connection) -> ConversationService:
        search = self.service(conn)
        with self._lock:
            if self._conversation is None:
                from shelfwise.conversation.store import RedisSessionStore
                from shelfwise.generation.narrate import Narrator
                from shelfwise.llm.client import OllamaClient

                store = RedisSessionStore(self.settings.redis_url, self.settings.session_ttl_s)
                llm_on = self.settings.query_parser == "cascade" and self.settings.narrate
                llm = OllamaClient(model=self.settings.llm_model, timeout=NARRATE_TIMEOUT_S)
                narrator = Narrator(llm if llm_on else None)  # None: template replies
                self._conversation = ConversationService(search, store, narrator=narrator)
            return self._conversation


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    service: SearchService | None = None,
    conversation: ConversationService | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    resources = _Resources(settings, engine, service, conversation)

    def search_service(
        conn: Annotated[Connection, Depends(resources.connection)],
    ) -> SearchService:
        return resources.service(conn)

    def conversation_service(
        conn: Annotated[Connection, Depends(resources.connection)],
    ) -> ConversationService:
        return resources.conversation(conn)

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

    @v1.post("/sessions", status_code=201)
    def start_session(
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> dict[str, str]:
        """A new anonymous conversation; its state expires after `session_ttl_s` idle."""
        return {"session_id": conversation.start()}

    @v1.post("/sessions/{session_id}/turns")
    def take_turn(
        session_id: str,
        request: TurnRequest,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """One message: merged into the session's state, routed by intent, answered with
        books (cards from the catalog, never from the LLM) and short template notes."""
        try:
            return conversation.turn(conn, session_id, request)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.post("/sessions/{session_id}/undo")
    def undo_topic_reset(
        session_id: str,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """Back to the search before the last "new topic"."""
        try:
            return conversation.undo(conn, session_id)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.delete("/sessions/{session_id}", status_code=204)
    def end_session(
        session_id: str,
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> None:
        """ "New visitor" / forget me: the state is deleted now, not at expiry."""
        conversation.end(session_id)

    app.include_router(v1)
    return app


app = create_app()
