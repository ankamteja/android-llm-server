# android-llm-server

Run a local, offline LLM as an always-on network service on an **unrooted Android phone**.

A Galaxy S25 with a dead display panel, permanently plugged in, serving an
OpenAI-compatible chat API over the LAN. No root, no custom ROM, no cloud.

```
   ANY CLIENT                                  PHONE (unrooted Android)
  ┌────────────┐                              ┌──────────────────────────┐
  │ curl / IDE │ ── POST /v1/chat/completions │  llama-server :8081      │
  │ OpenAI SDK │                              │  Qwen3-4B-Instruct Q4_K_M│
  │            │ ◀── streamed tokens ───────  │  6 threads, 4096 ctx     │
  └────────────┘                              └──────────────────────────┘
        │                                              ▲
        └──── USB (adb forward) ── or ── Wi-Fi ────────┘
```

## Why this is interesting

Phones are the most over-provisioned idle computers most people own. This one has
8 cores, 12 GB of RAM, a built-in UPS, and draws about 3 W. The constraint that makes
it a real engineering problem is that **you are not root**, which rules out the entire
normal server toolkit — no Docker, no `iptables`, no TUN devices, no ports below 1024.
Everything here is designed around that.

## Quickstart

**On the phone** (inside [Termux](https://termux.dev)):

```sh
git clone https://github.com/ankamteja/android-llm-server
cd android-llm-server
./install.sh          # packages, dirs, scripts, generates an API key
~/bin/fetch-model.sh  # ~2.3 GB, resumable
~/bin/llm-server.sh   # serves on :8081
```

**From your laptop:**

```sh
echo "<the API key install.sh printed>" > ~/.config/s25-llm-key
./client/llm "explain NAT traversal in two sentences"
```

The client auto-selects USB when a device is attached and falls back to `$LLM_HOST`
over Wi-Fi otherwise.

## What's in here

| Path | Runs on | Purpose |
|---|---|---|
| `install.sh` | phone | One-shot setup: packages, dirs, API key |
| `bin/fetch-model.sh` | phone | Resumable GGUF download |
| `bin/llm-server.sh` | phone | Launches `llama-server` with a wake lock |
| `boot/start-lab.sh` | phone | Termux:Boot autostart — sshd, tmux, LLM |
| `client/llm` | laptop | CLI client, USB-or-Wi-Fi transport selection |

## Documentation

- **[Architecture](docs/ARCHITECTURE.md)** — how every layer works, from the Android
  sandbox up through quantization and the request path. Written to be readable with
  no prior systems background.
- **[Setup log](docs/SETUP.md)** — the actual build, in order, including what broke.
- **[Networking](docs/NETWORKING.md)** — why remote access is the hard part: NAT,
  private addressing, and a DPI-filtered campus network.


## Measured performance

On the Galaxy S25 (Snapdragon 8 Elite, 6 of 8 cores, Qwen3-4B-Instruct Q4_K_M):

| Metric | Value |
|---|---|
| Generation | ~13.5 tokens/sec |
| Prompt processing | ~27 tokens/sec |
| Model load time | ~2.6 s |
| Idle RAM headroom | ~4 GB free with model resident |
| First-token latency | sub-second over USB |

Fast enough to read along with. Not instant, but usable for real work.

## Endpoint authentication

The API key protects the endpoints that cost CPU. Health and discovery are open:

| Endpoint | Auth required |
|---|---|
| `POST /v1/chat/completions` | yes — 401 without key |
| `POST /completion` | yes — 401 without key |
| `GET /health` | no (liveness probe) |
| `GET /v1/models` | no (capability discovery) |

This is standard `llama-server` behaviour: nothing that consumes compute is reachable
without the key.

## Security

`llama-server` binds `0.0.0.0`, so it is reachable by anything that can route to the
phone. On the network this was built on, client isolation is **off** — any device on
the same `/20` can reach it. So the API key is mandatory, not decorative:

- key generated with `openssl rand -hex 24`, stored `chmod 600` at `~/.config/llm-api-key`
- `.gitignore` excludes the key and all `*.gguf` weights
- the key never appears in this repository

## Status

Working: model serving, API-key auth, USB + Wi-Fi access, reboot persistence.

Not solved: **access from outside the LAN.** The phone sits behind carrier-grade NAT
with no inbound path, and the mesh-VPN services that normally solve this are
DPI-blocked on this network. See [docs/NETWORKING.md](docs/NETWORKING.md) for the
measurements and the VPS-relay design that fixes it.

## License

MIT — see [LICENSE](LICENSE).
