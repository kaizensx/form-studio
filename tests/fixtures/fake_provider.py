"""A stand-in for a model provider's HTTP API, for tests: answers GET /models and streams POST /chat/completions
(OpenAI's Chat Completions shape) or POST /messages (Anthropic's Messages shape) from a script. No model, no network.

    srv = FakeProvider(wire="openai", models=[{"id": "m1"}], script=[turn, turn, ...], key="sk-test")
    srv.url      -> "http://127.0.0.1:<port>/v1"
    srv.requests -> every request body it received

A turn is a dict: {"text": "...", "tools": [(name, args), ...], "thinking": "...", "usage": {...}, "status": 401,
"error": "..."}; turns are used in order, one per model request.

For detecting a provider added by URL (form/agents/custom.py): `prefix` is where the API lives ("/v1", "", "/api/v1")
and `strict=True` answers only there; `shape="gemini"` lists models the way Gemini's own API does, with an
OpenAI-compatible endpoint under <prefix>/openai; `ollama=True` also answers /api/tags and /api/show (a model's
"capabilities" key). An empty POST body is refused with 400, as real servers do, and uses no turn.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeProvider:
    def __init__(self, wire: str = "openai", models=None, script=None, key: str | None = None, delay: float = 0.0,
                 prefix: str = "/v1", strict: bool = False, shape: str | None = None, ollama: bool = False):
        self.wire, self.models, self.script, self.key, self.delay = wire, models or [], list(script or []), key, delay
        self.prefix, self.strict, self.shape, self.ollama = prefix, strict, shape, ollama
        self.gets: list[str] = []
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.hold = threading.Event()             # set() releases a turn that has "hold": True
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _auth_ok(self) -> bool:
                if not outer.key:
                    return True
                got = self.headers.get("x-api-key") or (self.headers.get("authorization") or "").removeprefix("Bearer ")
                return got == outer.key

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _list(self):
                ms = [{k: v for k, v in m.items() if not (outer.ollama and k == "capabilities")} for m in outer.models]
                if outer.wire == "anthropic":
                    return {"data": [dict(m, type="model") for m in ms], "has_more": False,
                            "first_id": ms[0]["id"] if ms else None, "last_id": ms[-1]["id"] if ms else None}
                return {"data": ms, "object": "list"}

            def do_GET(self):
                path = self.path.split("?")[0]
                outer.gets.append(path)
                if outer.ollama and path == "/api/tags":
                    return self._json(200, {"models": [{"name": m["id"], "model": m["id"], "digest": "0" * 12} for m in outer.models]})
                if outer.shape == "gemini" and path == outer.prefix + "/models":
                    if not self._auth_ok():
                        return self._json(401, {"error": {"message": "API key not valid"}})
                    return self._json(200, {"models": [{"name": "models/" + m["id"], "supportedGenerationMethods": ["generateContent"]}
                                                       for m in outer.models]})
                want = outer.prefix + ("/openai" if outer.shape == "gemini" else "") + "/models"
                if not path.endswith("/models") or (outer.strict or outer.shape) and path != want:
                    return self._json(404, {"error": {"message": "not found"}})
                if not self._auth_ok():
                    return self._json(401, {"error": {"message": "invalid api key"}})
                self._json(200, self._list())

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                path = self.path.split("?")[0]
                if outer.ollama and path == "/api/show":
                    m = next((m for m in outer.models if m["id"] == body.get("model")), None)
                    return self._json(200 if m else 404, {"capabilities": (m or {}).get("capabilities", ["completion"])})
                if body == {}:                              # how detection checks that the chat endpoint exists
                    if outer.strict and not path.startswith(outer.prefix + "/"):
                        return self._json(404, {"error": {"message": "not found"}})
                    return self._json(400, {"error": {"message": "messages: field required"}})
                outer.requests.append(body)
                outer.headers.append(dict(self.headers))
                if not self._auth_ok():
                    return self._json(401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}})
                turn = outer.script.pop(0) if outer.script else {"text": "(script ended)"}
                if turn.get("status"):
                    return self._json(turn["status"], {"error": {"message": turn.get("error", "failed")}})
                if not body.get("stream"):                  # one JSON answer (a provider test asks for that)
                    calls = turn.get("tools", [])
                    if outer.wire == "anthropic":
                        content = ([{"type": "text", "text": turn["text"]}] if turn.get("text") else []) + [
                            {"type": "tool_use", "id": f"toolu_{j}", "name": n, "input": a} for j, (n, a) in enumerate(calls)]
                        return self._json(200, {"type": "message", "role": "assistant", "content": content,
                                                "stop_reason": "tool_use" if calls else "end_turn"})
                    msg = {"role": "assistant", "content": turn.get("text") or None}
                    if calls:
                        msg["tool_calls"] = [{"id": f"call_{j}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                                             for j, (n, a) in enumerate(calls)]
                    return self._json(200, {"choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if calls else "stop"}]})
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                try:
                    if outer.wire == "anthropic":
                        self._anthropic(turn)
                    else:
                        self._openai(turn, body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _sse(self, obj, event=None):
                s = (f"event: {event}\n" if event else "") + "data: " + (obj if isinstance(obj, str) else json.dumps(obj)) + "\n\n"
                self.wfile.write(s.encode())
                self.wfile.flush()

            def _openai(self, turn, body):
                text = turn.get("text", "")
                for i in range(0, len(text), 7):
                    self._sse({"choices": [{"index": 0, "delta": {"content": text[i:i + 7]}}]})
                if turn.get("hold"):
                    outer.hold.wait(30)
                for j, (name, args) in enumerate(turn.get("tools", [])):
                    raw = json.dumps(args)
                    self._sse({"choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": j, "id": f"call_{len(outer.requests)}_{j}", "type": "function",
                         "function": {"name": name, "arguments": raw[:5]}, **turn.get("extra", {})}]}}]})
                    self._sse({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": j, "function": {"arguments": raw[5:]}}]}}]})
                fin = "tool_calls" if turn.get("tools") else "stop"
                self._sse({"choices": [{"index": 0, "delta": {}, "finish_reason": fin}]})
                if turn.get("usage") or (body.get("stream_options") or {}).get("include_usage"):
                    self._sse({"choices": [], "usage": turn.get("usage") or {"prompt_tokens": 10, "completion_tokens": 5}})
                self._sse("[DONE]")

            def _anthropic(self, turn):
                self._sse({"type": "message_start", "message": {"model": "fake", "usage": {"input_tokens": 100,
                           "cache_read_input_tokens": 40, "output_tokens": 1}}}, "message_start")
                idx = 0
                if turn.get("thinking"):
                    self._sse({"type": "content_block_start", "index": idx, "content_block": {"type": "thinking", "thinking": ""}})
                    self._sse({"type": "content_block_delta", "index": idx, "delta": {"type": "thinking_delta", "thinking": turn["thinking"]}})
                    self._sse({"type": "content_block_delta", "index": idx, "delta": {"type": "signature_delta", "signature": "sig-" + str(len(outer.requests))}})
                    self._sse({"type": "content_block_stop", "index": idx})
                    idx += 1
                if turn.get("text"):
                    self._sse({"type": "content_block_start", "index": idx, "content_block": {"type": "text", "text": ""}})
                    for i in range(0, len(turn["text"]), 6):
                        self._sse({"type": "content_block_delta", "index": idx, "delta": {"type": "text_delta", "text": turn["text"][i:i + 6]}})
                    self._sse({"type": "content_block_stop", "index": idx})
                    idx += 1
                for name, args in turn.get("tools", []):
                    raw = json.dumps(args)
                    self._sse({"type": "content_block_start", "index": idx, "content_block": {"type": "tool_use", "id": f"toolu_{len(outer.requests)}_{idx}",
                                                                                             "name": name, "input": {}}})
                    for i in range(0, len(raw), 4):
                        self._sse({"type": "content_block_delta", "index": idx, "delta": {"type": "input_json_delta", "partial_json": raw[i:i + 4]}})
                    self._sse({"type": "content_block_stop", "index": idx})
                    idx += 1
                stop = turn.get("stop") or ("tool_use" if turn.get("tools") else "end_turn")
                self._sse({"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 25}})
                self._sse({"type": "message_stop"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.root = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.url = self.root + prefix

    def close(self):
        self.hold.set()
        self.server.shutdown()
        self.server.server_close()
