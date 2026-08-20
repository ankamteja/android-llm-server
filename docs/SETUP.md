# Setup log

The build in the order it happened, including what broke. Reproducible on any
unrooted Android 11+ device with Termux.

Target device for this build: Galaxy S25 (`SM-S931B`), Android 16, Snapdragon 8 Elite,
8 cores, 12 GB RAM, 219 GB storage. Display panel is dead — the whole build is headless.

---

## Phase 0 — Termux on a screenless phone

Prerequisite work, done before this project. Summarised because the LLM server
depends on all of it.

Termux was installed from the GitHub release (`v0.119.0-beta.3`, `arm64-v8a`).
Play Protect hard-blocks that APK with no "install anyway" option, and
`adb install --bypass-low-target-sdk-block` does not help — that flag addresses the
platform SDK check, not Play Protect. The working route:

```sh
settings put global package_verifier_user_consent -1
settings put global verifier_verify_adb_installs 0
# install, then restore BOTH to 1
```

Restoring both afterwards matters — leaving verification off weakens the device
permanently for a one-time install.

With no usable display, all interaction is through `adb`. A shell inside Termux
without touching the phone:

```sh
run-as com.termux   # plus exporting PREFIX / LD_LIBRARY_PATH / PATH
```

This works **only because the GitHub APK is debug-signed**. A Play Store or F-Droid
release build refuses `run-as`.

Baseline services, already running before this project:

- `sshd` on **8022**, key-only (`PasswordAuthentication no`)
- `tmux` session `lab` for long-lived jobs
- `Termux:Boot` restarting both after reboot
- both Termux packages on the battery-optimisation whitelist
- `settings put global settings_enable_monitor_phantom_procs false`

---

## Phase 1 — capability check

Before committing to a design, confirm the device can actually fetch what it needs.

```
packages.termux.dev      200
pypi.org                 200
registry.npmjs.org       200
proxy.golang.org         200
huggingface.co           200
```

Resources at the time of the build:

```
MemTotal      11 380 216 kB
MemAvailable   3 404 112 kB      ← the number that constrains model choice
SwapTotal     12 582 908 kB      (zram)
storage       133 GB free
cpu0 scaling  2 745 600 kHz
```

**`MemAvailable`, not `MemTotal`, is the real budget.** Android was already using most
of the 12 GB. ~3.4 GB free is what a model actually has to fit in.

---

## Phase 2 — install llama.cpp

```sh
pkg install llama-cpp
```

**First attempt failed:**

```
Err:2 ... llama-cpp aarch64 0.0.0-b10290-0
  404  Not Found
E: Failed to fetch .../llama-cpp_0.0.0-b10290-0_aarch64.deb  404
```

A stale local package index — apt held a version number the mirror had already rotated
away. `apt-get update` first, then install. Worth remembering: a 404 on a `.deb` almost
always means a stale index, not a missing package.

Result: `llama-server`, `llama-cli`, `llama-quantize` and friends in `$PREFIX/bin`.

---

## Phase 3 — choosing a model

Constraint: must fit comfortably inside ~3.4 GB of available RAM.

Candidates probed by `HEAD` request for real file sizes:

| Model | Q4_K_M size | Result |
|---|---|---|
| `Qwen/Qwen3-4B-Instruct-2507-GGUF` | — | 401, gated |
| `unsloth/Qwen3-4B-Instruct-2507-GGUF` | **2.32 GB** | **chosen** |
| `Qwen/Qwen2.5-3B-Instruct-GGUF` | 1.96 GB | available |
| `bartowski/Llama-3.2-3B-Instruct-GGUF` | 1.88 GB | available |
| `Qwen/Qwen2.5-7B-Instruct-GGUF` | — | 404, path moved |

Chose the newest model that fit. A 7B at Q4 (~4.7 GB) would have exceeded available RAM
and thrashed against zram.

Measured throughput was **~1.05 MB/s**, so 2.32 GB takes roughly 38 minutes. The
download therefore runs under `tmux` with `curl -C -` so a dropped connection resumes
rather than restarts:

```sh
tmux new-session -d -s dl \
  "curl -4 -L -C - --retry 999 --retry-delay 5 --retry-all-errors -o ~/models/qwen3-4b.gguf '<url>'"
```

`termux-wake-lock` is essential here — without it Android suspends the CPU and the
transfer stalls the moment the device goes idle.

---

## Phase 4 — the server

`bin/llm-server.sh` launches `llama-server` bound to `0.0.0.0:8081` with an API key.

The key is generated once and never enters the repository:

```sh
openssl rand -hex 24 > ~/.config/llm-api-key
chmod 600 ~/.config/llm-api-key
```

Port 8081 rather than 80 or 443 because a non-root user cannot bind below 1024.
`--api-key` is mandatory rather than optional because the LAN has no client isolation —
see [NETWORKING.md](NETWORKING.md), Measurement 4.

---

## Phase 5 — persistence

`~/.termux/boot/start-lab.sh` extended to start the LLM alongside `sshd` and `tmux`.
The original was backed up to `start-lab.sh.bak` before editing.

The new block is guarded on both the model and the key existing, so a half-finished
install cannot leave a crash-looping service at boot:

```sh
if [ -r "$HOME/models/qwen3-4b.gguf" ] && [ -r "$HOME/.config/llm-api-key" ]; then
  tmux has-session -t llm 2>/dev/null || \
    tmux new-session -d -s llm "$HOME/bin/llm-server.sh"
fi
```

---

## Phase 6 — access

```sh
# USB — immune to IP drift, preferred while docked
adb forward tcp:8081 tcp:8081
curl -H "Authorization: Bearer $KEY" http://localhost:8081/v1/models

# Wi-Fi — convenient, but the address is a DHCP lease and will move
curl -H "Authorization: Bearer $KEY" http://<phone-ip>:8081/v1/models
```

`client/llm` wraps both and picks whichever transport is live.

---

## Gotchas worth keeping

- **Multi-line heredocs do not survive the `adb shell` hop** — they fail with
  `can't create temporary file ... Permission denied`. Pipe files in as `base64 -w0`
  and decode on the device instead.
- **`apt` 404 on a `.deb` means a stale index.** Run `apt-get update` before concluding
  a package is missing.
- **`MemAvailable` is the budget, not `MemTotal`.** Sizing a model against total RAM
  on a phone will pick something that swaps and crawls.
- **Restore `package_verifier_user_consent` to 1** after sideloading. It is easy to
  leave a device permanently less safe for the sake of one install.
- **`--mlock` is not optional in practice.** Without it Android pages the model out
  during idle and the next request stalls for seconds.
