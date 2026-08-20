# Plain-English guide

No jargon. What this thing is, how to use it, and what to do when it breaks.
If you read only one file, read this one.

---

## What did we actually build?

Your Galaxy S25 — the one with the dead screen — is now a little **server**. A server
is just a computer that stays on and answers requests. It sits plugged in, and your
laptop asks it questions.

Two things run on it:

1. **A private ChatGPT** (a model called Qwen3-4B). It runs entirely on the phone.
   No internet, no account, nothing leaves your devices.
2. **A study assistant for HTB CPTS** that answers using *your own notes*. You ask
   "how do I crack an NTLMv2 hash?", it finds the relevant bit of your notes, and
   writes an answer based on them — with the note's file name so you can check it.

That's it. A phone that answers pentest questions from your notes, offline.

---

## The two things that always confused people

**"Server" just means always-on computer.** Your laptop sleeps when you close it.
The phone doesn't. So anything you want available all the time lives on the phone.

**"API key" is just a password.** The phone is reachable by anyone on the same Wi-Fi.
The key stops strangers from using it. Every request must carry the key or it's
rejected. Your key is in a file on the phone; keep it secret, like any password.

---

## How to use it (copy-paste)

You talk to the phone from your laptop. First connect (pick ONE):

**By USB cable (simplest, always works):**
```bash
adb forward tcp:8081 tcp:8081
```

**By Wi-Fi (both on the same network, no cable):**
```bash
# nothing to set up — just use the phone's address in the commands below
# phone address today: <phone-ip>  (this can change — see "IP changed?" below)
```

Then set your password once per terminal. Read it from the phone rather than
pasting it into a file — a key that lives in a document ends up in a commit:
```bash
adb forward tcp:8022 tcp:8022
KEY=$(ssh -p 8022 localhost 'cat ~/.config/llm-api-key')
```

### Ask the plain model a question
```bash
curl -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  http://localhost:8081/v1/chat/completions \
  -d '{"messages":[{"role":"user","content":"explain SMB null sessions"}]}'
```
(Over Wi-Fi, replace `localhost` with `<phone-ip>`.)

### Ask the CPTS assistant (answers from YOUR notes)

**Easiest — in a browser** (from any device on the same Wi-Fi):
```
http://<phone-ip>:8083
```
It opens a chat page. Paste the API key once when it asks (the browser remembers it),
type a question, and the answer streams in with the note files it used listed under it.
This is the assistant that reads *your notes* — port 8081 is the plain model that does
not. Any OpenAI-compatible app pointed at `http://<phone-ip>:8083/v1` gets the same
notes-aware answers.

> The key travels in clear text over the local Wi-Fi here, and this page can read the
> private notes. Fine for your own use on a trusted network; see `docs/SECURITY.md`
> before exposing it wider.

**Or on the command line** (log into the phone):
```bash
ssh -p 8022 <phone-ip>        # or: adb forward tcp:8022 tcp:8022 && ssh -p 8022 localhost
python3 ~/rag/bin/rag-ask.py "how do I enumerate SNMP?"
```
It streams an answer, then the note files it used.

---

## What it's good at, and what it isn't

**Good at:** summarising, rewriting, recalling things from your notes, standard pentest
commands and methodology, quick "how do I..." questions. Great as a study aid.

**Not good at:** hard multi-step reasoning, anything needing current/internet info,
and it is **slower than ChatGPT** — about 12 words a second once it starts, after a few
seconds of reading your question on the phone's GPU. That's the price of running on a
phone. It is built to be the always-on, offline study box; heavier work belongs on a
desktop GPU.

Think of it as a sharp intern that never sleeps and never phones home — not a genius.

---

## When something breaks

**"Connection refused" / no answer**
The server probably isn't running. Restart it:
```bash
ssh -p 8022 <phone-ip>
~/bin/llm-server.sh &          # the chat model
~/rag/bin/rag-embed-server.sh & # the notes-search helper
```
Or just reboot the phone — everything restarts automatically on boot.

**"401 Unauthorized"**
Wrong or missing password. Check you set `KEY=` correctly and included the
`Authorization: Bearer $KEY` header.

**IP changed? (Wi-Fi stopped working)**
The phone's Wi-Fi address isn't fixed. Get the new one over USB:
```bash
adb shell ip -4 addr show wlan0 | grep inet
```
Use that new address instead of `<phone-ip>`.

**I added new notes — how does it learn them?**
Put the new `.md` files in `~/rag/corpus/` on the phone, then:
```bash
python3 ~/rag/bin/rag-index.py
```
It re-reads everything. No "training" needed — it just re-indexes.

---

## Can I use it from anywhere (off the local network)?

Not yet. The phone is behind a NAT'd network that blocks incoming
connections from the outside world — and the usual tools that get around that
(Tailscale, etc.) may be blocked on such networks. The fix is a cheap/free
cloud server acting as a middleman; it's designed but not built. Details in
`docs/NETWORKING.md`. For now: works on the local Wi-Fi and over USB.

---

## The map (where things live on the phone)

```
~/models/qwen3-4b.gguf     the chat model (the "brain")
~/models/nomic-embed.gguf  the notes-search model
~/bin/llm-server.sh        starts the chat model on port 8081
~/rag/corpus/              YOUR notes (the source material)
~/rag/index.jsonl          the searchable version of your notes
~/rag/bin/rag-ask.py       ask a question over your notes
~/.config/llm-api-key      your password (keep secret)
~/.termux/boot/start-lab.sh runs all of it automatically after a reboot
```

Deeper detail, if you ever want it: `docs/ARCHITECTURE.md` (how it works),
`docs/SETUP.md` (how it was built), `docs/NETWORKING.md` (why remote access is hard),
`docs/MAINTENANCE.md` (the phone cleanup), `rag/README.md` (the notes assistant).
