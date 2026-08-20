#!/data/data/com.termux/files/usr/bin/env python3
"""Browser front end and OpenAI-compatible endpoint for the notes assistant.

Runs on the DEVICE. The chat server on :8081 answers from model weights alone;
everything here goes through retrieval first, so:

    :8081  raw model, no notes
    :8083  same model, your notes retrieved and pasted in first

    GET  /                      the chat page
    GET  /health                {"status","chunks","auth_required"} — always open
    POST /ask                   {"question": "..."} -> SSE token stream
    POST /v1/chat/completions   OpenAI-compatible, RAG applied automatically

Binding decides whether a token is demanded. On loopback there is nothing to
protect against -- only processes on the phone, and whatever the laptop
forwards over USB, can reach it -- so no key is asked for:

    adb forward tcp:8083 tcp:8083   # then http://localhost:8083

Bound to a routable address (--host 0.0.0.0) every request except /health must
carry the bearer token from ~/.config/llm-api-key. Be clear-eyed about what
that is worth: this endpoint answers *out of* the private notes corpus, and the
token travels in clear text over HTTP, so anyone able to watch traffic on the
same network can lift it and read the notes through it. See docs/SECURITY.md.

The index is loaded once at startup (a few seconds) instead of per question,
which is most of why this answers faster than the CLI.
"""
import argparse
import json
import os
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ragcore  # noqa: E402

MAX_BODY = 256 * 1024

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CPTS notes assistant</title>
<style>
:root{color-scheme:light dark;--bg:#faf9f7;--fg:#1c1b19;--mut:#6b6862;--line:#e0ddd6;
--card:#fff;--accent:#8a5a2b;--code:#f3f1ec}
@media (prefers-color-scheme:dark){:root{--bg:#16151a;--fg:#e9e7e2;--mut:#9a968e;
--line:#2c2a31;--card:#1e1d23;--accent:#d59b5f;--code:#232128}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 ui-sans-serif,system-ui,sans-serif}
header{padding:18px 20px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:16px;font-weight:600}
header p{margin:4px 0 0;color:var(--mut);font-size:13px}
main{max-width:820px;margin:0 auto;padding:20px}
#log{display:flex;flex-direction:column;gap:14px;margin-bottom:20px}
.msg{padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.q{border-left:3px solid var(--accent)}
.a{white-space:pre-wrap;word-wrap:break-word}
.a code,.a pre{background:var(--code);border-radius:4px}
.a pre{padding:10px;overflow-x:auto}
.a code{padding:1px 4px;font-size:13px}
.src{margin-top:10px;padding-top:10px;border-top:1px solid var(--line);
color:var(--mut);font-size:12px}
.src b{color:var(--fg);font-weight:600}
.src div{font-family:ui-monospace,monospace;margin-top:3px}
.meta{color:var(--mut);font-size:12px;margin-top:8px}
form{display:flex;gap:8px;position:sticky;bottom:0;background:var(--bg);padding:12px 0}
textarea{flex:1;resize:vertical;min-height:52px;padding:10px;border:1px solid var(--line);
border-radius:8px;background:var(--card);color:var(--fg);font:inherit}
button{padding:0 18px;border:0;border-radius:8px;background:var(--accent);color:#fff;
font:inherit;font-weight:600;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
.err{color:#c0392b}
#keybox{display:flex;gap:8px;align-items:center;margin-bottom:14px;padding:10px 12px;
border:1px solid var(--line);border-radius:8px;background:var(--card);font-size:13px}
#keybox label{color:var(--mut);white-space:nowrap}
#keybox input{flex:1;padding:6px 8px;border:1px solid var(--line);border-radius:6px;
background:var(--bg);color:var(--fg);font:inherit;font-family:ui-monospace,monospace}
#ks{color:var(--mut);white-space:nowrap}
</style></head><body>
<header><h1>CPTS notes assistant</h1>
<p>Answers from <span id="n">your</span> note chunks — retrieval first,
then the local model.</p></header>
<main>
<div id="log"></div>
<div id="keybox" hidden><label for="k">API key</label>
<input id="k" type="password" placeholder="bearer token from ~/.config/llm-api-key"
autocomplete="off"><span id="ks"></span></div>
<form id="f"><textarea id="q" placeholder="how do I enumerate SMB shares?"
autofocus></textarea><button id="b">Ask</button></form>
</main>
<script>
const log=document.getElementById('log'),f=document.getElementById('f'),
      q=document.getElementById('q'),b=document.getElementById('b');
const kb=document.getElementById('keybox'),ki=document.getElementById('k'),
      ks=document.getElementById('ks');
// Stored per browser only. It never leaves this device except as the bearer
// header on requests to this server.
let apiKey='';
try{apiKey=localStorage.getItem('ragKey')||''}catch(e){}
ki.value=apiKey;
ki.oninput=()=>{apiKey=ki.value.trim();
  try{localStorage.setItem('ragKey',apiKey)}catch(e){}
  ks.textContent=apiKey?'saved':''};
function authHeaders(){return apiKey?{'Authorization':'Bearer '+apiKey}:{}}
fetch('health').then(r=>r.json()).then(d=>{
  document.getElementById('n').textContent=d.chunks;
  if(d.auth_required){kb.hidden=false; if(!apiKey) ki.focus();}
});
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function render(s){return esc(s)
  .replace(/```([\\s\\S]*?)```/g,(m,c)=>'<pre><code>'+c.replace(/^\\w*\\n/,'')+'</code></pre>')
  .replace(/`([^`\\n]+)`/g,'<code>$1</code>')}
f.onsubmit=async e=>{
  e.preventDefault();
  const question=q.value.trim(); if(!question) return;
  q.value=''; b.disabled=true;
  const qd=document.createElement('div'); qd.className='msg q'; qd.textContent=question;
  const ad=document.createElement('div'); ad.className='msg';
  const body=document.createElement('div'); body.className='a'; ad.appendChild(body);
  log.append(qd,ad); ad.scrollIntoView({block:'end'});
  let text='', t0=Date.now();
  try{
    const res=await fetch('ask',{method:'POST',
      headers:{'Content-Type':'application/json',...authHeaders()},
      body:JSON.stringify({question})});
    if(res.status===401){kb.hidden=false; ki.focus();
      throw new Error('This server needs an API key. Paste it above and ask again.')}
    if(!res.ok) throw new Error(await res.text());
    const rd=res.body.getReader(), dec=new TextDecoder(); let buf='';
    for(;;){
      const {value,done}=await rd.read(); if(done) break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split('\\n\\n'); buf=parts.pop();
      for(const p of parts){
        const line=p.split('\\n').find(l=>l.startsWith('data:')); if(!line) continue;
        const ev=JSON.parse(line.slice(5));
        if(ev.token){text+=ev.token; body.innerHTML=render(text);
          ad.scrollIntoView({block:'end'})}
        if(ev.error){body.innerHTML+='<div class="err">'+esc(ev.error)+'</div>'}
        if(ev.sources){
          const s=document.createElement('div'); s.className='src';
          s.innerHTML='<b>sources</b>'+ev.sources.map(x=>'<div>'+esc(x)+'</div>').join('');
          ad.appendChild(s);
          const m=document.createElement('div'); m.className='meta';
          m.textContent=`${ev.chunks} chunks searched · retrieval ${ev.retrieve_ms}ms `
            +`· first token ${(ev.ttft_ms/1000).toFixed(1)}s · ${ev.tok_per_s} tok/s `
            +`· ${ev.prompt_chars} prompt chars · total ${((Date.now()-t0)/1000).toFixed(1)}s`;
          ad.appendChild(m);
        }
      }
    }
  }catch(err){body.innerHTML+='<div class="err">'+esc(String(err))+'</div>'}
  b.disabled=false; q.focus();
};
q.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();f.requestSubmit()}};
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "rag-web"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("empty request body")
        if length > MAX_BODY:
            raise ValueError(f"request body over {MAX_BODY} bytes")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _authorized(self):
        """No key needed when bound to loopback; required otherwise."""
        if not self.server.require_key:
            return True
        sent = self.headers.get("Authorization", "")
        return sent.startswith("Bearer ") and sent[7:].strip() == self.server.key

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/health":
            # auth_required lets the page know whether to ask for a key. Kept
            # open so a liveness probe needs no credential.
            self._send(200, {"status": "ok", "chunks": len(self.server.index),
                             "auth_required": self.server.require_key})
        elif path == "/v1/models":
            self._send(200, {"object": "list", "data": [
                {"id": "cpts-notes-rag", "object": "model", "owned_by": "local"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path not in ("/ask", "/v1/chat/completions"):
            self._send(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send(401, {"error": "missing or bad bearer token"})
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
            return
        try:
            if path == "/ask":
                self._handle_ask(payload)
            else:
                self._handle_openai(payload)
        except ragcore.RagError as exc:
            self._send(503, {"error": str(exc)})
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "internal error, see server log"})

    # -- browser stream ----------------------------------------------------
    def _handle_ask(self, payload):
        question = (payload.get("question") or "").strip()
        if not question:
            self._send(400, {"error": "no question"})
            return
        top_k = int(payload.get("top_k") or self.server.top_k)

        t0 = time.time()
        hits = ragcore.retrieve(self.server.index, question, top_k=top_k)
        retrieve_ms = int((time.time() - t0) * 1000)
        messages, hits = ragcore.build_messages(question, hits)
        prompt_chars = len(messages[1]["content"])

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def event(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        ttft_ms, tokens = None, 0
        try:
            for token in ragcore.chat(messages, stream=True, key=self.server.key):
                if ttft_ms is None:
                    ttft_ms = int((time.time() - t0) * 1000)
                tokens += 1
                event({"token": token})
        except ragcore.RagError as exc:
            event({"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return  # browser navigated away mid-answer
        total = time.time() - t0
        gen_s = total - (ttft_ms or 0) / 1000
        event({"sources": ragcore.sources(hits), "chunks": len(self.server.index),
               "retrieve_ms": retrieve_ms, "ttft_ms": ttft_ms,
               "prompt_chars": prompt_chars, "tokens": tokens,
               "tok_per_s": round(tokens / gen_s, 1) if gen_s > 0 else None,
               "scores": [round(s, 3) for s, _ in hits]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # -- OpenAI-compatible -------------------------------------------------
    def _handle_openai(self, payload):
        messages = payload.get("messages") or []
        question = next((m.get("content", "") for m in reversed(messages)
                         if m.get("role") == "user"), "").strip()
        if not question:
            self._send(400, {"error": "no user message"})
            return
        top_k = int(payload.get("top_k") or self.server.top_k)
        hits = ragcore.retrieve(self.server.index, question, top_k=top_k)
        rag_messages, hits = ragcore.build_messages(question, hits)
        src = ragcore.sources(hits)

        params = {k: payload[k] for k in ("temperature", "max_tokens", "top_p")
                  if k in payload}

        if not payload.get("stream"):
            answer = ragcore.chat(rag_messages, key=self.server.key, **params)
            self._send(200, {
                "id": f"chatcmpl-rag-{int(time.time()*1000)}",
                "object": "chat.completion", "created": int(time.time()),
                "model": "cpts-notes-rag",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": answer}}],
                "sources": src,
            })
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        created, cid = int(time.time()), f"chatcmpl-rag-{int(time.time()*1000)}"

        def chunk(delta, finish=None):
            body = {"id": cid, "object": "chat.completion.chunk", "created": created,
                    "model": "cpts-notes-rag",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(f"data: {json.dumps(body)}\n\n".encode())
            self.wfile.flush()

        try:
            for token in ragcore.chat(rag_messages, stream=True, key=self.server.key,
                                      **params):
                chunk({"content": token})
        except (BrokenPipeError, ConnectionResetError):
            return
        chunk({}, finish="stop")
        self.wfile.write(f"data: {json.dumps({'sources': src})}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def build_server(host, port, index, key, top_k):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.index = index
    httpd.key = key
    httpd.top_k = top_k
    # Loopback is already limited to processes on the phone (and whatever the
    # laptop forwards over USB), so no token is asked for there. Any other bind
    # address is reachable from the network and must present the API key.
    httpd.require_key = host not in ("127.0.0.1", "localhost", "::1")
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("RAG_WEB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("RAG_WEB_PORT", "8083")))
    ap.add_argument("--index", default=None, help="path to index.jsonl")
    ap.add_argument("--top-k", type=int, default=ragcore.TOP_K)
    args = ap.parse_args(argv)

    t0 = time.time()
    try:
        index = ragcore.Index.load(args.index)
        key = ragcore.api_key()
    except ragcore.RagError as exc:
        print(f"rag-web: {exc}", file=sys.stderr)
        return 1
    print(f"loaded {len(index)} chunks in {time.time()-t0:.1f}s", flush=True)

    httpd = build_server(args.host, args.port, index, key, args.top_k)
    if httpd.require_key:
        print(f"listening on {args.host}:{args.port} — bearer token REQUIRED "
              f"(not loopback)", flush=True)
    else:
        print(f"listening on http://{args.host}:{args.port} "
              f"(loopback only; adb forward tcp:{args.port} tcp:{args.port})",
              flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
