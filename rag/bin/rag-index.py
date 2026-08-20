#!/data/data/com.termux/files/usr/bin/env python3
"""Build the RAG index. Runs on the DEVICE.

Walks the corpus of markdown notes, splits each into heading-bounded chunks
(never cutting a fenced code block), embeds every chunk through the local
embedding server, and writes one JSON object per line to the index.

    python3 rag-index.py [CORPUS_DIR] [INDEX_FILE]

Defaults: ~/rag/corpus  ->  ~/rag/index.jsonl
Talks to the embedding server on http://127.0.0.1:8082 (see rag-embed-server.sh).
Chunking and embedding live in ragcore.py, shared with rag-ask.py / rag-web.py.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ragcore  # noqa: E402


def collect(corpus):
    files = []
    for root, _, names in os.walk(corpus):
        for name in names:
            if name.endswith(".md"):
                files.append(os.path.join(root, name))
    return sorted(files)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus", nargs="?", default="~/rag/corpus")
    ap.add_argument("index", nargs="?", default="~/rag/index.jsonl")
    args = ap.parse_args(argv)
    corpus = os.path.expanduser(args.corpus)
    index = os.path.expanduser(args.index)

    files = collect(corpus)
    print(f"corpus: {len(files)} files", flush=True)
    if not files:
        print(f"no .md files under {corpus}", file=sys.stderr)
        return 1

    chunks = []
    for path in files:
        chunks.extend(ragcore.chunk_file(path, corpus))
    print(f"chunks: {len(chunks)}", flush=True)

    t0 = time.time()
    tmp = index + ".partial"
    try:
        with open(tmp, "w") as out:
            for i, chunk in enumerate(chunks):
                chunk["vector"] = ragcore.embed(ragcore.document_text(chunk))
                out.write(json.dumps(chunk) + "\n")
                if (i + 1) % 25 == 0 or i + 1 == len(chunks):
                    print(f"  embedded {i+1}/{len(chunks)}", flush=True)
    except ragcore.RagError as exc:
        print(f"rag-index: {exc}", file=sys.stderr)
        print(f"partial index left at {tmp}", file=sys.stderr)
        return 1
    # Only replace a working index once the whole run succeeded.
    os.replace(tmp, index)
    print(f"done: {len(chunks)} chunks -> {index} in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
