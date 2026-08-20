#!/data/data/com.termux/files/usr/bin/bash
# Persistent embedding server for the RAG pipeline. Runs on the DEVICE.
# nomic-embed-text-v1.5 in embedding mode, OpenAI-compatible /v1/embeddings on :8082.
set -euo pipefail
MODEL="${RAG_EMBED_MODEL:-$HOME/models/nomic-embed.gguf}"
PORT="${RAG_EMBED_PORT:-8082}"

# The chat server takes the six performance cores (cpu0-5); this one gets the
# two prime cores (cpu6-7), so the two never fight for the same core. Before
# this split they asked for 12 threads between them on an 8-core phone.
THREADS="${RAG_EMBED_THREADS:-2}"
CPU_MASK="${RAG_EMBED_CPU_MASK:-0xc0}"   # cpu6-7

# Embedding is pure prompt processing, which is exactly what the Adreno GPU is
# good at, so this is where offload pays off most — it is the difference
# between a fast and a slow rag-index.py run over the whole corpus. As in
# bin/llm-server.sh, GGML_BACKEND_PATH is deliberately left unset so that ggml
# discovers every backend rather than just one.

[ -r "$MODEL" ] || { echo "no embed model at $MODEL" >&2; exit 1; }
termux-wake-lock
exec llama-server \
  --model     "$MODEL" \
  --host      127.0.0.1 \
  --port      "$PORT" \
  --embeddings \
  --pooling   mean \
  --ctx-size  2048 \
  --batch-size  2048 \
  --ubatch-size 2048 \
  --n-gpu-layers 99 \
  --threads   "$THREADS" \
  --cpu-mask  "$CPU_MASK" \
  --cpu-strict 1
