# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-08-21

First tagged release: an offline LLM server on an unrooted Android phone, plus a
retrieval-augmented notes assistant, both reachable from a laptop or other
devices on the same network.

### Added
- **Chat server** — `llama-server` serving an OpenAI-compatible API on `:8081`,
  API-key protected, autostarting on boot via Termux:Boot and tmux.
- **Notes assistant (RAG)** — a pipeline that embeds a corpus of markdown notes,
  retrieves the most relevant chunks for a question by cosine similarity (pure
  standard library, no numpy), and answers from them with cited sources.
- **Browser UI + OpenAI-compatible RAG endpoint** (`rag/bin/rag-web.py`, `:8083`)
  — a chat page and a `/v1/chat/completions` endpoint that apply retrieval before
  answering and add a `sources` field. Binds LAN-wide behind the bearer token, or
  loopback-only with `RAG_WEB_HOST=127.0.0.1`.
- **Shared core** (`rag/bin/ragcore.py`) — chunking, scoring, prompt assembly used
  by the indexer, the CLI, and the web server so they cannot drift apart. Vectors
  held as pre-normalized float32 arrays (~4.8 MB vs ~38 MB of Python floats).
- **Test suite** (`tests/`) — 60 tests covering the whole path against stand-in
  model servers, so they run on a laptop and in CI with no phone and no model
  weights.
- **CI** (`.github/workflows/ci.yml`) — pytest on Python 3.11–3.13, ruff, and
  shellcheck.
- **Benchmark harness** (`bench/`) — `probe.py` reports live prompt/generation
  throughput; `RESULTS.md` records the full matrix and the GPU story.

### Performance
- **GPU offload** — prompt processing runs on the Adreno GPU through Mesa's turnip
  Vulkan driver, taking prompt-eval from **18 to 70 tokens/sec**. Generation runs
  on the six pinned performance cores at **12 tokens/sec**. A 605-token retrieval
  prompt starts answering in **8.9 s instead of 36 s**.
- Retrieved context is bounded by a character budget rather than a fixed chunk
  count, since time-to-first-token is prompt-eval bound.

### Security
- API key minted with python's `secrets` module (Termux ships no openssl) and
  stored `chmod 600`; never committed.
- The notes corpus and built index are gitignored — the index contains full chunk
  text, so publishing it would publish the notes.

### Setup
- `install.sh` is idempotent, runs a preflight (Termux, aarch64, free space),
  installs the Vulkan GPU packages, and generates the key if absent.
- `bin/fetch-model.sh` pins and verifies the model's SHA256, skipping the
  download when the file is already present and correct.

[0.1.0]: https://github.com/ankamteja/android-llm-server/releases/tag/v0.1.0
