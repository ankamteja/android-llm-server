"""Chunking, vector maths, retrieval and prompt assembly."""
import math
import os

import pytest

import ragcore
from fakes import fake_vector


# --- chunking --------------------------------------------------------------

def test_split_sections_keeps_code_fences_whole():
    text = (
        "# Recon\n"
        "Start here.\n"
        "```bash\n"
        "# this hash is a comment, not a heading\n"
        "nmap -sC -sV target\n"
        "```\n"
        "## Next\n"
        "More.\n"
    )
    sections = dict(ragcore.split_sections(text))
    assert "nmap -sC -sV target" in sections["Recon"]
    # The '#' inside the fence must not have started a new section.
    assert "this hash is a comment" in sections["Recon"]
    assert sections["Next"].strip() == "More."


def test_split_sections_horizontal_rule_keeps_heading():
    text = "## Tools\nfirst\n***\nsecond\n"
    sections = ragcore.split_sections(text)
    assert [h for h, _ in sections] == ["Tools", "Tools"]
    assert [b.strip() for _, b in sections] == ["first", "second"]


def test_pack_merges_tiny_sections_forward():
    sections = [("Big", "word " * 30), ("Tiny", "short")]
    packed = ragcore.pack(sections)
    assert len(packed) == 1
    assert packed[0][0] == "Big"
    assert "short" in packed[0][1]


def test_pack_splits_oversized_sections():
    para = "word " * 200
    packed = ragcore.pack([("Huge", f"{para}\n\n{para}\n\n{para}")])
    assert len(packed) > 1
    assert all(h == "Huge" for h, _ in packed)
    assert all(len(body.split()) <= ragcore.MAX_WORDS * 1.5 for _, body in packed)


def test_breadcrumb_drops_readme_and_dashes():
    crumb = ragcore.breadcrumb("/c/exploitation/password-attacks/README.md", "/c")
    assert crumb == "exploitation > password attacks"


def test_chunk_file_records_relative_source(tmp_path):
    sub = tmp_path / "recon"
    sub.mkdir()
    (sub / "smb.md").write_text("## Shares\nsmbclient -N -L //TARGET\n")
    chunks = ragcore.chunk_file(str(sub / "smb.md"), str(tmp_path))
    assert chunks[0]["source"] == os.path.join("recon", "smb.md")
    assert chunks[0]["heading"] == "Shares"
    assert chunks[0]["breadcrumb"] == "recon > smb"


def test_document_text_carries_nomic_prefix_and_is_clipped():
    chunk = {"breadcrumb": "a > b", "heading": "H", "text": "x" * 20000}
    doc = ragcore.document_text(chunk)
    assert doc.startswith("search_document: a > b > H")
    assert len(doc) == ragcore.EMBED_CHARS


# --- vectors ---------------------------------------------------------------

def test_normalize_gives_unit_length():
    unit = ragcore.normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in unit)), 1.0, rel_tol=1e-6)


def test_cosine_known_values():
    assert math.isclose(ragcore.cosine([1, 0], [1, 0]), 1.0, rel_tol=1e-6)
    assert math.isclose(ragcore.cosine([1, 0], [0, 1]), 0.0, abs_tol=1e-6)
    assert math.isclose(ragcore.cosine([1, 0], [-1, 0]), -1.0, rel_tol=1e-6)
    assert math.isclose(ragcore.cosine([1, 1], [2, 2]), 1.0, rel_tol=1e-6)


def test_dot_of_normalized_matches_cosine():
    a, b = [0.3, -1.2, 4.0, 0.5], [2.0, 1.0, -0.5, 3.0]
    assert math.isclose(ragcore.dot(ragcore.normalize(a), ragcore.normalize(b)),
                        ragcore.cosine(a, b), abs_tol=1e-6)


def test_normalize_survives_zero_vector():
    assert list(ragcore.normalize([0.0, 0.0])) == [0.0, 0.0]


# --- index -----------------------------------------------------------------

def test_index_load_counts_chunks(index):
    assert len(index) == 3
    assert {d["source"] for d in index.docs} == {
        "recon/smb.md", "recon/snmp.md", "creds/hashcat.md"}


def test_index_load_strips_vectors_from_docs(index):
    assert all("vector" not in doc for doc in index.docs)


def test_index_load_missing_file_raises(tmp_path):
    with pytest.raises(ragcore.RagError, match="no index at"):
        ragcore.Index.load(str(tmp_path / "nope.jsonl"))


def test_index_load_empty_file_raises(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    with pytest.raises(ragcore.RagError, match="empty"):
        ragcore.Index.load(str(path))


def test_index_load_corrupt_line_raises(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"source":"a","text":"b"}\n')  # no vector key
    with pytest.raises(ragcore.RagError, match="not a valid index record"):
        ragcore.Index.load(str(path))


def test_search_ranks_the_matching_note_first(index):
    hits = index.search(fake_vector("search_query: how do I enumerate smb shares"),
                        top_k=3)
    assert hits[0][1]["source"] == "recon/smb.md"
    assert [s for s, _ in hits] == sorted((s for s, _ in hits), reverse=True)


def test_search_respects_top_k(index):
    assert len(index.search(fake_vector("anything"), top_k=2)) == 2


def test_search_scores_are_cosines_in_range(index):
    for score, _ in index.search(fake_vector("smb shares"), top_k=3):
        assert -1.0001 <= score <= 1.0001


# --- prompt assembly -------------------------------------------------------

def test_build_messages_puts_notes_before_question(index):
    hits = index.search(fake_vector("smb shares"), top_k=2)
    messages, kept = ragcore.build_messages("how do I enumerate smb?", hits)
    assert len(kept) == 2
    assert messages[0]["role"] == "system"
    assert "ONLY the provided notes context" in messages[0]["content"]
    user = messages[1]["content"]
    assert user.index("Notes context:") < user.index("Question: ")
    assert "[recon/smb.md — Enumerate shares]" in user


def test_sources_are_unique_and_ordered(index):
    hits = index.search(fake_vector("smb shares"), top_k=3)
    duplicated = hits + hits
    assert ragcore.sources(duplicated) == ragcore.sources(hits)
    assert ragcore.sources(hits)[0] == hits[0][1]["source"]


# --- server calls ----------------------------------------------------------

def test_embed_query_uses_the_search_query_prefix(wired, index):
    embed_server, _ = wired
    ragcore.embed_query("how do I enumerate smb?")
    assert embed_server.calls[-1]["input"].startswith("search_query: ")


def test_api_key_reads_and_strips(keyfile):
    assert ragcore.api_key(keyfile) == "testkey"


def test_api_key_missing_file_raises(tmp_path):
    with pytest.raises(ragcore.RagError, match="cannot read API key"):
        ragcore.api_key(str(tmp_path / "absent"))


def test_api_key_empty_file_raises(tmp_path):
    path = tmp_path / "blank"
    path.write_text("   \n")
    with pytest.raises(ragcore.RagError, match="is empty"):
        ragcore.api_key(str(path))


def test_chat_rejects_a_bad_key(wired):
    with pytest.raises(ragcore.RagError, match="401"):
        ragcore.chat([{"role": "user", "content": "hi"}], key="wrong")


def test_chat_unreachable_server_gives_a_readable_error():
    with pytest.raises(ragcore.RagError, match="cannot reach"):
        # Port 1 is never listening, and the message must not be a traceback.
        ragcore.chat([{"role": "user", "content": "hi"}],
                     url="http://127.0.0.1:1/v1/chat/completions", key="k")


def test_ask_sends_retrieved_notes_to_the_model(wired, index):
    _, chat_server = wired
    answer, hits = ragcore.ask(index, "how do I enumerate smb shares?")
    assert answer == "SAW_CONTEXT"
    assert hits[0][1]["source"] == "recon/smb.md"
    sent = chat_server.calls[-1]["messages"][-1]["content"]
    assert "smbclient -N -L //TARGET" in sent


def test_streaming_yields_the_same_answer(wired, index):
    stream, _ = ragcore.ask(index, "smb shares", stream=True)
    assert "".join(stream) == "SAW_CONTEXT"


# --- context budget --------------------------------------------------------

def test_fit_context_stops_at_the_budget(index):
    hits = index.search(fake_vector("smb shares"), top_k=3)
    kept, context = ragcore.fit_context(hits, budget=90)
    assert len(kept) < len(hits)
    assert len(context) <= 90


def test_fit_context_always_keeps_the_best_hit_even_if_oversized(index):
    hits = index.search(fake_vector("smb shares"), top_k=3)
    kept, context = ragcore.fit_context(hits, budget=10)
    assert len(kept) == 1
    assert kept[0] == hits[0]
    assert context.endswith("[...truncated]")


def test_fit_context_keeps_best_first(index):
    hits = index.search(fake_vector("smb shares"), top_k=3)
    kept, _ = ragcore.fit_context(hits, budget=10_000)
    assert [s for s, _ in kept] == sorted((s for s, _ in kept), reverse=True)


def test_build_messages_cites_only_what_was_sent(index):
    hits = index.search(fake_vector("smb shares"), top_k=3)
    messages, kept = ragcore.build_messages("q", hits, budget=90)
    user = messages[1]["content"]
    for _, doc in kept:
        assert doc["source"] in user
    dropped = [doc for _, doc in hits if (0, doc) not in [(0, d) for _, d in kept]]
    for doc in dropped:
        assert f"[{doc['source']} — {doc['heading']}]" not in user


def test_max_tokens_comes_from_config(wired, index):
    _, chat_server = wired
    ragcore.ask(index, "smb shares")
    assert chat_server.calls[-1]["max_tokens"] == ragcore.MAX_TOKENS
