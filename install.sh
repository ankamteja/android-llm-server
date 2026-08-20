#!/data/data/com.termux/files/usr/bin/bash
# One-shot setup. Runs on the DEVICE (inside Termux) on a fresh install.
# Idempotent: safe to re-run — it only fills in what is missing.
set -euo pipefail

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------
# Fail early with a clear message rather than halfway through a package install.
[ -n "${PREFIX:-}" ] && [ -d "$PREFIX" ] || die "this must run inside Termux (\$PREFIX not set)"
case "$(uname -m)" in
  aarch64|arm64) : ;;
  *) die "built for aarch64 phones; this device is $(uname -m)" ;;
esac
# The model alone is 2.3 GB; ask for a little headroom on top.
avail_kb=$(df -Pk "$HOME" | awk 'NR==2{print $4}')
[ "${avail_kb:-0}" -ge 3500000 ] || die "need ~3.5 GB free under \$HOME, have $((avail_kb/1024)) MB"

# --- packages --------------------------------------------------------------
# llama-cpp is the server. The Vulkan backend plus Mesa's turnip driver are what
# let prompt processing run on the Adreno GPU (4x faster than CPU); without them
# everything silently falls back to CPU. python runs the RAG pipeline and mints
# the API key. See bench/RESULTS.md for why the GPU packages matter.
say "installing packages (this pulls the Vulkan GPU backend)"
pkg update -y
pkg install -y \
  llama-cpp \
  llama-cpp-backend-vulkan \
  mesa-vulkan-icd-freedreno \
  python \
  openssh \
  tmux \
  termux-api

# --- directories -----------------------------------------------------------
say "creating directories"
mkdir -p "$HOME/bin" "$HOME/models" "$HOME/.config" "$HOME/.termux/boot" \
         "$HOME/rag/bin" "$HOME/rag/corpus"

# --- scripts ---------------------------------------------------------------
say "installing scripts"
install -m 700 bin/llm-server.sh        "$HOME/bin/llm-server.sh"
install -m 700 bin/fetch-model.sh       "$HOME/bin/fetch-model.sh"
install -m 755 boot/start-lab.sh        "$HOME/.termux/boot/start-lab.sh"
# RAG pipeline: shared core plus the three entry points.
install -m 644 rag/bin/ragcore.py           "$HOME/rag/bin/ragcore.py"
install -m 700 rag/bin/rag-embed-server.sh  "$HOME/rag/bin/rag-embed-server.sh"
install -m 755 rag/bin/rag-index.py         "$HOME/rag/bin/rag-index.py"
install -m 755 rag/bin/rag-ask.py           "$HOME/rag/bin/rag-ask.py"
install -m 755 rag/bin/rag-web.py           "$HOME/rag/bin/rag-web.py"

# --- API key ---------------------------------------------------------------
# Termux ships no openssl, so the key is minted with python's secrets module,
# which is always present. Never overwrite an existing key on a re-run.
KEYFILE="$HOME/.config/llm-api-key"
if [ ! -r "$KEYFILE" ]; then
  say "generating API key"
  python3 -c "import secrets; print(secrets.token_hex(24))" > "$KEYFILE"
  chmod 600 "$KEYFILE"
fi

# --- GPU sanity check ------------------------------------------------------
# Not fatal: the server still runs on CPU if the GPU is unavailable, just slower.
if command -v vulkaninfo >/dev/null 2>&1; then
  if vulkaninfo --summary 2>/dev/null | grep -qi adreno; then
    say "GPU detected: $(vulkaninfo --summary 2>/dev/null | grep -i adreno | head -1 | sed 's/^[[:space:]]*//')"
  fi
fi

echo
say "setup done. API key (also at $KEYFILE):"
cat "$KEYFILE"
echo
cat <<'NEXT'
next steps:
  ~/bin/fetch-model.sh      download + verify the chat model (~2.3 GB, resumable)
  ~/bin/llm-server.sh       start the chat server on :8081

for the notes assistant (RAG), additionally:
  - put an embedding model at ~/models/nomic-embed.gguf   (see rag/README.md)
  - put your notes (markdown) under ~/rag/corpus/
  - ~/rag/bin/rag-embed-server.sh   then   python3 ~/rag/bin/rag-index.py

everything autostarts on reboot via ~/.termux/boot/start-lab.sh
NEXT
