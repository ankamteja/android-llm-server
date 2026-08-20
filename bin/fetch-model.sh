#!/data/data/com.termux/files/usr/bin/bash
# Download the GGUF model. Resumable — safe to re-run after a dropped connection.
# Runs on the DEVICE (inside Termux).
set -euo pipefail

URL="${LLM_MODEL_URL:-https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
DEST="${LLM_MODEL:-$HOME/models/qwen3-4b.gguf}"

mkdir -p "$(dirname "$DEST")"
termux-wake-lock

# -C - resumes a partial file; --retry-all-errors survives flaky campus Wi-Fi.
curl -4 -L -C - --retry 999 --retry-delay 5 --retry-all-errors -o "$DEST" "$URL"

echo "model at $DEST ($(du -h "$DEST" | cut -f1))"
