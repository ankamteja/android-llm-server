# Networking

Why the server is LAN-only today, what was measured, and the design that fixes it.

The host network for this build is a large managed network that does egress filtering.
All findings below are measurements taken from the two endpoints involved — the phone
and the laptop — probing outbound reachability to public internet services. No scanning
of the local network was performed.

---

## The goal and the obstacle

Goal: reach the phone's `:8081` from outside the LAN.

Obstacle, in one line: **the phone has a private address behind NAT, so it cannot
receive inbound connections** — and the standard tools that work around that are
filtered on this network.

---

## Measurement 1 — the phone's address is private

```
wlan0: inet 10.12.219.205/20
```

`10.0.0.0/8` is RFC 1918 private space. Not globally routable, not unique, shared by a
large device population behind one public IP. Inbound connections have no NAT mapping
to follow and are dropped at the edge. Nothing on the device can change this.

Also relevant: the SIM slot is empty.

```
gsm.sim.state = ABSENT,ABSENT
```

So there is no cellular path to fall back to — the device is Wi-Fi-only.

---

## Measurement 2 — mesh VPN providers are filtered

The usual fix is a mesh VPN: both peers dial *out* to a coordinator, which introduces
them, sidestepping NAT entirely. Tested reachability of the relevant control planes:

| Endpoint | TCP 443 | TLS |
|---|---|---|
| `controlplane.tailscale.com` | connects | **RST** |
| `login.tailscale.com` | connects | **RST** |
| `derp1.tailscale.com` | connects | **RST** |
| `my.zerotier.com` | — | **RST** |
| `api.netbird.io` | — | **RST** |
| `region1.v2.argotunnel.com` (Cloudflare Tunnel) | — | **RST** |
| `connect.ngrok-agent.com` | — | **blocked** |
| `tailscale.com` (marketing site) | connects | 200 OK |

The pattern is diagnostic. TCP completes, then the connection is reset **during the TLS
handshake** — and the company's own marketing site, on a different CDN, loads fine.

That is **SNI-based deep packet inspection**. The TLS `ClientHello` carries the
destination hostname in plaintext before encryption begins. The filter reads that field,
matches it against a blocklist, and resets the connection. The block is by *hostname*,
not by protocol or port.

```
client                          filter                      server
  │── TCP SYN ─────────────────────┼──────────────────────────▶│
  │◀─ SYN/ACK ─────────────────────┼───────────────────────────│   TCP fine
  │── TLS ClientHello (SNI: controlplane.tailscale.com) ──▶│
  │◀─ RST ─────────────────────────│                            blocked on the name
```

---

## Measurement 3 — UDP is open; only VPN endpoints are filtered

An early hypothesis was that all external UDP was dropped, which would have ruled out
WireGuard entirely. That was wrong, and re-testing corrected it:

| Destination | Result |
|---|---|
| `1.1.1.1:53` (DNS) | **pass** |
| `9.9.9.9:53` (DNS) | **pass** |
| `pool.ntp.org:123` (NTP) | **pass** |
| `162.159.192.1:2408` (Cloudflare WARP) | no reply |

Generic UDP egress works. Only the *known VPN endpoint* is unreachable. This matters a
great deal for the design: a WireGuard listener on a self-hosted host, on a
non-standard UDP port, presents no hostname to inspect and no known address to match.

---

## Measurement 4 — no client isolation on the LAN

The laptop reaches the phone directly across the wireless network:

```
$ ssh -p 8022 10.12.219.205
OK from localhost — up 6 days
```

Convenient, and also a warning. Client isolation is off, so **every device on the
`/20` can reach the phone's open ports**. This is the direct reason `llama-server`
runs with `--api-key` rather than open. A service bound to `0.0.0.0` on this network
is a service offered to several thousand strangers.

---

## Measurement 5 — `warp-cli` cannot run unrooted

Tested for completeness. Four independent blockers, each sufficient on its own:

```
/dev/tun  →  crw-rw---- 1 system vpn 10, 200
python  →  open("/dev/net/tun")  →  [Errno 13] Permission denied
```

1. **TUN is `system:vpn`.** Termux's `u0_a485` is not in that group. `warp-svc` must
   create a TUN interface; it cannot.
2. **`CAP_NET_ADMIN` required** to manipulate routing tables. Not available unrooted.
3. **No Termux package** — `apt-cache search warp` returns nothing.
4. **glibc vs bionic.** Cloudflare ships Debian/Ubuntu builds; Termux is bionic.
   `proot-distro` would solve the libc mismatch but not the TUN access, since proot
   is a `ptrace` shim that fakes root without granting real capabilities.

Android's own VPN apps work because `VpnService` is a framework API that grants
`vpn` group access to apps holding the permission — a path unavailable to a
non-privileged binary in Termux.

---

## The design that actually works

Stop trying to receive inbound connections on a device that structurally cannot, and
put the public address somewhere that has one.

```
                        ┌────────────────────────┐
  CLIENT ──────────────▶│  VPS — real public IP  │
  (anywhere)            │  WireGuard, UDP :8472  │
                        └───────────┬────────────┘
                                    │  tunnel established
                                    │  OUTBOUND by the phone
                        ┌───────────▼────────────┐
                        │  PHONE  10.x, no ports │
                        │  llama-server :8081    │
                        └────────────────────────┘
```

The phone dials out and holds the tunnel open. Clients hit the VPS's public address and
ride the existing tunnel down. The VPS's only job is to be a fixed address the phone
cannot otherwise have.

Why this is expected to work here:

- Generic UDP egress is confirmed open (Measurement 3).
- A self-hosted endpoint on a non-standard port exposes no SNI hostname and matches no
  provider blocklist — there is nothing for the DPI to key on.
- The phone side runs as an Android VPN app via `VpnService`, so no root is needed.

Cost: an always-free ARM instance from a major cloud provider supplies the public IP at
no charge. The tunnel is the only missing piece; everything on the phone is already built.

---

## Summary

| Question | Answer |
|---|---|
| Reachable on the LAN? | Yes — `http://<phone-ip>:8081`, API key required |
| Reachable over USB? | Yes — `adb forward`, immune to IP drift |
| Reachable from the internet? | **No** — NAT, no inbound path |
| Can Tailscale fix it? | Not on this network — SNI DPI resets its control plane |
| Can `warp-cli` fix it? | No — impossible unrooted, and its endpoint is filtered too |
| What does fix it? | VPS relay + WireGuard on a non-standard UDP port |
