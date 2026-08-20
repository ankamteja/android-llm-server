#!/data/data/com.termux/files/usr/bin/env python3
"""Answer a CPTS study question from the notes. Runs on the DEVICE.

    python3 rag-ask.py "how do I crack an NTLMv2 hash with hashcat?"

Embeds the question, finds the most similar note chunks by cosine similarity
(pure Python, no numpy), then asks the chat model to answer using only that
retrieved context. Prints the answer followed by the sources it drew from.
"""
import json, math, os, sys, urllib.request

INDEX     = os.path.expanduser(os.environ.get("RAG_INDEX", "~/rag/index.jsonl"))
EMBED_URL = os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8082/v1/embeddings")
CHAT_URL  = os.environ.get("RAG_CHAT_URL",  "http://127.0.0.1:8081/v1/chat/completions")
KEYFILE   = os.path.expanduser(os.environ.get("LLM_KEYFILE", "~/.config/llm-api-key"))
TOP_K     = int(os.environ.get("RAG_TOP_K", "5"))

SYSTEM = (
    "You are a penetration-testing study assistant for the HTB CPTS exam. "
    "Answer using ONLY the provided notes context. Give exact commands and flags. "
    "Cite the source path in brackets after each step. "
    "If the context does not cover the question, say so plainly instead of guessing."
)

def embed(text):
    req = urllib.request.Request(
        EMBED_URL, data=json.dumps({"input": text, "model": "nomic"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"][0]["embedding"]

def cosine(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    return dot / (na*nb + 1e-9)

def main():
    if len(sys.argv) < 2:
        print('usage: rag-ask.py "your question"', file=sys.stderr); sys.exit(1)
    question = " ".join(sys.argv[1:])

    if not os.path.exists(INDEX):
        print(f"no index at {INDEX} — run rag-index.py first", file=sys.stderr); sys.exit(1)
    docs = [json.loads(l) for l in open(INDEX)]

    qv = embed(f"search_query: {question}")
    ranked = sorted(docs, key=lambda d: cosine(qv, d["vector"]), reverse=True)[:TOP_K]

    context = "\n\n".join(
        f"[{d['source']} — {d['heading']}]\n{d['text']}" for d in ranked)
    key = open(KEYFILE).read().strip()
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",
             "content": f"Notes context:\n\n{context}\n\n---\nQuestion: {question}"},
        ],
        "stream": False, "temperature": 0.2, "max_tokens": 768,
    }
    req = urllib.request.Request(
        CHAT_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        ans = json.load(r)["choices"][0]["message"]["content"]

    print(ans.strip())
    print("\n--- sources ---")
    seen = set()
    for d in ranked:
        if d["source"] not in seen:
            print(f"  {d['source']}")
            seen.add(d["source"])

if __name__ == "__main__":
    main()
