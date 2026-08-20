"""Shared fixtures. Everything here runs on a laptop or in CI — no phone, no GGUF."""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "rag", "bin"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import ChatHandler, EmbedHandler, FakeServer, TEST_KEY, fake_vector  # noqa: E402

import ragcore  # noqa: E402


@pytest.fixture
def embed_server():
    with FakeServer(EmbedHandler) as srv:
        yield srv


@pytest.fixture
def chat_server():
    with FakeServer(ChatHandler) as srv:
        yield srv


@pytest.fixture
def keyfile(tmp_path):
    path = tmp_path / "llm-api-key"
    path.write_text(TEST_KEY + "\n")
    path.chmod(0o600)
    return str(path)


CORPUS_CHUNKS = [
    {"source": "recon/smb.md", "breadcrumb": "recon > smb",
     "heading": "Enumerate shares",
     "text": "smbclient -N -L //TARGET lists shares anonymously."},
    {"source": "recon/snmp.md", "breadcrumb": "recon > snmp",
     "heading": "Community strings",
     "text": "onesixtyone TARGET wordlist brute forces snmp community strings."},
    {"source": "creds/hashcat.md", "breadcrumb": "creds > hashcat",
     "heading": "NTLMv2",
     "text": "hashcat -m 5600 hashes rockyou cracks ntlmv2 responses."},
]


@pytest.fixture
def index_file(tmp_path):
    """A tiny index.jsonl embedded with the deterministic fake embedder."""
    path = tmp_path / "index.jsonl"
    with path.open("w") as fh:
        for chunk in CORPUS_CHUNKS:
            record = dict(chunk)
            record["vector"] = fake_vector(ragcore.document_text(chunk))
            fh.write(json.dumps(record) + "\n")
    return str(path)


@pytest.fixture
def index(index_file):
    return ragcore.Index.load(index_file)


@pytest.fixture
def wired(monkeypatch, embed_server, chat_server, keyfile):
    """Point ragcore's module-level defaults at the fake servers."""
    monkeypatch.setattr(ragcore, "EMBED_URL", f"{embed_server.url}/v1/embeddings")
    monkeypatch.setattr(ragcore, "CHAT_URL", f"{chat_server.url}/v1/chat/completions")
    monkeypatch.setattr(ragcore, "KEYFILE", keyfile)
    return embed_server, chat_server
