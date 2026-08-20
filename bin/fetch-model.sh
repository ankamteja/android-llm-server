#!/data/data/com.termux/files/usr/bin/bash
# Download and verify the chat model (GGUF). Runs on the DEVICE (inside Termux).
# Resumable — safe to re-run after a dropped connection.
set -euo pipefail

# Pin the exact build so a rebuild is reproducible. Override URL/DEST/SHA to use
# a different quant or model.
URL="${LLM_MODEL_URL:-https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
DEST="${LLM_MODEL:-$HOME/models/qwen3-4b.gguf}"
SHA256="${LLM_MODEL_SHA256:-3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597}"

mkdir -p "$(dirname "$DEST")"
termux-wake-lock

verify() {
  [ -r "$DEST" ] || return 1
  [ -n "$SHA256" ] || return 0   # nothing to check against
  printf '%s  %s\n' "$SHA256" "$DEST" | sha256sum -c --status
}

if verify; then
  echo "model already present and verified at $DEST"
  exit 0
fi

# -C - resumes a partial file; --retry-all-errors survives a flaky connection.
echo "downloading $(basename "$URL") ..."
curl -4 -L -C - --retry 999 --retry-delay 5 --retry-all-errors -o "$DEST" "$URL"

if [ -n "$SHA256" ]; then
  echo "verifying checksum ..."
  if verify; then
    echo "checksum OK"
  else
    echo "CHECKSUM MISMATCH for $DEST" >&2
    echo "  expected: $SHA256" >&2
    echo "  got:      $(sha256sum "$DEST" | cut -d' ' -f1)" >&2
    echo "delete the file and re-run, or set LLM_MODEL_SHA256 if you changed the model." >&2
    exit 1
  fi
fi

echo "model at $DEST ($(du -h "$DEST" | cut -f1))"
