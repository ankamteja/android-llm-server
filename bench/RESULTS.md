# Measured performance

Galaxy S25 (`SM-S931B`), Snapdragon 8 Elite, 12 GB RAM, unrooted Termux.
Model: Qwen3-4B-Instruct-2507, Q4_K_M, 2.32 GiB.
llama.cpp build b10516 (Termux `llama-cpp` package).
Numbers from `llama-bench -p 256 -n 32`, and from `bench/probe.py` against the
live server. `pp` is prompt processing, `tg` is token generation.

## Summary

| | prompt eval | generation |
|---|---:|---:|
| before (CPU only, 8 threads) | 17.9 tok/s | 10.4 tok/s |
| after (GPU + 6 pinned cores) | **70.2 tok/s** | **12.0 tok/s** |

Prompt processing is what you wait on before an answer starts. On a real RAG
question (605-token prompt) that is **36 s → 8.9 s**.

## Where the time goes

Retrieval is not the bottleneck and never was: embedding the question, scoring
all 1560 chunks in pure Python and picking the top 5 takes **161 ms**. The rest
is llama-server.

## The CPU is heterogeneous

`/sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq`:

| cores | clock | role |
|---|---|---|
| cpu0–5 | 3.53 GHz | performance |
| cpu6–7 | 4.47 GHz | prime |

Splitting work evenly across all 8 is *slower* than using the 6 matched cores.
Threads on the prime cores finish their share early and idle, and leaving those
two cores free lets the OS and the GPU driver run without preempting a worker.

| config | pp256 | tg32 |
|---|---:|---:|
| `-t 8` unpinned | 75.12 | 9.14 |
| `-t 8 -C 0xff --cpu-strict 1` | 75.16 | 7.80 |
| **`-t 6 -C 0x3f --cpu-strict 1`** | **75.35** | **12.16** |
| `-t 2 -C 0xc0 --cpu-strict 1` | 74.94 | 8.00 |

So the chat server takes cpu0–5 and the embedding server takes cpu6–7. Before
this split the two asked for 12 threads between them on an 8-core phone.

## The GPU was never being used

The Adreno 830 is reachable from unrooted Termux, but not the way it first
appears:

- The vendor OpenCL driver cannot be loaded. `/vendor/lib64/libOpenCL.so` is
  listed in `/vendor/etc/public.libraries.txt`, but the Android linker refuses
  an absolute path into `/vendor/lib64` from an app namespace, and the bare
  soname resolves to Termux's own ICD loader instead. `ggml_opencl: platform
  IDs not available` is that dead end.
- Vulkan works. `pkg install llama-cpp-backend-vulkan mesa-vulkan-icd-freedreno`
  gives Mesa's **turnip** driver, entirely in userspace, and `vulkaninfo`
  then reports `Adreno (TM) 830`.

CPU-only prompt eval, for comparison — note it scales with thread count, so the
CPU is genuinely compute-starved here in a way the GPU fixes:

| threads | flash-attn | pp256 | tg32 |
|---|---|---:|---:|
| 4 | off | 11.89 | 11.04 |
| 6 | off | 15.78 | 12.92 |
| 8 | off | 18.66 | 12.82 |
| 4 | on | 12.10 | 11.52 |
| 6 | on | 15.99 | 13.43 |
| 8 | on | 17.57 | 14.34 |

Flash-attention makes no meaningful difference to prompt eval on this CPU.

### Do not set `GGML_BACKEND_PATH`

ggml finds its backend libraries by looking next to the `llama-server` binary.
Setting `GGML_BACKEND_PATH` to a single `.so` **restricts** it to that one
backend — pointing it at `libggml-cpu.so` silently disables the GPU and costs
4x on prompt eval. Setting it to a directory, or to a colon-separated list,
fails outright. Leave it unset and start the server from a Termux shell (which
is what `boot/start-lab.sh` does via tmux); started from a bare `ssh` command
the binary path resolves to `/apex/...` and no backend is found at all.

## Reproducing

```bash
# On the phone
llama-bench -m ~/models/qwen3-4b.gguf -p 256 -n 32 -t 6 -C 0x3f --cpu-strict 1

# From the laptop, against the running server
adb forward tcp:8081 tcp:8081
python3 bench/probe.py
```
