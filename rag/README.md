# rag — CPTS study assistant

Retrieval-augmented generation over a corpus of pentesting notes, running entirely
on the phone. Ask a question, get an answer grounded in *your* notes with the source
paths cited — no hallucinated commands, no internet.

Built for **HTB CPTS** prep. The corpus here is a private tree of HTB Academy / CPTS
module notes (information gathering, exploitation, password attacks, privilege
escalation, post-exploitation). It runs as an always-on, offline study assistant;
heavier work belongs on a desktop GPU.

## How it works

```
  question
     │
     ▼  search_query: <question>
  ┌────────────────────┐   768-dim vector   ┌──────────────────────────┐
  │ embed server :8082 │───────────────────▶│ cosine top-k over        │
  │ nomic-embed-v1.5   │                     │ ~1300 note chunks (pure  │
  └────────────────────┘                     │ Python, no numpy)        │
                                             └────────────┬─────────────┘
                                                          │ 5 best chunks
                                                          ▼
                    system + retrieved notes + question ──▶ chat server :8081
                                                          (Qwen3-4B, API key)
                                                          │
                                                          ▼
                                             answer + cited source paths
```

Two models, two ports, both on the phone:

- **:8081** — the chat model (Qwen3-4B), the main server, API-key protected.
- **:8082** — the embedding model (nomic-embed-text-v1.5), bound to `127.0.0.1` only
  (never leaves the phone; retrieval is a purely local step).

Retrieval never trains or changes a model. Solve a new box, drop the write-up in
`corpus/`, re-run the indexer — the assistant knows it immediately. That is the whole
advantage of RAG over fine-tuning for a knowledge base that keeps growing.

## Pieces

| Path | Runs on | Purpose |
|---|---|---|
| `bin/ragcore.py` | phone | Chunking, scoring, prompt assembly — shared by the three below |
| `bin/rag-embed-server.sh` | phone | Serves nomic-embed on :8082 (embedding mode) |
| `bin/rag-index.py` | phone | Chunks `corpus/`, embeds each chunk → `index.jsonl` |
| `bin/rag-ask.py` | phone | Embeds a query, cosine top-k, prompts the chat model |
| `bin/rag-web.py` | phone | Browser page + OpenAI-compatible endpoint on :8083 |

## Usage (on the phone)

```sh
# one time: put your notes under ~/rag/corpus/ (markdown), then
~/rag/bin/rag-embed-server.sh &          # start the embed server (:8082)
python3 ~/rag/bin/rag-index.py           # build ~/rag/index.jsonl
python3 ~/rag/bin/rag-ask.py "how do I crack an NTLMv2 hash with hashcat?"
```

## In a browser

`rag-web.py` serves a chat page on :8083 and keeps the index in memory, so it does
not re-read it per question. From the laptop:

```sh
adb forward tcp:8083 tcp:8083
xdg-open http://localhost:8083
```

It binds `127.0.0.1` on the phone, so it is reachable only through that forward and
never sits on the wider network. If you do bind it to a routable address
(`--host 0.0.0.0`), it requires the same bearer token as :8081.

## Which port applies retrieval

This is the distinction that matters, and it is easy to get wrong:

| Port | Retrieval | What it answers from |
|---|---|---|
| `:8081` | **no** | the model's weights alone |
| `:8083` | **yes** | your notes, retrieved and pasted into the prompt |

`llama-server` on :8081 knows nothing about `corpus/`. Anything pointed straight at
it — curl, a browser, any OpenAI client — gets an answer that never saw your notes.
Point clients at :8083 instead; it speaks the same `/v1/chat/completions` shape and
adds a `sources` field to the response.

```sh
curl http://localhost:8083/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"how do I enumerate SMB shares?"}]}'
```

## Speed

Retrieval is not the slow part: embedding the question, scoring all 1560 chunks in
pure Python and taking the top 5 costs **161 ms**. The wait is prompt processing on
the chat model, which is why the retrieved context is capped by a character budget
(`RAG_CONTEXT_CHARS`, default 2000) rather than a fixed chunk count — prompt length
is the wait. See [../bench/RESULTS.md](../bench/RESULTS.md).

## Tests

`tests/` covers chunking, scoring, retrieval ranking, prompt assembly and the whole
HTTP surface against stand-in model servers, so it runs on a laptop and in CI with
no phone and no model weights:

```sh
python3 -m pytest tests/ -q
```

## Chunking

Markdown is split on `###`/`####` headings and `***` rules, **never cutting a fenced
code block** — commands stay whole. Tiny sections merge forward; oversized ones split
at blank lines. Each chunk carries a breadcrumb derived from its file path
(`exploitation > password-attacks > john-the-ripper`) so retrieval and citations stay
oriented within the CPTS module tree.

## Design notes

- **No numpy.** Termux's Python has no numpy wheel without a build, so cosine
  similarity is plain Python. Over ~1300 chunks a query scores in well under a second.
- **Embedding prefixes matter.** nomic-embed distinguishes documents from queries:
  chunks are embedded as `search_document: …`, questions as `search_query: …`.
  Skipping this measurably degrades retrieval.
- **Batch size, not context, was the ceiling.** The embed server rejected inputs over
  512 tokens until `--batch-size`/`--ubatch-size` were raised to 2048; the indexer also
  truncates any chunk to a safe length as a backstop.
- **The corpus stays private.** `corpus/` and `index.jsonl` are gitignored — this
  module ships the pipeline, never the notes.
