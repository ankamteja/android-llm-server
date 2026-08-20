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

# Browser front end for the notes assistant on :8083 (localhost only). Open it
# from the laptop with:  adb forward tcp:8083 tcp:8083 && xdg-open http://localhost:8083
# Unlike :8081 this applies retrieval before answering, so it needs the index.
if [ -r "$HOME/rag/index.jsonl" ] && [ -r "$HOME/rag/bin/rag-web.py" ]; then
  tmux has-session -t ragweb 2>/dev/null || \
    tmux new-session -d -s ragweb "python3 $HOME/rag/bin/rag-web.py"
fi
