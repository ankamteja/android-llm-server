"""The HTTP surface of rag-web.py: browser page, SSE stream, OpenAI endpoint, auth."""
import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

import ragcore
from fakes import TEST_KEY

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_rag_web():
    """rag-web.py has a dash in its name, so it needs a manual import."""
    path = os.path.join(REPO, "rag", "bin", "rag-web.py")
    spec = importlib.util.spec_from_file_location("rag_web", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rag_web = _load_rag_web()


@pytest.fixture
def web(wired, index):
    """rag-web bound to an ephemeral loopback port, wired to the fake models."""
    httpd = rag_web.build_server("127.0.0.1", 0, index, TEST_KEY, ragcore.TOP_K)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def get(url, **kw):
    return urllib.request.urlopen(url, timeout=15, **kw)


def post(url, obj, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    return urllib.request.urlopen(req, timeout=30)


def sse_events(resp):
    """Parse an SSE body into the list of decoded JSON events."""
    events = []
    for line in resp.read().decode().splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        events.append(json.loads(payload))
    return events


# --- static surface --------------------------------------------------------

def test_index_page_is_served(web):
    resp = get(web.url + "/")
    body = resp.read().decode()
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("text/html")
    assert "<title>CPTS notes assistant</title>" in body


def test_health_reports_chunk_count(web):
    body = json.load(get(web.url + "/health"))
    assert body["status"] == "ok"
    assert body["chunks"] == 3


def test_health_says_whether_a_key_is_needed(web, monkeypatch):
    assert json.load(get(web.url + "/health"))["auth_required"] is False
    monkeypatch.setattr(web, "require_key", True)
    assert json.load(get(web.url + "/health"))["auth_required"] is True


def test_page_asks_for_a_key_and_sends_it(web):
    """The page must carry the token, or a LAN-bound server is unusable."""
    body = get(web.url + "/").read().decode()
    assert "auth_required" in body
    assert "'Authorization':'Bearer '+apiKey" in body
    assert "res.status===401" in body


def test_models_endpoint_names_the_rag_model(web):
    body = json.load(get(web.url + "/v1/models"))
    assert body["data"][0]["id"] == "cpts-notes-rag"


def test_unknown_path_is_404(web):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(web.url + "/nope")
    assert exc.value.code == 404


# --- /ask ------------------------------------------------------------------

def test_ask_streams_tokens_then_sources(web):
    events = sse_events(post(web.url + "/ask",
                             {"question": "how do I enumerate smb shares?"}))
    answer = "".join(e["token"] for e in events if "token" in e)
    assert answer == "SAW_CONTEXT"
    final = events[-1]
    assert final["sources"][0] == "recon/smb.md"
    assert final["chunks"] == 3


def test_ask_reports_timing_telemetry(web):
    final = sse_events(post(web.url + "/ask", {"question": "smb shares"}))[-1]
    for field in ("retrieve_ms", "ttft_ms", "prompt_chars", "tokens", "scores"):
        assert field in final, field
    assert final["ttft_ms"] >= final["retrieve_ms"]
    assert final["prompt_chars"] > 0


def test_ask_actually_retrieves_before_asking(web, wired):
    _, chat_server = wired
    post(web.url + "/ask", {"question": "how do I enumerate smb shares?"}).read()
    sent = chat_server.calls[-1]["messages"][-1]["content"]
    assert "Notes context:" in sent
    assert "smbclient -N -L //TARGET" in sent


def test_ask_rejects_an_empty_question(web):
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(web.url + "/ask", {"question": "   "})
    assert exc.value.code == 400


def test_ask_rejects_malformed_json(web):
    req = urllib.request.Request(web.url + "/ask", data=b"{not json",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=15)
    assert exc.value.code == 400


def test_ask_honours_top_k(web, wired):
    embed_server, chat_server = wired
    post(web.url + "/ask", {"question": "smb", "top_k": 1}).read()
    sent = chat_server.calls[-1]["messages"][-1]["content"]
    assert sent.count("[recon/") + sent.count("[creds/") == 1


# --- OpenAI-compatible endpoint -------------------------------------------

def test_openai_endpoint_applies_rag(web, wired):
    _, chat_server = wired
    body = json.load(post(web.url + "/v1/chat/completions",
                          {"messages": [{"role": "user",
                                         "content": "how do I enumerate smb shares?"}]}))
    assert body["choices"][0]["message"]["content"] == "SAW_CONTEXT"
    assert body["model"] == "cpts-notes-rag"
    assert body["sources"][0] == "recon/smb.md"


def test_openai_endpoint_streams(web):
    resp = post(web.url + "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "smb shares"}],
                 "stream": True})
    events = sse_events(resp)
    answer = "".join(e["choices"][0]["delta"].get("content", "")
                     for e in events if e.get("choices"))
    assert answer == "SAW_CONTEXT"
    assert events[-1]["sources"][0] == "recon/smb.md"


def test_openai_endpoint_uses_the_last_user_message(web, wired):
    _, chat_server = wired
    post(web.url + "/v1/chat/completions", {"messages": [
        {"role": "user", "content": "ignore this one"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "how do I enumerate smb shares?"},
    ]}).read()
    assert "Question: how do I enumerate smb shares?" in \
        chat_server.calls[-1]["messages"][-1]["content"]


def test_openai_endpoint_forwards_sampling_params(web, wired):
    _, chat_server = wired
    post(web.url + "/v1/chat/completions",
         {"messages": [{"role": "user", "content": "smb"}],
          "temperature": 0.9, "max_tokens": 42}).read()
    assert chat_server.calls[-1]["temperature"] == 0.9
    assert chat_server.calls[-1]["max_tokens"] == 42


def test_openai_endpoint_rejects_no_user_message(web):
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(web.url + "/v1/chat/completions",
             {"messages": [{"role": "system", "content": "hi"}]})
    assert exc.value.code == 400


# --- auth ------------------------------------------------------------------

def test_loopback_bind_needs_no_token(index):
    httpd = rag_web.build_server("127.0.0.1", 0, index, TEST_KEY, 5)
    try:
        assert httpd.require_key is False
    finally:
        httpd.server_close()


def test_non_loopback_bind_requires_a_token(index):
    httpd = rag_web.build_server("0.0.0.0", 0, index, TEST_KEY, 5)
    try:
        assert httpd.require_key is True
    finally:
        httpd.server_close()


def test_token_is_enforced_when_required(web, monkeypatch):
    monkeypatch.setattr(web, "require_key", True)
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(web.url + "/ask", {"question": "smb"})
    assert exc.value.code == 401

    events = sse_events(post(web.url + "/ask", {"question": "smb"},
                             headers={"Authorization": f"Bearer {TEST_KEY}"}))
    assert any("token" in e for e in events)


def test_health_stays_open_when_a_token_is_required(web, monkeypatch):
    monkeypatch.setattr(web, "require_key", True)
    assert json.load(get(web.url + "/health"))["status"] == "ok"


def test_oversized_body_is_rejected(web):
    big = {"question": "x" * (rag_web.MAX_BODY + 10)}
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(web.url + "/ask", big)
    assert exc.value.code == 400


# --- failure handling ------------------------------------------------------

def test_chat_server_down_is_reported_in_the_stream(web, monkeypatch):
    monkeypatch.setattr(ragcore, "CHAT_URL", "http://127.0.0.1:1/v1/chat/completions")
    events = sse_events(post(web.url + "/ask", {"question": "smb"}))
    assert any("cannot reach" in e.get("error", "") for e in events)


def test_embed_server_down_returns_503(web, monkeypatch):
    monkeypatch.setattr(ragcore, "EMBED_URL", "http://127.0.0.1:1/v1/embeddings")
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(web.url + "/ask", {"question": "smb"})
    assert exc.value.code == 503
