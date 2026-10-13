# 4. Ollama with Qwen3-4B for the local LLM

**Status:** accepted, 2026-10-06

## Context

No paid APIs, and the development machine is an M2 Mac with 8 GB of RAM that also runs Postgres, the embedder, Whisper and Kokoro. The LLM parses requests (latency-critical) and narrates answers (streamed). Both need reliable JSON-schema output.

## Decision

- **Runtime: Ollama.** One command to install and serve, JSON-schema `format` for constrained decoding, streaming, model keep-alive. llama.cpp's server is the fallback if grammar tricks are ever needed; vLLM brings nothing for one user.
- **Model: Qwen3-4B (Q4, ~2.5 GB)** on the Mac with thinking off; Qwen3-8B/14B only on the 4090 (grounding runs, catalog tagging).
- The parser is a **cascade**: rules first (a fast path for plain lookups), the LLM for the rest, and the rules as the fallback when the LLM is down or its answer fails validation.

## Consequences

- Parser on gold set B (184 dev queries): intent accuracy 90.8%, exact match 79.4%, constraint F1 95.0% (precision 98.0%, recall 92.2%).
- On the 8 GB Mac the 4B model and the API (~3.3 GB) don't fit in memory together without swapping, which shows up in the voice timings; a 16 GB machine would not have this problem.
- Distilling the parser into a smaller student was planned and dropped (2026-10-11): the 4B parser is accurate enough and the remaining latency is elsewhere.
