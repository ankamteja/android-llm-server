#!/data/data/com.termux/files/usr/bin/bash
# Persistent embedding server for the RAG pipeline. Runs on the DEVICE.
# nomic-embed-text-v1.5 in embedding mode, OpenAI-compatible /v1/embeddings on :8082.
set -euo pipefail
MODEL="${RAG_EMBED_MODEL:-$HOME/models/nomic-embed.gguf}"
PORT="${RAG_EMBED_PORT:-8082}"
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
  --threads   4
