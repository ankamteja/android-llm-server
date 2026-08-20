# Architecture

How an unrooted phone becomes a network service, layer by layer.
Written assuming no prior systems background.

---

## 0. What a "server" actually is

A computer that stays on and answers requests over a network. That's the whole
definition. A phone qualifies — it just usually isn't asked to.

```
   LAPTOP                                   PHONE
  ┌──────────┐                            ┌──────────────┐
  │ client   │ ── "what is a monad?" ───▶ │ llama-server │
  │          │ ◀── "a monad is ..." ────  │ + Qwen3-4B   │
  └──────────┘                            └──────────────┘
```

Everything below is plumbing that makes those two arrows reliable.

---

## 1. Android is Linux wearing different clothes

Android is not an alternative to Linux — it *is* Linux, with a different userland.
The device here reports:

```
Linux 6.6.98-android15  aarch64
```

A real kernel, managing processes, memory and sockets exactly like a desktop.
What differs is what sits on top: instead of `bash` and `/usr/bin`, you get Java
applications, each sandboxed as its own user account.

**The governing constraint: no root.** Every app runs as a locked-down numeric user.
Termux here is `u0_a485`. Nearly every design decision follows from that:

| Wanted | Blocked because |
|---|---|
| `warp-cli` / any VPN daemon | `/dev/tun` is `crw-rw---- system:vpn`; `u0_a485` isn't in that group |
| Docker / containers | needs kernel namespace + capability privileges |
| Bind port 443 or 53 | kernel reserves ports < 1024 for root |
| `iptables` firewall rules | needs `CAP_NET_ADMIN` |

The architecture works *around* these rather than fighting them.

---

## 2. Termux — a Linux userland without root

Termux is an ordinary Android app that unpacks a full Linux environment inside its
own private directory:

```
/data/data/com.termux/files/usr     ← acts as /usr
/data/data/com.termux/files/home    ← acts as /home/you
```

It needs no root because it never touches anything outside that directory. It runs
normal ARM64 binaries as a normal sandboxed user. `pkg install llama-cpp` simply
drops a binary in there.

**One subtlety that matters.** Desktop Linux links against **glibc**; Android uses
**bionic**. The C library is how every program asks the kernel to do anything, so a
Debian binary will not run under Termux even on identical hardware. Termux maintains
its own rebuilt package repository. This is the second, independent reason vendor
`.deb` packages like Cloudflare's `warp-cli` cannot work here.

---

## 3. Two transports to reach the device

```
        ┌──────────── PATH A: USB ─────────────┐
LAPTOP ═╡  adb forward tcp:8081 tcp:8081       ╞═ PHONE
        └──────────────────────────────────────┘

        ┌──────────── PATH B: Wi-Fi ───────────┐
LAPTOP ─┤  http://<phone-lan-ip>:8081          ├─ PHONE
        └──────────────────────────────────────┘
```

**Path A — USB.** `adb` is Android's debug bridge. `adb forward tcp:8081 tcp:8081`
means: *open port 8081 on the laptop, and pipe anything arriving there down the USB
cable to port 8081 on the phone.* The laptop talks to `localhost` and never knows the
traffic left the machine.

- Immune to IP changes — no IP is involved at all.
- Survives Wi-Fi outages.
- Dies on replug; the forward is bound to one adb session and must be re-established.

**Path B — Wi-Fi.** Ordinary IP routing to the phone's LAN address. Convenient, but
the address is a DHCP lease and will drift.

`client/llm` tries USB first and falls back to Wi-Fi, so callers don't care which is live.

---

## 4. Why "from anywhere" is the hard part

Worth understanding properly, because it is the one unsolved piece.

Addresses in `10.0.0.0/8`, `192.168.0.0/16` and `172.16.0.0/12` are **private**. They
are not globally unique — millions of networks reuse the same numbers — so the public
internet refuses to route them. A phone at `10.12.219.205` is meaningful only inside
its own network.

```
   INTERNET                 EDGE ROUTER (NAT)              PHONE
  outbound ────────────────────▶  allowed  ──────────────▶  fine
  inbound  ◀──── dropped ──────   no mapping to consult     unreachable
```

The network has one public address shared by thousands of devices, via **NAT**
(Network Address Translation). On an outbound connection the router records "replies
to this flow go to `.205`" and rewrites headers accordingly. Inbound connections have
no such record — the router receives a packet for an address it owns, with no way to
know which of thousands of devices should receive it, so it drops it.

**This is not a setting. It is how NAT works.** A device behind NAT cannot receive
unsolicited connections.

**How mesh VPNs normally fix it.** Tailscale and friends have both machines make
*outbound* connections to a coordination server, which introduces them to each other.
Both sides dialled out, so NAT is satisfied. You get a stable virtual address
(`100.x.y.z`) that works from anywhere.

**Why that failed here.** See [NETWORKING.md](NETWORKING.md) — the network runs SNI-based
deep packet inspection and resets connections to every known mesh-VPN provider.

**The fix that works:** rent a host that *has* a public IP. The phone dials out to it
and holds the connection open; the relay lends the phone its address.

```
  CLIENT (anywhere) ──▶ VPS public IP ──▶ [tunnel opened outbound by phone] ──▶ PHONE
```

---

## 5. The model

Three ideas.

**A model is a large array of numbers.** Qwen3-4B has ~4 billion parameters learned
during training. Inference means pushing your input through all of them. Nothing is
fetched from the internet at request time — that's what "offline" means here.

**Quantization is what makes it fit.** Parameters are natively 16-bit, so 4B of them
is roughly 8 GB — more than the ~3.4 GB of RAM actually available on this device.
`Q4_K_M` stores most weights in about 4 bits, shrinking the file to **2.32 GB** for a
modest quality loss. `.gguf` is llama.cpp's container format for such models.

**llama.cpp runs it on CPU.** Most ML tooling assumes an NVIDIA GPU. llama.cpp is
portable C++ that runs on ordinary processors including ARM, using NEON SIMD
instructions. `llama-server` wraps it in an HTTP API that mimics OpenAI's, so existing
clients work unchanged against it.

Launch flags and why each is there:

```
--host 0.0.0.0     listen on all interfaces, not just loopback
--port 8081        must be >1024 — non-root cannot bind lower
--api-key <key>    mandatory: 0.0.0.0 on a LAN without client isolation
--ctx-size 4096    tokens of context retained per conversation
--threads 6        6 of 8 cores; 2 left for Android itself
--cont-batching    keep the pipeline fed across overlapping requests
--mlock            pin weights in RAM so Android cannot swap them out
```

`--mlock` matters more than it looks: without it, Android's memory manager will page
the model out under pressure and the first token after an idle period takes seconds.

---

## 6. Staying alive

Android aggressively kills background work to protect battery. Three defenses:

- **`termux-wake-lock`** — tells Android to keep the CPU running. Without it, long
  jobs stall the moment the device idles.
- **`tmux`** — a session that outlives your connection. Normally, closing SSH kills
  its children; tmux detaches them instead.
- **`Termux:Boot`** — runs `~/.termux/boot/start-lab.sh` after each reboot, restarting
  `sshd`, the work session, and the LLM.

Two further settings applied out-of-band on the device:

```sh
settings put global settings_enable_monitor_phantom_procs false   # stop reaping bg procs
# both Termux packages added to the battery-optimisation whitelist
```

Autostart is guarded so a missing model can't leave a broken service running:

```sh
if [ -r "$HOME/models/qwen3-4b.gguf" ] && [ -r "$HOME/.config/llm-api-key" ]; then
  tmux has-session -t llm 2>/dev/null || \
    tmux new-session -d -s llm "$HOME/bin/llm-server.sh"
fi
```

---

## 7. One request, end to end

```
 1. client issues POST /v1/chat/completions
 2. adb pipes it down the USB cable  (or it routes over Wi-Fi)
 3. arrives at phone port 8081
 4. llama-server validates the API key         ← wrong key stops here
 5. prompt is tokenized into integers
 6. tokens flow through 4B parameters across 6 CPU cores
 7. one token predicted at a time, each appended and fed back in
 8. tokens detokenized to text and streamed back
```

Steps 5–7 are the only genuinely "AI" part. Everything else is moving bytes reliably —
which is the honest shape of most infrastructure work.
