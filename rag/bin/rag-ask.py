#!/data/data/com.termux/files/usr/bin/env python3
"""Answer a CPTS study question from the notes. Runs on the DEVICE.

    python3 rag-ask.py "how do I crack an NTLMv2 hash with hashcat?"

Embeds the question, finds the most similar note chunks by cosine similarity
(pure Python, no numpy), then asks the chat model to answer using only that
retrieved context. Prints the answer followed by the sources it drew from.

For a browser window or an OpenAI-compatible endpoint over the same retrieval,
run rag-web.py instead — it keeps the index in memory between questions.
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ragcore  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question", nargs="+")
    ap.add_argument("--top-k", type=int, default=ragcore.TOP_K)
    ap.add_argument("--index", default=None)
    ap.add_argument("--no-stream", action="store_true",
                    help="wait for the whole answer instead of printing tokens")
    ap.add_argument("--show-scores", action="store_true",
                    help="print the similarity score next to each source")
    args = ap.parse_args(argv)
    question = " ".join(args.question)

    try:
        index = ragcore.Index.load(args.index)
        hits = ragcore.retrieve(index, question, top_k=args.top_k)
        messages, hits = ragcore.build_messages(question, hits)
        if args.no_stream:
            print(ragcore.chat(messages))
        else:
            for token in ragcore.chat(messages, stream=True):
                sys.stdout.write(token)
                sys.stdout.flush()
            print()
    except ragcore.RagError as exc:
        print(f"rag-ask: {exc}", file=sys.stderr)
        return 1

    print("\n--- sources ---")
    if args.show_scores:
        seen = set()
        for score, doc in hits:
            if doc["source"] not in seen:
                seen.add(doc["source"])
                print(f"  {score:.3f}  {doc['source']}")
    else:
        for src in ragcore.sources(hits):
            print(f"  {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
