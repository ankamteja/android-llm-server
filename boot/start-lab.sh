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
