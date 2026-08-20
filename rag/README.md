# rag — CPTS study assistant

Retrieval-augmented generation over a corpus of pentesting notes, running entirely
on the phone. Ask a question, get an answer grounded in *your* notes with the source
paths cited — no hallucinated commands, no internet.

Built for **HTB CPTS** prep. The corpus here is a private tree of HTB Academy / CPTS
module notes (information gathering, exploitation, password attacks, privilege
escalation, post-exploitation). Heavy CTF work is intended to move to a laptop RTX 4060
later; this runs the always-on study assistant.

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
| `bin/rag-embed-server.sh` | phone | Serves nomic-embed on :8082 (embedding mode) |
| `bin/rag-index.py` | phone | Chunks `corpus/`, embeds each chunk → `index.jsonl` |
| `bin/rag-ask.py` | phone | Embeds a query, cosine top-k, prompts the chat model |

## Usage (on the phone)

```sh
# one time: put your notes under ~/rag/corpus/ (markdown), then
~/rag/bin/rag-embed-server.sh &          # start the embed server (:8082)
python3 ~/rag/bin/rag-index.py           # build ~/rag/index.jsonl
python3 ~/rag/bin/rag-ask.py "how do I crack an NTLMv2 hash with hashcat?"
```

From the laptop, run the same `rag-ask.py` over SSH, or call the chat server directly
with your own retrieval client.

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
