"""Stand-in embedding and chat servers.

The real ones are llama-server processes holding multi-gigabyte GGUF weights on
a phone. These speak the same HTTP shapes in a few hundred lines so the whole
RAG path can be tested on a laptop, in CI, with no model and no device.
"""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 32
TEST_KEY = "testkey"


def fake_vector(text):
    """Deterministic pseudo-embedding: same text always gives the same vector,
    and texts sharing words land closer together than unrelated ones."""
    vec = [0.0] * DIM
    words = text.lower().replace("\n", " ").split()
    for word in words:
        digest = hashlib.sha256(word.encode()).digest()
        for i in range(DIM):
            vec[i] += (digest[i % len(digest)] - 128) / 128.0
    if not words:
        vec[0] = 1.0
    return vec


class _Base(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class EmbedHandler(_Base):
    def do_POST(self):
        body = self._json_body()
        self.server.calls.append(body)
        self._send(200, {"data": [{"embedding": fake_vector(body.get("input", ""))}]})


class ChatHandler(_Base):
    """Echoes back whether it was given retrieved notes, so a test can tell a
    RAG answer apart from a bare-model answer."""

    def do_POST(self):
        if self.headers.get("Authorization") != f"Bearer {TEST_KEY}":
            self._send(401, {"error": "unauthorized"})
            return
        body = self._json_body()
        self.server.calls.append(body)
        user = body["messages"][-1]["content"]
        answer = "SAW_CONTEXT" if "Notes context:" in user else "NO_CONTEXT"

        if not body.get("stream"):
            self._send(200, {"choices": [
                {"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": answer}}]})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in (answer[:4], answer[4:]):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class FakeServer:
    """Context manager running one handler on an ephemeral port."""

    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.calls = []
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def calls(self):
        return self.httpd.calls

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
