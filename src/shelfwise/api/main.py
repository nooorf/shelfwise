"""FastAPI application. Routes stay thin; logic lives in the shelfwise package."""

import asyncio
import base64
import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import Connection, Engine

from shelfwise import __version__
from shelfwise.config import Settings, get_settings
from shelfwise.conversation.service import (
    BookFeedback,
    ChipRemoval,
    ChipStrength,
    ConversationService,
    ExploreRequest,
    FiltersRequest,
    SessionNotFound,
    SurpriseRequest,
    TurnRequest,
    TurnResponse,
)
from shelfwise.evaluation.bench import Bench, load_bench
from shelfwise.generation.narrate import Reply
from shelfwise.logging import configure_logging
from shelfwise.pipeline import (
    BookDetail,
    GenreCount,
    SearchRequest,
    SearchResponse,
    SearchService,
    build_service,
)
from shelfwise.voice.listen import Endpointer, load_listening
from shelfwise.voice.tts import load_speech


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


NARRATE_TIMEOUT_S = 60.0  # a whole reply; past it the reply falls back to templates
# What the session socket accepts besides "cancel" (see `stream`).
SOCKET_MESSAGES = frozenset(
    {
        "text",
        "undo",
        "remove_chip",
        "chip_strength",
        "more_like",
        "less_like",
        "surprise",
        "explore",
        "filters",
    }
)


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
                speech = load_speech(Path(self.settings.tts_model_dir), self.settings.tts_voice)
                listening = load_listening(Path(self.settings.vad_model_dir), self.settings.whisper)
                self._conversation = ConversationService(
                    search, store, narrator=narrator, speech=speech, listening=listening
                )
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

    @v1.get("/books/{work_id}")
    def book(
        work_id: int,
        conn: Annotated[Connection, Depends(resources.connection)],
        service: Annotated[SearchService, Depends(search_service)],
    ) -> BookDetail:
        """One book for the drawer: the card's facts with live availability, the description,
        its tags, its editions and where every copy is."""
        detail = service.book_detail(conn, work_id, service.today())
        if detail is None:
            raise HTTPException(404, "no such book")
        return detail

    @v1.post("/speech", response_class=Response)
    def speech(
        request: SpeechRequest,
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> Response:
        """Any text as speech (a 16-bit WAV, 24 kHz, Kokoro), for demos and checks. 503 when
        the TTS model isn't downloaded (`make download-tts`)."""
        if conversation.speech is None:
            raise HTTPException(503, "text-to-speech is off: run `make download-tts`")
        return Response(conversation.audio(request.text), media_type="audio/wav")

    @v1.get("/bench")
    def bench() -> Bench:
        """The benchmark dashboard's data: the newest dev-split retrieval report (every system's
        scores with CIs, per category, latency) and the newest parser report."""
        return load_bench()

    @v1.get("/genres")
    def genres(
        conn: Annotated[Connection, Depends(resources.connection)],
        service: Annotated[SearchService, Depends(search_service)],
    ) -> list[GenreCount]:
        """Every genre in the catalog with its number of books, largest first (Explore)."""
        return service.genres(conn)

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

    @v1.post("/sessions/{session_id}/chips/remove")
    def remove_chip(
        session_id: str,
        removal: ChipRemoval,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """The reader tapped a chip's remove button: its constraints go, and the search runs
        again on what is left."""
        try:
            return conversation.remove_chip(conn, session_id, removal)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.post("/sessions/{session_id}/chips/strength")
    def set_chip_strength(
        session_id: str,
        change: ChipStrength,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """The reader switched a chip between must (a filter) and preferred (a ranking nudge);
        the search runs again. Only chips marked `switchable` change."""
        try:
            return conversation.set_chip_strength(conn, session_id, change)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.post("/sessions/{session_id}/explore")
    def explore(
        session_id: str,
        request: ExploreRequest,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """Explore a genre: a new search (undo-able) for its books, those on the shelf now and
        most borrowed first. No parsing."""
        try:
            return conversation.explore(conn, session_id, request)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.post("/sessions/{session_id}/filters")
    def filters(
        session_id: str,
        request: FiltersRequest,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """The filters form: page limit, years and "available now" as musts on the current
        search (or the start of one). No parsing."""
        try:
            return conversation.filters(conn, session_id, request)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.post("/sessions/{session_id}/surprise")
    def surprise(
        session_id: str,
        request: SurpriseRequest,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """The "Surprise me" button: three unseen books on the shelf now, within the hard
        chips. No parsing."""
        try:
            return conversation.surprise(conn, session_id, request)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.post("/sessions/{session_id}/feedback")
    def book_feedback(
        session_id: str,
        feedback: BookFeedback,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> TurnResponse:
        """ "More like this" (the book becomes the seed) or "less like this" (it is hidden and
        the books nearest it pushed down) on a shown book; the search runs again."""
        try:
            return conversation.book_feedback(conn, session_id, feedback)
        except SessionNotFound:
            raise HTTPException(404, "session not found or expired: start a new one") from None

    @v1.delete("/sessions/{session_id}", status_code=204)
    def end_session(
        session_id: str,
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> None:
        """ "New visitor" / forget me: the state is deleted now, not at expiry."""
        conversation.end(session_id)

    @v1.websocket("/sessions/{session_id}/stream")
    async def stream(
        websocket: WebSocket,
        session_id: str,
        conn: Annotated[Connection, Depends(resources.connection)],
        conversation: Annotated[ConversationService, Depends(conversation_service)],
    ) -> None:
        """One socket per session (design doc §20.5, text events). Client -> server:
        {"type": "text", "text": ..., "limit"?, "narrate"?}, {"type": "undo"},
        {"type": "remove_chip", "field": ..., "label": ...},
        {"type": "chip_strength", "field": ..., "label": ..., "strength": "hard" | "soft"},
        {"type": "more_like" | "less_like", "work_id": ...}, {"type": "surprise"},
        {"type": "explore", "genre": ...}, {"type": "filters", "pages_max"?, "year_from"?,
        "year_to"?, "available_now"?}, {"type": "speak", "on": bool}, {"type": "cancel"},
        {"type": "listen", "on": bool} and, while listening, binary frames of 16 kHz 16-bit
        mono PCM. Listening answers {"type": "listening", "on", "reason"?}; the server finds
        the utterance's end itself ("speech_start" when it hears speech: barge-in), then sends
        {"type": "transcript", "text", "fixed": [{"heard", "catalog"}]} (names respelled from
        the catalog) and runs it as a typed "text" message; "listen" off
        before the end transcribes what was heard so far.
        Server -> client, per turn: "turn" (cards, chips, notes: everything but the narration,
        as soon as retrieval is done), then "reply" when the narration is ready, then, with
        speech on, one "audio" per sentence ({"seq", "text", "wav": base64 16-bit WAV}), then
        "done". "speak" is answered with {"type": "speak", "on"}: false when no TTS model is
        loaded. A new message or "cancel" while the reply or its audio is being made drops it
        ("cancelled"): the server half of barge-in."""
        await websocket.accept()
        if conversation.store.get(session_id) is None:
            await websocket.send_json({"type": "error", "message": "session not found or expired"})
            await websocket.close(code=4404)
            return
        receive: asyncio.Task[Any] = asyncio.create_task(websocket.receive())
        narrating: asyncio.Task[Any] | None = None
        narrating_turn = 0
        speak = False
        listener: Endpointer | None = None  # set while the microphone is open

        async def stop_listening(reason: str) -> None:
            nonlocal listener
            listener = None
            await websocket.send_json({"type": "listening", "on": False, "reason": reason})

        async def hear(raw: bytes) -> dict[str, Any] | None:
            """Microphone audio in; a text message out once the utterance has ended."""
            if listener is None:
                return None  # frames still in flight after listening stopped
            heard = listener
            for event in heard.feed(raw):
                if event == "start":
                    await websocket.send_json({"type": "speech_start"})
                    await drop_narration()  # barge-in by voice
                elif event == "timeout":
                    await stop_listening("no speech")
                else:
                    return await transcribe(heard)
            return None

        async def transcribe(heard: Endpointer) -> dict[str, Any] | None:
            await stop_listening("heard")
            text, fixes = await asyncio.to_thread(conversation.transcribe, conn, heard.audio())
            await websocket.send_json(
                {"type": "transcript", "text": text,
                 "fixed": [{"heard": f.heard, "catalog": f.catalog} for f in fixes]}
            )  # fmt: skip
            return {"type": "text", "text": text} if text else None

        async def finish(response: TurnResponse, job: Callable[[], Reply] | None) -> None:
            """The rest of a turn, in the background: narration, then speech, then "done"."""
            turn = response.turn
            reply = None
            if job is not None:
                reply = await asyncio.to_thread(job)
                await websocket.send_json(
                    {"type": "reply", "turn": turn, "reply": reply.model_dump(mode="json")}
                )
            if speak and conversation.speech is not None:
                for seq, sentence in enumerate(conversation.spoken(response, reply)):
                    clip = await asyncio.to_thread(conversation.audio, sentence)
                    await websocket.send_json(
                        {"type": "audio", "turn": turn, "seq": seq, "text": sentence,
                         "wav": base64.b64encode(clip).decode("ascii")}
                    )  # fmt: skip
            await websocket.send_json({"type": "done", "turn": turn})

        async def drop_narration() -> None:
            nonlocal narrating
            if narrating is not None:
                narrating.cancel()  # its thread finishes on its own; the result is discarded
                narrating = None
                await websocket.send_json({"type": "cancelled", "turn": narrating_turn})

        try:
            while True:
                waiting = {receive} | ({narrating} if narrating else set())
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if narrating is not None and narrating in done:
                    narrating.result()  # raises what the background part raised
                    narrating = None
                if receive not in done:
                    continue
                raw = receive.result()
                if raw["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(raw.get("code", 1000))
                receive = asyncio.create_task(websocket.receive())
                if raw.get("bytes") is not None:
                    heard = await hear(raw["bytes"])
                    if heard is None:
                        continue
                    message: Any = heard  # the transcript, handled as if typed
                else:
                    try:
                        message = json.loads(raw.get("text") or "")
                    except json.JSONDecodeError:
                        await websocket.send_json({"type": "error", "message": "not JSON"})
                        continue
                kind = message.get("type") if isinstance(message, dict) else None
                if kind == "listen":
                    if not message.get("on"):
                        if listener is not None and listener.heard:  # "done talking" tapped
                            heard = await transcribe(listener)
                            if heard is None:
                                continue
                            message, kind = heard, "text"
                        else:
                            await stop_listening("stopped")
                            continue
                    elif not conversation.can_listen:
                        await websocket.send_json(
                            {"type": "listening", "on": False, "reason": "unavailable"}
                        )
                        continue
                    else:
                        listener = conversation.endpointer()
                        await websocket.send_json({"type": "listening", "on": True})
                        continue
                if kind == "cancel":
                    await drop_narration()
                    continue
                if kind == "speak":
                    speak = bool(message.get("on")) and conversation.speech is not None
                    await websocket.send_json({"type": "speak", "on": speak})
                    continue
                if kind not in SOCKET_MESSAGES:
                    await websocket.send_json({"type": "error", "message": f"unknown {kind!r}"})
                    continue
                await drop_narration()  # a new message barges in
                try:
                    if kind == "text":
                        request = TurnRequest.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                            | {"message": message.get("text", "")}
                        )
                        wants_reply = request.narrate
                        request = request.model_copy(update={"narrate": False})
                        response = await asyncio.to_thread(
                            conversation.turn, conn, session_id, request
                        )
                        said = request.message
                    elif kind == "remove_chip":
                        removal = ChipRemoval.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                        )
                        wants_reply = removal.narrate
                        response = await asyncio.to_thread(
                            conversation.remove_chip, conn, session_id,
                            removal.model_copy(update={"narrate": False}),
                        )  # fmt: skip
                        said = f'without "{removal.label}"'
                    elif kind == "chip_strength":
                        change = ChipStrength.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                        )
                        wants_reply = change.narrate
                        response = await asyncio.to_thread(
                            conversation.set_chip_strength, conn, session_id,
                            change.model_copy(update={"narrate": False}),
                        )  # fmt: skip
                        words = "a must" if change.strength == "hard" else "a preference"
                        said = f'"{change.label}" as {words}'
                    elif kind == "explore":
                        genre = ExploreRequest.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                        )
                        wants_reply, said = genre.narrate, genre.said()
                        response = await asyncio.to_thread(
                            conversation.explore, conn, session_id,
                            genre.model_copy(update={"narrate": False}),
                        )  # fmt: skip
                    elif kind == "filters":
                        form = FiltersRequest.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                        )
                        wants_reply, said = form.narrate, form.said()
                        response = await asyncio.to_thread(
                            conversation.filters, conn, session_id,
                            form.model_copy(update={"narrate": False}),
                        )  # fmt: skip
                    elif kind == "surprise":
                        press = SurpriseRequest.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                        )
                        wants_reply = press.narrate
                        response = await asyncio.to_thread(
                            conversation.surprise, conn, session_id,
                            press.model_copy(update={"narrate": False}),
                        )  # fmt: skip
                        said = "surprise me"
                    elif kind in ("more_like", "less_like"):
                        feedback = BookFeedback.model_validate(
                            {k: v for k, v in message.items() if k != "type"}
                            | {"more": kind == "more_like"}
                        )
                        wants_reply = feedback.narrate
                        response = await asyncio.to_thread(
                            conversation.book_feedback, conn, session_id,
                            feedback.model_copy(update={"narrate": False}),
                        )  # fmt: skip
                        said = f"{'more' if feedback.more else 'less'} like this"
                    else:
                        wants_reply = bool(message.get("narrate", True))
                        response = await asyncio.to_thread(
                            conversation.undo, conn, session_id, 5, False
                        )
                        said = response.semantic_query
                except SessionNotFound:
                    await websocket.send_json({"type": "error", "message": "session expired"})
                    await websocket.close(code=4404)
                    return
                except ValidationError as exc:
                    await websocket.send_json({"type": "error", "message": str(exc)})
                    continue
                await websocket.send_json({"type": "turn", **response.model_dump(mode="json")})
                job = conversation.narration_job(conn, response, said) if wants_reply else None
                if job is None and not (speak and conversation.speech is not None):
                    await websocket.send_json({"type": "done", "turn": response.turn})
                    continue
                narrating_turn = response.turn
                narrating = asyncio.create_task(finish(response, job))
        except WebSocketDisconnect:
            pass
        finally:
            receive.cancel()
            if narrating is not None:
                narrating.cancel()

    app.include_router(v1)
    return app


app = create_app()
