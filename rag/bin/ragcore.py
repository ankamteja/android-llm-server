"""Shared RAG pieces: chunking, index loading, retrieval, prompt assembly.

Imported by rag-index.py (build), rag-ask.py (CLI) and rag-web.py (browser +
OpenAI-compatible endpoint) so all three agree on how notes are cut up, scored
and handed to the model. Pure standard library — Termux has no numpy.
"""
import json
import math
import os
import re
import urllib.error
import urllib.request
from array import array
from operator import mul

# --- configuration ---------------------------------------------------------
# Every value is env-overridable so tests can point at a fake server.

EMBED_URL = os.environ.get("RAG_EMBED_URL", "http://127.0.0.1:8082/v1/embeddings")
CHAT_URL = os.environ.get("RAG_CHAT_URL", "http://127.0.0.1:8081/v1/chat/completions")
INDEX_PATH = os.path.expanduser(os.environ.get("RAG_INDEX", "~/rag/index.jsonl"))
KEYFILE = os.path.expanduser(os.environ.get("LLM_KEYFILE", "~/.config/llm-api-key"))
TOP_K = int(os.environ.get("RAG_TOP_K", "5"))

MAX_WORDS = 350  # target chunk size; larger sections are split at blank lines
MIN_WORDS = 20   # sections smaller than this are merged forward
EMBED_CHARS = 6000  # ~1800 tokens, under the embed ctx/batch ceiling

# Time to first token is prompt-eval bound, and on this phone that is the whole
# wait: retrieval takes ~160 ms while prompt eval runs at roughly 20 tokens per
# second. A token is about 4 characters, so every 1000 characters of retrieved
# notes costs ~12 seconds before the answer starts. We therefore pull a generous
# top_k (ranking is cheap) and then spend a fixed character budget on the
# best-scoring chunks, rather than pasting in a fixed number of them and letting
# the prompt size — and the wait — vary with whatever the chunker produced.
# Raise it for more thorough answers, lower it for a faster first token.
CONTEXT_CHARS = int(os.environ.get("RAG_CONTEXT_CHARS", "2000"))
MAX_TOKENS = int(os.environ.get("RAG_MAX_TOKENS", "512"))

SYSTEM = (
    "You are a penetration-testing study assistant for the HTB CPTS exam. "
    "Answer using ONLY the provided notes context. Give exact commands and flags. "
    "Cite the source path in brackets after each step. "
    "If the context does not cover the question, say so plainly instead of guessing."
)


class RagError(RuntimeError):
    """Anything the caller should show the user rather than traceback on."""


# --- chunking (used at index time) -----------------------------------------

def breadcrumb(path, corpus):
    """exploitation/password-attacks/john-the-ripper/README.md
       -> 'exploitation > password attacks > john the ripper'"""
    rel = os.path.relpath(path, corpus)
    parts = rel[:-3].split(os.sep) if rel.endswith(".md") else rel.split(os.sep)
    if parts and parts[-1].lower() in ("readme", "index"):
        parts = parts[:-1]
    return " > ".join(p.replace("-", " ") for p in parts)


def split_sections(text):
    """Yield (heading, body) splitting on # .. #### headings and *** rules,
    keeping fenced ``` code blocks intact."""
    sections, cur_head, cur, in_code = [], "", [], False

    def flush(h, buf):
        body = "\n".join(buf).strip()
        if body:
            sections.append((h, body))

    for ln in text.splitlines():
        if ln.strip().startswith("```"):
            in_code = not in_code
            cur.append(ln)
            continue
        if not in_code and (re.match(r"^#{1,4}\s+", ln) or ln.strip() == "***"):
            flush(cur_head, cur)
            cur = []
            if ln.strip() != "***":
                cur_head = re.sub(r"^#{1,4}\s+", "", ln).strip()
            continue
        cur.append(ln)
    flush(cur_head, cur)
    return sections


def pack(sections):
    """Merge tiny sections forward, split oversized ones at blank lines."""
    out, buf_h, buf = [], "", []

    def wc(s):
        return len(s.split())

    for head, body in sections:
        if wc(body) < MIN_WORDS and buf:
            buf.append(body)
            continue
        if buf:
            out.append((buf_h, "\n\n".join(buf)))
            buf = []
        if wc(body) > MAX_WORDS:
            acc = []
            for p in body.split("\n\n"):
                if acc and sum(wc(x) for x in acc) + wc(p) > MAX_WORDS:
                    out.append((head, "\n\n".join(acc)))
                    acc = []
                acc.append(p)
            if acc:
                out.append((head, "\n\n".join(acc)))
        else:
            buf_h, buf = head, [body]
    if buf:
        out.append((buf_h, "\n\n".join(buf)))
    return out


def chunk_file(path, corpus):
    """Read one markdown file into index-ready chunk dicts (no vectors yet)."""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    crumb = breadcrumb(path, corpus)
    return [
        {"source": os.path.relpath(path, corpus), "breadcrumb": crumb,
         "heading": head, "text": body}
        for head, body in pack(split_sections(text))
    ]


def document_text(chunk):
    """The string that gets embedded for a chunk (nomic needs its prefix)."""
    return (f"search_document: {chunk['breadcrumb']} > {chunk['heading']}\n"
            f"{chunk['text']}")[:EMBED_CHARS]


# --- vectors ---------------------------------------------------------------

def normalize(vec):
    """Unit-length float array, so cosine similarity is a plain dot product."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return array("f", vec)
    return array("f", (x / norm for x in vec))


def dot(a, b):
    return sum(map(mul, a, b))


def cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return sum(map(mul, a, b)) / (na * nb + 1e-9)


# --- index -----------------------------------------------------------------

class Index:
    """The embedded corpus held in memory.

    Vectors are stored pre-normalized as float32 arrays: 1560 chunks x 768 dims
    is ~4.8 MB this way versus ~38 MB as lists of Python floats, which matters
    on a phone that is already near its RAM ceiling.
    """

    def __init__(self, docs, vectors):
        self.docs = docs
        self.vectors = vectors

    def __len__(self):
        return len(self.docs)

    @classmethod
    def load(cls, path=None):
        path = os.path.expanduser(path or INDEX_PATH)
        if not os.path.exists(path):
            raise RagError(f"no index at {path} — run rag-index.py first")
        docs, vectors = [], []
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    vec = rec.pop("vector")
                except (ValueError, KeyError) as exc:
                    raise RagError(
                        f"{path}:{lineno} is not a valid index record ({exc})") from exc
                docs.append(rec)
                vectors.append(normalize(vec))
        if not docs:
            raise RagError(f"index at {path} is empty")
        return cls(docs, vectors)

    def search(self, query_vec, top_k=TOP_K):
        """Return [(score, doc)] for the top_k most similar chunks."""
        qv = normalize(query_vec)
        scored = ((dot(qv, v), i) for i, v in enumerate(self.vectors))
        best = sorted(scored, reverse=True)[:top_k]
        return [(score, self.docs[i]) for score, i in best]


# --- talking to the two model servers --------------------------------------

def _post(url, payload, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RagError(f"{url} returned {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RagError(
            f"cannot reach {url}: {exc.reason} — is the server up?") from exc


def embed(text, url=None, timeout=120):
    """One embedding vector from the local nomic server."""
    resp = _post(url or EMBED_URL, {"input": text[:EMBED_CHARS], "model": "nomic"},
                 {"Content-Type": "application/json"}, timeout)
    with resp as r:
        return json.load(r)["data"][0]["embedding"]


def embed_query(question, url=None, timeout=120):
    """nomic asymmetric retrieval: questions get a different prefix to notes."""
    return embed(f"search_query: {question}", url=url, timeout=timeout)


def api_key(keyfile=None):
    path = os.path.expanduser(keyfile or KEYFILE)
    try:
        with open(path) as fh:
            key = fh.read().strip()
    except OSError as exc:
        raise RagError(f"cannot read API key at {path}: {exc}") from exc
    if not key:
        raise RagError(f"API key file {path} is empty")
    return key


def fit_context(hits, budget=None):
    """Best-scoring chunks that fit the character budget, best first.

    Returns (kept_hits, context_string). The top hit is always kept even if it
    alone exceeds the budget, in which case it is truncated — an answer from a
    clipped note beats no answer.
    """
    budget = CONTEXT_CHARS if budget is None else budget
    kept, blocks, used = [], [], 0
    for score, doc in hits:
        block = f"[{doc['source']} — {doc['heading']}]\n{doc['text']}"
        if not kept and len(block) > budget:
            block = block[:budget] + "\n[...truncated]"
        elif used + len(block) > budget:
            continue  # a later, shorter chunk may still fit
        kept.append((score, doc))
        blocks.append(block)
        used += len(block)
    return kept, "\n\n".join(blocks)


def build_context(hits, budget=None):
    """The notes block pasted in front of the question."""
    return fit_context(hits, budget)[1]


def build_messages(question, hits, system=SYSTEM, budget=None):
    """System + user messages for a retrieval-augmented answer.

    Returns (messages, kept_hits) so the caller cites only the notes that
    actually made it into the prompt."""
    kept, context = fit_context(hits, budget)
    messages = [
        {"role": "system", "content": system},
        {"role": "user",
         "content": f"Notes context:\n\n{context}\n\n---\nQuestion: {question}"},
    ]
    return messages, kept


def sources(hits):
    """Unique source paths, best match first."""
    seen, out = set(), []
    for _, doc in hits:
        if doc["source"] not in seen:
            seen.add(doc["source"])
            out.append(doc["source"])
    return out


def retrieve(index, question, top_k=TOP_K, embed_url=None):
    """Embed the question and pull the most similar chunks."""
    return index.search(embed_query(question, url=embed_url), top_k=top_k)


def chat(messages, stream=False, url=None, key=None, timeout=300, **params):
    """Call the chat server. Returns the answer string, or a token iterator
    when stream=True."""
    payload = {"messages": messages, "stream": bool(stream),
               "temperature": 0.2, "max_tokens": MAX_TOKENS}
    payload.update(params)
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {key or api_key()}"}
    resp = _post(url or CHAT_URL, payload, headers, timeout)
    if not stream:
        with resp as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()
    return _iter_stream(resp)


def _iter_stream(resp):
    """Yield content deltas from an OpenAI-style SSE response."""
    with resp as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                delta = json.loads(data)["choices"][0].get("delta", {})
            except (ValueError, KeyError, IndexError):
                continue
            piece = delta.get("content")
            if piece:
                yield piece


def ask(index, question, top_k=TOP_K, stream=False, budget=None, **kw):
    """Retrieve then answer. Returns (answer_or_iterator, kept_hits)."""
    hits = retrieve(index, question, top_k=top_k)
    messages, kept = build_messages(question, hits, budget=budget)
    return chat(messages, stream=stream, **kw), kept
