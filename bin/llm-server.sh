#!/data/data/com.termux/files/usr/bin/bash
# Launch llama-server on the phone.
# Runs on the DEVICE (inside Termux), not on the laptop.
set -euo pipefail

MODEL="${LLM_MODEL:-$HOME/models/qwen3-4b.gguf}"
KEYFILE="${LLM_KEYFILE:-$HOME/.config/llm-api-key}"
PORT="${LLM_PORT:-8081}"
THREADS="${LLM_THREADS:-6}"
CTX="${LLM_CTX:-4096}"

[ -r "$MODEL" ]   || { echo "no model at $MODEL — run bin/fetch-model.sh first" >&2; exit 1; }
[ -r "$KEYFILE" ] || { echo "no API key at $KEYFILE — run install.sh first" >&2; exit 1; }

# Android suspends the CPU when idle; without this the server stalls mid-request.
termux-wake-lock

# --host 0.0.0.0 exposes this to the whole LAN, which is why --api-key is not optional.
exec llama-server \
  --model     "$MODEL" \
  --host      0.0.0.0 \
  --port      "$PORT" \
  --api-key   "$(cat "$KEYFILE")" \
  --ctx-size  "$CTX" \
  --threads   "$THREADS" \
  --parallel  1 \
  --cont-batching \
  --mlock
