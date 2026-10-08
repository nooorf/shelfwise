# Shelfwise web app

React + TypeScript + Vite + Tailwind (design doc §22, §24). The results shelf is the main surface; the conversation column steers it; active constraints are chips. Turns go over the session WebSocket: cards arrive as soon as retrieval is done, the LLM's validated notes follow.

```bash
make api          # terminal 1: the API on :8000 (needs `make up`)
make web          # terminal 2: http://localhost:5173 (proxies /api to :8000)
make web-test     # unit tests (Vitest)
make web-build    # type-check and build into dist/
make web-types    # after an API change: regenerate src/api/schema.d.ts from its OpenAPI schema
```

Layout of `src/`: `api/` (generated types, REST calls), `session/` (WebSocket client with reconnect, the Zustand store that turns server events into what's on screen, the hook that wires them), `components/` (shelf, book card, availability pill, chips, conversation, the avatar slot where the Phase 6b avatar will go).
