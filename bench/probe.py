#!/usr/bin/env python3
"""Report prompt-eval and generation speed straight from llama-server's timings.

    python3 bench/probe.py [URL]

Run it against the chat server (default http://localhost:8081) after an
`adb forward tcp:8081 tcp:8081`. Prompt-eval speed is the number that decides
how long you wait before an answer starts, and it is the one that changes when
the GPU backend is or is not in play.
"""
import json
import os
import sys
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8081/v1/chat/completions"
KEYFILE = os.path.expanduser(os.environ.get("LLM_KEYFILE", "~/.config/llm-api-key"))
KEY = os.environ.get("LLM_API_KEY") or (
    open(KEYFILE).read().strip() if os.path.exists(KEYFILE) else "")

payload = {
    # Long enough that prompt processing dominates and is measured accurately.
    "messages": [{"role": "user", "content": "Explain SMB enumeration. " * 60}],
    "max_tokens": 16,
    "temperature": 0,
}
req = urllib.request.Request(
    URL, data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
with urllib.request.urlopen(req, timeout=600) as resp:
    t = json.load(resp)["timings"]

print(f"prompt: {t['prompt_n']:>5} tok at {t['prompt_per_second']:>6.1f} tok/s")
print(f"gen:    {t['predicted_n']:>5} tok at {t['predicted_per_second']:>6.1f} tok/s")
