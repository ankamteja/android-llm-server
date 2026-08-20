#!/data/data/com.termux/files/usr/bin/bash
# One-shot setup. Runs on the DEVICE (inside Termux) on a fresh install.
set -euo pipefail

echo "==> installing packages"
pkg update -y
pkg install -y llama-cpp openssh tmux termux-api

echo "==> creating directories"
mkdir -p "$HOME/bin" "$HOME/models" "$HOME/.config" "$HOME/.termux/boot"

echo "==> installing scripts"
install -m 700 bin/llm-server.sh  "$HOME/bin/llm-server.sh"
install -m 700 bin/fetch-model.sh "$HOME/bin/fetch-model.sh"
install -m 755 boot/start-lab.sh  "$HOME/.termux/boot/start-lab.sh"

KEYFILE="$HOME/.config/llm-api-key"
if [ ! -r "$KEYFILE" ]; then
  echo "==> generating API key"
  openssl rand -hex 24 > "$KEYFILE"
  chmod 600 "$KEYFILE"
fi

echo
echo "setup done. API key:"
cat "$KEYFILE"
echo
echo "next:  ~/bin/fetch-model.sh    then    ~/bin/llm-server.sh"
