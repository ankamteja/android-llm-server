#!/data/data/com.termux/files/usr/bin/env python3
"""Build the RAG index. Runs on the DEVICE.

Walks the corpus of markdown notes, splits each into heading-bounded chunks
(never cutting a fenced code block), embeds every chunk through the local
embedding server, and writes one JSON object per line to the index.

    python3 rag-index.py [CORPUS_DIR] [INDEX_FILE]

Defaults: ~/rag/corpus  ->  ~/rag/index.jsonl
Talks to the embedding server on http://127.0.0.1:8082 (see rag-embed-server.sh).
"""
import json, os, re, sys, urllib.request, time

CORPUS = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/rag/corpus")
INDEX  = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/rag/index.jsonl")
EMBED_URL = os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8082/v1/embeddings")

MAX_WORDS = 350   # target chunk size; larger sections are split at blank lines
MIN_WORDS = 20    # sections smaller than this are merged forward

def breadcrumb(path):
    """exploitation/password-attacks/john-the-ripper/README.md
       -> 'exploitation > password-attacks > john-the-ripper'"""
    rel = os.path.relpath(path, CORPUS)
    parts = rel.replace(".md", "").split(os.sep)
    if parts and parts[-1].lower() in ("readme", "index"):
        parts = parts[:-1]
    return " > ".join(p.replace("-", " ") for p in parts)

def split_sections(text):
    """Yield (heading, body) splitting on ### / #### headings and *** rules,
    keeping fenced ``` code blocks intact."""
    lines = text.splitlines()
    sections, cur_head, cur, in_code = [], "", [], False
    def flush(h, buf):
        body = "\n".join(buf).strip()
        if body:
            sections.append((h, body))
    for ln in lines:
        if ln.strip().startswith("```"):
            in_code = not in_code
            cur.append(ln); continue
        if not in_code and (re.match(r"^#{1,4}\s+", ln) or ln.strip() == "***"):
            flush(cur_head, cur)
            cur = []
            cur_head = re.sub(r"^#{1,4}\s+", "", ln).strip() if ln.strip() != "***" else cur_head
            continue
        cur.append(ln)
    flush(cur_head, cur)
    return sections

def pack(sections):
    """Merge tiny sections forward, split oversized ones at blank lines."""
    out, buf_h, buf = [], "", []
    def wc(s): return len(s.split())
    for head, body in sections:
        if wc(body) < MIN_WORDS and buf:
            buf.append(body); continue
        if buf:
            out.append((buf_h, "\n\n".join(buf))); buf = []
        if wc(body) > MAX_WORDS:
            para, acc = body.split("\n\n"), []
            for p in para:
                if sum(wc(x) for x in acc) + wc(p) > MAX_WORDS and acc:
                    out.append((head, "\n\n".join(acc))); acc = []
                acc.append(p)
            if acc: out.append((head, "\n\n".join(acc)))
        else:
            buf_h, buf = head, [body]
    if buf: out.append((buf_h, "\n\n".join(buf)))
    return out

def embed(text):
    text = text[:6000]  # ~1800 tokens, under the embed ctx/batch ceiling
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"input": text, "model": "nomic"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["data"][0]["embedding"]

def main():
    files = []
    for root, _, names in os.walk(CORPUS):
        for n in names:
            if n.endswith(".md"):
                files.append(os.path.join(root, n))
    files.sort()
    print(f"corpus: {len(files)} files", flush=True)

    chunks = []
    for f in files:
        crumb = breadcrumb(f)
        for head, body in pack(split_sections(open(f, encoding="utf-8", errors="ignore").read())):
            chunks.append({"source": os.path.relpath(f, CORPUS),
                           "breadcrumb": crumb, "heading": head, "text": body})
    print(f"chunks: {len(chunks)}", flush=True)

    t0 = time.time()
    with open(INDEX, "w") as out:
        for i, c in enumerate(chunks):
            doc = f"search_document: {c['breadcrumb']} > {c['heading']}\n{c['text']}"
            c["vector"] = embed(doc)
            out.write(json.dumps(c) + "\n")
            if (i + 1) % 25 == 0 or i + 1 == len(chunks):
                print(f"  embedded {i+1}/{len(chunks)}", flush=True)
    print(f"done: {len(chunks)} chunks -> {INDEX} in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
