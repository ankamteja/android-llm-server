#!/data/data/com.termux/files/usr/bin/bash
# Launch llama-server on the phone.
# Runs on the DEVICE (inside Termux), not on the laptop.
set -euo pipefail

MODEL="${LLM_MODEL:-$HOME/models/qwen3-4b.gguf}"
KEYFILE="${LLM_KEYFILE:-$HOME/.config/llm-api-key}"
PORT="${LLM_PORT:-8081}"
THREADS="${LLM_THREADS:-8}"
CTX="${LLM_CTX:-8192}"

[ -r "$MODEL" ]   || { echo "no model at $MODEL — run bin/fetch-model.sh first" >&2; exit 1; }
[ -r "$KEYFILE" ] || { echo "no API key at $KEYFILE — run install.sh first" >&2; exit 1; }

# Android suspends the CPU when idle; without this the server stalls mid-request.
termux-wake-lock

# Flags tuned for a phone CPU:
#   --flash-attn on        faster attention, lower memory
#   --cache-type-k/v q8_0  quantized KV cache — fits an 8192 context in RAM
#   --host 0.0.0.0         LAN-reachable, which is why --api-key is mandatory
exec llama-server \
  --model     "$MODEL" \
  --host      0.0.0.0 \
  --port      "$PORT" \
  --api-key   "$(cat "$KEYFILE")" \
  --ctx-size  "$CTX" \
  --threads   "$THREADS" \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --parallel  1 \
  --cont-batching
