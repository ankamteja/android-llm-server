#!/data/data/com.termux/files/usr/bin/bash
# Launch llama-server on the phone.
# Runs on the DEVICE (inside Termux), not on the laptop.
set -euo pipefail

MODEL="${LLM_MODEL:-$HOME/models/qwen3-4b.gguf}"
KEYFILE="${LLM_KEYFILE:-$HOME/.config/llm-api-key}"
PORT="${LLM_PORT:-8081}"
CTX="${LLM_CTX:-8192}"

# Snapdragon 8 Elite is 6 performance cores (cpu0-5, 3.53 GHz) plus 2 prime
# cores (cpu6-7, 4.47 GHz). Splitting work evenly across all 8 is slower than
# using the 6 matched cores: the threads on the prime cores finish their share
# early and then idle, and the two cores left free absorb the OS and the GPU
# driver. Measured on this device, generation goes 9.1 -> 12.2 tokens/sec by
# dropping from 8 unpinned threads to 6 pinned ones.
THREADS="${LLM_THREADS:-6}"
CPU_MASK="${LLM_CPU_MASK:-0x3f}"   # cpu0-5

# The GPU (Adreno 830, reached through Mesa's turnip Vulkan driver) is about
# 4x faster than the CPU at prompt processing -- 75 vs 19 tokens/sec -- and
# prompt processing is what decides how long you wait before an answer starts.
# It is slower at generating tokens, so the split below is deliberate: GPU for
# the prompt, the pinned CPU cores for generation.
#
# ggml discovers its backend libraries by looking next to the llama-server
# binary, which only resolves correctly when the server is started from a
# Termux shell (as boot/start-lab.sh does via tmux). Do NOT set
# GGML_BACKEND_PATH here: pointing it at a single .so restricts ggml to that
# one backend, which silently drops the GPU and costs 4x on prompt eval.
NGL="${LLM_NGL:-99}"

[ -r "$MODEL" ]   || { echo "no model at $MODEL — run bin/fetch-model.sh first" >&2; exit 1; }
[ -r "$KEYFILE" ] || { echo "no API key at $KEYFILE — run install.sh first" >&2; exit 1; }

# Android suspends the CPU when idle; without this the server stalls mid-request.
termux-wake-lock

# Flags tuned for this phone:
#   -ngl 99                offload to the Adreno GPU for prompt processing
#   --cpu-strict           keep the worker threads on the cores chosen above
#   --poll 100             spin rather than sleep between batches
# (--prio is deliberately absent: raising thread priority needs root, and an
# unrooted Termux just logs "Operation not permitted" once per thread.)
#   --flash-attn on        faster attention, lower memory
#   --cache-type-k/v q8_0  quantized KV cache — fits an 8192 context in RAM
#   --host 0.0.0.0         LAN-reachable, which is why --api-key is mandatory
exec llama-server \
  --model     "$MODEL" \
  --host      0.0.0.0 \
  --port      "$PORT" \
  --api-key   "$(cat "$KEYFILE")" \
  --ctx-size  "$CTX" \
  --n-gpu-layers "$NGL" \
  --threads   "$THREADS" \
  --cpu-mask  "$CPU_MASK" \
  --cpu-strict 1 \
  --poll      100 \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --parallel  1 \
  --cont-batching
