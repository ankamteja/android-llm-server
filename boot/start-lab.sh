#!/data/data/com.termux/files/usr/bin/sh
# Run by Termux:Boot after every reboot. Keep it short and non-interactive.

# Without a wake lock Android suspends the CPU and long jobs stall.
termux-wake-lock

# SSH in over:  adb forward tcp:8022 tcp:8022 && ssh -p 8022 localhost
# Or straight over Wi-Fi:  ssh -p 8022 <phone-ip>
sshd

# One long-lived session to attach to, so work survives a dropped connection.
tmux has-session -t lab 2>/dev/null || tmux new-session -d -s lab

# Local LLM on :8081, API-key protected. Only starts once the model is present.
if [ -r "$HOME/models/qwen3-4b.gguf" ] && [ -r "$HOME/.config/llm-api-key" ]; then
  tmux has-session -t llm 2>/dev/null || \
    tmux new-session -d -s llm "$HOME/bin/llm-server.sh"
fi

# RAG embedding server on :8082 (localhost only), for the CPTS study assistant.
if [ -r "$HOME/models/nomic-embed.gguf" ] && [ -x "$HOME/rag/bin/rag-embed-server.sh" ]; then
  tmux has-session -t embsrv 2>/dev/null || \
    tmux new-session -d -s embsrv "$HOME/rag/bin/rag-embed-server.sh"
fi

# Browser front end for the notes assistant on :8083. Unlike :8081 this applies
# retrieval before answering, so it needs the index.
#
# It is bound LAN-wide so other devices on the Wi-Fi can use it, which means
# every request except /health must carry the bearer token. Note what that
# exposes: this endpoint reads out of the private notes corpus and the token is
# sent in clear text over HTTP. Set RAG_WEB_HOST=127.0.0.1 to go back to
# loopback-only (reachable via adb forward tcp:8083 tcp:8083), which is the
# safer default on a network you do not trust.
if [ -r "$HOME/rag/index.jsonl" ] && [ -r "$HOME/rag/bin/rag-web.py" ]; then
  tmux has-session -t ragweb 2>/dev/null || \
    tmux new-session -d -s ragweb \
      "RAG_WEB_HOST=${RAG_WEB_HOST:-0.0.0.0} python3 $HOME/rag/bin/rag-web.py"
fi
