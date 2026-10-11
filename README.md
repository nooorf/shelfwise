# Shelfwise

A library assistant you can talk to. Ask for *"a dark psychological thriller, nothing supernatural, under 300 pages, on the shelf today"*, by typing or out loud, and it answers with books the library actually has, says where they are, and explains each pick, with a talking avatar on the live page. Hybrid retrieval, an LLM query parser, and a local LLM that can only cite books retrieval found. Everything runs locally on an 8 GB M2 Mac; no paid APIs.

Book metadata is real (5,358 works from Open Library and the UCSD Goodreads Book Graph); shelves, copies and 12 months of loans are simulated.

## Results

All on the **dev split** of hand-checked benchmark queries, on an M2 Mac with 8 GB (the locked test split runs once, after the fine-tuning, see [below](#still-to-come-the-gpu-day)).

| What | Result | Compared with |
| --- | --- | --- |
| Ranking quality, nDCG@10 (113 queries) | **0.682** (95% CI 0.64–0.72) | dense embeddings 0.643, hybrid BM25 + dense 0.581, BM25 0.408 |
| Requests with a "not" (37 negation pairs): books in the top 10 that break the request | **31%** | 62% for hybrid search, 67% for dense: typing "without romance" *adds* romance |
| Books shown to readers that the library doesn't have (150 adversarial cases) | **0%** | 21% for naive RAG (top 5 books, no checks); an LLM on its own memory names unowned books 77% of the time |
| Constraints read right from a request, F1 (184 queries) | **95.0%** | precision 98.0%, recall 92.2% (Qwen3-4B parser with a rules fallback) |
| Follow-ups understood in a conversation (set C, 40 sessions, 112 turns) | turn kind **95.4%**, state F1 **80.4%** | the rules alone: 70.6% and 34.9% |
| Search time, p95 | **250 ms** | dense alone 32 ms |
| Spoken answer: time to first audio, median (20 spoken questions, LLM on) | **10.3 s** on the 8 GB Mac | ~2.7 s in a short run with the rules parser instead of the LLM, where nothing swaps; see [Known gaps](#known-gaps) |
| Talking avatar | adds **+0.36 s** to it (95% CI −1.75 to +2.42 s: no measurable cost) | lips **4 ms** behind the sound (median; 95% within 63 ms), **59 fps** while speaking, first frame **0.73 s** after opening the page |

**About the comparison with dense search.** Plain dense retrieval (bge-base embeddings) is a strong baseline here. Shelfwise beats it by **+0.039 nDCG@10**, with a paired 95% CI of +0.002 to +0.077, so the gain is real but only just: the CI barely excludes zero, and the two settings that produced it (author narrowing, a weaker reading-level vote) were tuned on this same dev split. The locked test split is the honest check. Where Shelfwise clearly wins is **negation** (0.60 vs 0.29 nDCG@10), lookups (0.98 vs 0.88) and vague requests (0.53 vs 0.47). It still trails dense on learning requests (0.73 vs 0.79) and genre (0.78 vs 0.83), and it is about 8x slower (the parser, filters and lookups; the LLM parse itself is cached in these timings).

![The architecture](docs/img/final-architecture.png)

## What it does

- **Understands the whole request.** A query parser (Qwen3-4B, rules as the fallback) turns it into hard constraints (page limits, availability, an excluded tag), soft preferences (mood, pace, "for beginners") and a topic. Each shows as a chip the reader can drop or switch between "must" and "preferred".
- **Never breaks a hard constraint.** Constraints become one SQL query that returns the allowed books, and every search channel scores only those ([ADR 1](docs/decisions/0001-filter-first-exact-search.md)).
- **Handles "not".** Every book is tagged offline by an LLM for romance, violence, darkness, pace, supernatural, audience and more, so "without the romance" becomes a filter instead of a vector that drifts towards romance ([ADR 2](docs/decisions/0002-facets-for-negation.md), [the study](docs/negation-study.md)).
- **Can't invent books.** The narrating LLM's output schema only accepts the IDs of the books retrieval found; titles, authors and availability come from the database; a validator checks every sentence before it's shown or spoken ([ADR 3](docs/decisions/0003-id-constrained-generation.md)).
- **Holds a conversation.** "Shorter", "not so dark", "something like the second one", "only ones I can borrow today" refine the previous request; a new topic starts fresh; undo brings the last one back.
- **Talks.** Whisper large-v3-turbo listens, Silero VAD hears when you stop, Kokoro speaks. The first sentence is spoken while the LLM is still writing the rest, and speaking over it interrupts it.
- **Has a face.** A VRM avatar whose lips move with the audio as it plays, so it can't drift or delay the voice ([ADR 5](docs/decisions/0005-avatar-lip-sync.md)).
- **Shows its work.** `/bench` draws the leaderboard with confidence intervals, quality against latency, scores per kind of request, grounding, and the voice timings; the chat's inspector shows the parse and the candidates at each stage.

## How it was evaluated

- **Set A, retrieval** (`eval/data/queries.csv`): requests in eleven categories (lookup, author, genre, negation, availability, similarity, vague, learning, …), split into dev and test by paraphrase family. The test split hasn't been looked at.
- **Relevance grades**: every system's top 10 is pooled and graded 0–3 by written rules ([eval/GRADING.md](eval/GRADING.md)). Claude grades the pool; a person grades a blind sample to measure agreement: within one grade 90% of the time, relevant/not κ 0.60–0.63 (the same person regrading the sample agreed with themselves at κ 0.76).
- **Set B, parsing**: gold parses for 184 requests ([eval/PARSING.md](eval/PARSING.md)). **Set C**: scripted conversations, the state checked after every turn. **Set E, grounding**: made-up titles, prompt injections (in the message and in catalog text), checked-out books, ordinary requests; Shelfwise vs naive RAG vs an LLM alone.
- **Book tags** against 200 hand-reviewed books: audience 96% (κ 0.90), supernatural 95%, fiction 100%; graded scales (darkness, violence, romance) 57–67% exact but 97–99% within one step.
- **Voice** (`make measure`): spoken questions through the live page in a real browser, timed from the last word of the question to the first word of the answer leaving the speakers, with the avatar off and on.

Reports are JSON files in `eval/reports/`, one per run, named by time and commit.

## Design decisions

1. [Filter first, then exact vector search in memory](docs/decisions/0001-filter-first-exact-search.md)
2. [Negation through LLM-extracted book facets](docs/decisions/0002-facets-for-negation.md)
3. [The LLM may only cite retrieved books](docs/decisions/0003-id-constrained-generation.md)
4. [Ollama with Qwen3-4B for the local LLM](docs/decisions/0004-ollama-local-llm.md)
5. [Lip-sync from the playing audio, in the browser](docs/decisions/0005-avatar-lip-sync.md)
6. [Fine-tuning setup and one locked test run](docs/decisions/0006-fine-tuning-setup.md)

The full design, with the alternatives considered, is in [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md).

## Still to come: the GPU day

One command on an RTX 4090 (`make gpu-day`, [scripts/gpu_day.py](scripts/gpu_day.py)) fine-tunes the embedder (bge-base, cached MNRL on graded pairs and 10,696 synthetic requests) and two cross-encoder rerankers, re-embeds the catalog, re-runs the dev benchmark and the rerank depth sweep, and then runs the **locked test split once** for the base and the final configuration. Its numbers go in the table above. The off-the-shelf reranker currently makes ranking worse (0.600 at its best depth, below dense alone), which is the case for fine-tuning one.

## Known gaps

- **Voice on 8 GB.** With the 4B LLM, the API and Whisper loaded together the Mac swaps (4.5 GB of swap in use), and every stage slows: of the 11.5 s mean wait, transcription takes 4.6 s (1.2 s when the LLM isn't loaded), the LLM parse 3.5 s, search 1.5 s (0.1–0.3 s otherwise) and the first spoken sentence 1.1 s; hearing the end of the question is a fixed 0.7 s. A 16 GB machine, or a smaller Whisper, is the fix; the pipeline itself streams (the first sentence plays while the LLM is still writing the rest).
- **Graded tags are coarse.** The tagger and a human agree on darkness or violence within one step almost always, but exactly only about 60% of the time, so "nothing too dark" filters at the right level only partly.
- **Conversation misses** (set C): "novel" rarely sets fiction; "psychological thriller" stays its own genre; "cozy" doesn't lower darkness; "not ya" isn't an exclusion; "doesn't matter if it's checked out" doesn't drop availability.
- **One grader.** Grades come from Claude with a person's blind check; a second human annotator would show whether the system ranking holds.
- Not done, on purpose: distilling the parser into a smaller model (the 4B parser is accurate enough and fast with caching), public hosting (the LLM can't be hosted without paid APIs or a permanent GPU).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/), Docker, [Ollama](https://ollama.com) and Node 24.

```bash
cp .env.example .env
make install             # Python 3.12 env + git hooks
make up                  # Postgres (pgvector) + Redis
make migrate             # the catalog schema
make import-seed         # the seed shelf from Open Library (~5 min first time, cached after)
make download-goodreads  # UCSD Book Graph subsets, ~1.6 GB (academic use only)
make build-catalog       # ~5,000 works from them (~10 min)
make simulate            # shelves, copies and 12 months of simulated loans
make embed               # embeddings for meaning-based search
make llm-pull            # the LLM (~2.5 GB); then `make llm` in its own terminal
make download-tts download-stt download-avatar   # voice and the placeholder avatar
make api                 # http://localhost:8000/api/v1/health
make web                 # http://localhost:5173 (another terminal)
```

Then `make test` (unit), `make test-all` (with the database), `make web-test`, `make web-e2e` (a real browser), `make eval` (the benchmark), `make measure` (the voice timings).

**Stack:** Python 3.12, FastAPI, SQLAlchemy, Postgres 16 + pgvector, sentence-transformers, bm25s, Ollama, mlx-whisper, kokoro-onnx · React 19, Vite, Tailwind 4, three.js + @pixiv/three-vrm, zustand · pytest + Hypothesis, Vitest, Playwright, ruff, pyright.

## Licences of what it uses

None of the data or models below are in this repository; the `make download-*` targets and the first run fetch them. Details and versions: [CREDITS.md](CREDITS.md).

| Kind | What | Licence |
| --- | --- | --- |
| Data | UCSD Book Graph (Goodreads, 2017) | Academic use only; downloaded locally, never redistributed |
| Data | Open Library metadata | CC0 (public domain) |
| Data | Open Library covers | Publishers' images, shown as catalogue thumbnails under Open Library's terms |
| Embedding model | BAAI bge-base-en-v1.5 (and the fine-tuned copy) | MIT |
| Rerankers | cross-encoder/ms-marco-MiniLM-L6-v2, BAAI bge-reranker-base | Apache-2.0, MIT |
| LLM | Qwen3-4B (Mac), Qwen3-8B and 14B (GPU runs), via Ollama | Apache-2.0 |
| Speech to text | Whisper large-v3-turbo (MLX 4-bit conversion) | MIT |
| Voice activity | Silero VAD | MIT |
| Voice | Kokoro-82M, voice `af_heart` (kokoro-onnx export) | Apache-2.0 (model), MIT (kokoro-onnx) |
| Avatar | pixiv's VRM1_Constraint_Twist_Sample until our own VRoid model | VRM Public License 1.0 |
| Animation | None: idle motion, blinking, head turns and lip-sync are procedural | — |
| Fonts | Source Serif 4, Schibsted Grotesk | SIL Open Font License 1.1 |

The live session's architecture borrows ideas, no code, from a friend's project ([bytesy-z/SEECS-AI-Receptionist](https://github.com/bytesy-z/SEECS-AI-Receptionist)).

**Data citation.** Mengting Wan and Julian McAuley, "Item Recommendation on Monotonic Behavior Chains", RecSys 2018; Mengting Wan, Rishabh Misra, Ndapa Nakashole and Julian McAuley, "Fine-Grained Spoiler Detection from Large-Scale Review Corpora", ACL 2019.
