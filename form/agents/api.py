"""API agents: Form Studio runs the agent loop itself against a model provider's API, with Form Studio's MCP tools.

No CLI is needed. For each message the adapter starts Form Studio's own MCP server (the same `form-mcp --no-bench`
process a CLI agent gets, with the same environment, so ask_user and the activity log work the same), lists its
tools, offers them to the model with the provider's tool-calling format, runs each call the model makes, feeds the
results back (render images included when the model takes images), and repeats until the model answers without a
tool call. It speaks FORM's event vocabulary (see base.py), so the chat, the conversation store and the interface
cannot tell it from a CLI agent.

The conversation's API history is kept next to its events (<conversation>/.api/<session>.json), so the next message
continues with full context; a different agent starts from a transcript, as with the CLIs.
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from pathlib import Path

from . import providers as prov
from .base import LIVE_TEXT_MAX, Adapter, Run, short
from .mcp_client import MCPClient, MCPError
from .models import Recent, pretty

MAX_ROUNDS = 80                    # model turns per message; each may call several tools
MAX_HISTORY = 12_000_000           # bytes of saved API history; beyond that the next message starts from a transcript
ANTHROPIC_MAX_TOKENS = 32000
_NO_IMAGES: set = set()            # (provider, model) that refused an image this session
_NO_STREAM_USAGE: set = set()
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


class SessionGone(Exception):
    """The saved API history for this session is missing or unusable: send again with a transcript."""


class Control:
    """Stands in for a CLI process in the chat: terminate() stops the run (closes the stream, ends the tool server)."""

    def __init__(self):
        self.stopped = False
        self.returncode: int | None = None
        self.holder: dict = {}
        self.mcp: MCPClient | None = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped = True
        r = self.holder.get("resp")
        if r is not None:
            self.holder["closed"] = True
            try:
                r.close()
            except Exception:
                pass
        if self.mcp is not None and self.mcp.proc.poll() is None:
            try:
                self.mcp.proc.terminate()
            except OSError:
                pass

    def wait(self, timeout=None):
        return self.returncode


# ---- tools in each provider's format --------------------------------------------------------------------------------

def simplify(schema, strict: bool):
    """A tool's JSON schema as every provider accepts it. strict: also without title/default and anyOf-with-null,
    which Gemini's endpoint and some local servers refuse."""
    if isinstance(schema, list):
        return [simplify(x, strict) for x in schema]
    if not isinstance(schema, dict):
        return schema
    s = {k: simplify(v, strict) for k, v in schema.items() if not (strict and k in ("title", "default", "examples"))}
    if strict:
        any_of = s.get("anyOf")
        if isinstance(any_of, list):
            rest = [x for x in any_of if not (isinstance(x, dict) and x.get("type") == "null")]
            if len(rest) == 1 and isinstance(rest[0], dict):
                s.pop("anyOf")                       # optional already means it may be left out
                s = {**rest[0], **s}
    return s


def tool_specs(p: prov.Provider, tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        params = simplify(t.get("inputSchema") or {"type": "object", "properties": {}}, p.simple_schema)
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        if p.wire == "anthropic":
            out.append({"name": t["name"], "description": (t.get("description") or "")[:4000], "input_schema": params,
                        "eager_input_streaming": True})
        else:
            out.append({"type": "function", "function": {"name": t["name"], "description": (t.get("description") or "")[:4000],
                                                         "parameters": params}})
    return out


def _mcp_parts(res: dict) -> tuple[str, list[dict], bool]:
    """(text, images as {mime, data}, is_error) from an MCP tools/call result."""
    texts, imgs = [], []
    for c in res.get("content") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            texts.append(str(c.get("text", "")))
        elif c.get("type") == "image" and c.get("data"):
            imgs.append({"mime": c.get("mimeType") or "image/png", "data": c["data"]})
    if not texts and res.get("structuredContent") is not None:
        texts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
    return "\n".join(texts), imgs, bool(res.get("isError"))


# ---- the adapter --------------------------------------------------------------------------------------------------

class ApiAdapter(Adapter):
    inline = True
    kind = "api"

    def __init__(self, p: prov.Provider):
        self.p = p
        self.id, self.label, self.cli = p.id, p.label, ""
        self.install_hint = p.hint
        self.verified = p.verified
        self.images = True
        self.cost = p.id == "openrouter"           # the only provider here whose API reports a price
        self._cfg: dict = {}

    # -- discovery -----------------------------------------------------------
    def executable(self, cfg: dict) -> str | None:
        got = prov.info(self.p, cfg)
        return got["base"] if got.get("available") else None

    def _models(self, cfg: dict) -> list[dict]:
        self._cfg = cfg
        return prov.info(self.p, cfg).get("models") or []

    def default_model(self, cfg: dict) -> str | None:
        """The model "Default" means for this provider, or None (the person picks one; nothing is chosen for them):
        [chat] <id>_model; else the model last used with it in Form Studio; else, for a local server, what it has
        loaded; else the only model the provider lists."""
        return self._default(cfg)[0]

    def _default(self, cfg: dict) -> tuple[str | None, str]:
        own = (cfg.get("chat", {}) or {}).get(f"{self.id}_model")
        if own:
            return str(own), f"set as [chat] {self.id}_model"
        ms = self._models(cfg)
        ids = {m["id"] for m in ms}
        data = (cfg.get("data") or {}).get("dir") if isinstance(cfg, dict) else None
        if data:
            last = next((m for m in Recent(Path(data)).list(self.id) if m in ids), None)
            if last:
                return last, f"last used with {self.label} in Form Studio"
        if self.p.local and not self.p.custom and ms:
            return ms[0]["id"], f"loaded in {self.label}"
        if len(ms) == 1:
            return ms[0]["id"], f"the only model {self.label} lists"
        return None, ""

    def model_label(self, model_id):
        m = self.model_info(self._cfg, model_id) if model_id else {}
        return m.get("label") or (model_id or "" if self.p.local else pretty(model_id))

    def status(self, cfg: dict) -> dict:
        got = prov.info(self.p, cfg)
        key, where = prov.credentials(self.p)
        out = {"id": self.id, "label": self.label, "available": bool(got.get("available")), "cli": got.get("base"),
               "why": got.get("why"), "images": True, "reports_cost": self.cost, "verified": self.verified,
               "kind": "api", "local": self.p.local, "docs": self.p.docs, "key": self.p.key, "custom": self.p.custom}
        if self.p.custom:
            out["signin"] = {"signed_in": True if got.get("available") else (False if got.get("error") else None),
                             "how": ("Key stored by Form Studio" if key else "No key") + " · " + got.get("base", "")}
        elif self.p.local:
            out["signin"] = {"signed_in": True if got.get("available") else None,
                             "how": f"Local server at {got.get('base')}" if got.get("available") else self.p.hint}
        else:
            out["signin"] = {"signed_in": bool(key) and not got.get("error"),
                             "how": ("Key from " + where[4:] if where.startswith("env:") else "Key stored by Form Studio")
                             if key else "No key yet."}
        if not out["available"]:
            out["models"], out["efforts"] = [], []
            return out
        rows = [self._row(m) for m in _ordered(got["models"])]
        dflt, why = self._default(cfg)
        models = []
        if dflt:
            dl = next((r["label"] for r in rows if r["id"] == dflt), None) or (dflt if self.p.local else pretty(dflt))
            models.append({"id": "default", "label": "Default · " + dl, "resolved": dflt, "resolved_label": dl,
                           "note": f"{dflt} · {why}"})
        out["models"], out["efforts"] = models + rows, []
        out["pick"] = not dflt                     # no Default: the picker asks for a model before the first message
        out["count"] = len(rows)
        return out

    def _row(self, m: dict) -> dict:
        label = m.get("label") or (m["id"] if self.p.local else pretty(m["id"]))
        bits = [m["id"]]
        if m.get("free"):
            bits.append("free")
        if m.get("images") is False:
            bits.append("text only")
        if m.get("tools") is False:
            bits.append("no tool calls")
        row = {"id": m["id"], "label": label, "note": " · ".join(bits)}
        for k in ("vendor", "free", "images", "tools", "context"):
            if m.get(k) is not None:
                row[k] = m[k]
        if m.get("vendor"):
            row["vendor_label"] = m.get("vendor_label") or _vendor_name(m["vendor"])
        if m.get("efforts"):
            row["efforts"] = m["efforts"]
        return row

    def model_info(self, cfg: dict, model: str) -> dict:
        return next((m for m in self._models(cfg) if m["id"] == model), {})

    def resume_failed(self, stderr, events):
        return False

    # -- one run -------------------------------------------------------------
    def execute(self, run: Run, cfg: dict, emit, control: Control) -> dict | None:
        """Run one message. emit(list_of_events) delivers FORM events as they happen. Returns None, or the failure
        as {"message", "hint"} (an "end" event has been emitted either way, unless the run never started)."""
        p = self.p
        key, _ = prov.credentials(p)
        if p.key and not key:
            return {"message": f"No {p.label} key is set.", "hint": "Add one in Settings › Agents."}
        base = prov.base_url(p, cfg)
        model = run.model if run.model and run.model != "default" else self.default_model(cfg)
        if not model:
            n = len(self._models(cfg))
            if n:
                return {"message": f"Pick a model for {p.label} first.",
                        "hint": f"Open the model menu: {p.label} lists {n} models. The one you pick becomes its Default."}
            return {"message": f"{p.label} lists no model to use.", "hint": p.hint}
        minfo = self.model_info(cfg, model)
        hist_dir = Path(run.cwd) / ".api"
        sid = run.session
        msgs: list = []
        if sid:
            msgs = self._load(hist_dir, sid)           # raises SessionGone
        else:
            sid = uuid.uuid4().hex[:16]
        t0 = time.time()
        cost, usage, rounds, err = None, {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}, 0, None
        mcp = MCPClient(run.mcp.get("command", ""), run.mcp.get("args", []), run.mcp.get("env", {}), cwd=str(run.cwd))
        control.mcp = mcp
        try:
            try:
                mcp.initialize()
                tools = mcp.tools()
            except MCPError as e:
                return {"message": f"Form Studio's tools could not start: {e}", "hint": ""}
            specs = tool_specs(p, tools)
            system = run.system + ("\n\n" + mcp.instructions if mcp.instructions else "")
            emit([{"t": "session", "session": sid}, {"t": "start", "model": model, "session": sid}])
            images_ok = (p.id, model) not in _NO_IMAGES and minfo.get("images") is not False
            msgs.append(self._user(run, images_ok))
            checkpoint = len(msgs) - 1               # the user turn is kept only once something answers it
            while rounds < MAX_ROUNDS and not control.stopped:
                rounds += 1
                step = self._step(p, base, key, model, system, specs, msgs, run, control, emit, minfo)
                for k in usage:
                    usage[k] += step["usage"].get(k, 0)
                if step.get("cost") is not None:
                    cost = (cost or 0.0) + step["cost"]
                if step.get("error"):
                    err = step["error"]
                    break
                msgs.append(step["message"])
                if step["text"].strip():
                    emit([{"t": "text", "text": step["text"]}])
                calls = step["calls"]
                if not calls:
                    checkpoint = len(msgs)
                    if step.get("stop") == "refusal":
                        err = {"message": f"{p.label} declined to continue this request (its safety system stopped the reply).",
                               "hint": "Rephrase the request, or try another model."}
                    elif step.get("stop") in ("max_tokens", "length"):
                        err = {"message": "The reply hit the model's output limit and was cut off.",
                               "hint": "Ask it to continue, or to answer in smaller steps."}
                    break
                results = []
                for c in calls:
                    if control.stopped:
                        break
                    emit([{"t": "tool", "id": c["id"], "name": c["name"], "input": short(c["args"])},
                          {"t": "live", "live": {"kind": "tool", "name": c["name"], "chars": 0, "text": ""}}])
                    if c.get("bad"):
                        res = {"content": [{"type": "text", "text": "The tool arguments were not valid JSON: " + c["bad"]}], "isError": True}
                    else:
                        res = mcp.call(c["name"], c["args"], timeout=run.tool_timeout_s)
                    text, imgs, is_err = _mcp_parts(res)
                    emit([{"t": "result", "id": c["id"], "ok": not is_err, "image": bool(imgs), "text": text[:300], "full": text},
                          {"t": "live", "live": None}])
                    results.append((c, text, imgs, is_err))
                if control.stopped:
                    break
                msgs += self._results(p, results, images_ok and (p.id, model) not in _NO_IMAGES)
                checkpoint = len(msgs)
                if cost is not None and run.budget_usd and cost >= run.budget_usd:
                    err = {"message": f"Stopped at the per-message budget of ${run.budget_usd:.2f}.",
                           "hint": "Raise [chat] budget_usd_per_message in Settings, or continue in a new message."}
                    break
            else:
                if rounds >= MAX_ROUNDS and not control.stopped:
                    err = {"message": f"Stopped after {MAX_ROUNDS} model turns without a final answer.",
                           "hint": "Continue in a new message, or narrow the request."}
            self._save(hist_dir, sid, model, msgs[:checkpoint])
            emit([{"t": "end", "cost_usd": round(cost, 6) if cost is not None else None, "turns": rounds, "session": sid,
                   "error": None, "model": model,
                   "usage": {k: v for k, v in usage.items() if v}, "seconds": round(time.time() - t0, 1)}])
            return err
        finally:
            mcp.close()
            control.returncode = 0 if err is None else 1

    # -- history -------------------------------------------------------------
    def _load(self, d: Path, sid: str) -> list:
        if not re.fullmatch(r"[0-9a-f]{16}", str(sid)):
            raise SessionGone()
        f = d / f"{sid}.json"
        try:
            if f.stat().st_size > MAX_HISTORY:
                raise SessionGone()
            h = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SessionGone()
        if h.get("wire") != self.p.wire or not isinstance(h.get("messages"), list):
            raise SessionGone()
        return h["messages"]

    def _save(self, d: Path, sid: str, model: str, msgs: list) -> None:
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / f"{sid}.json.tmp"
            tmp.write_text(json.dumps({"wire": self.p.wire, "provider": self.p.id, "model": model, "messages": msgs},
                                      ensure_ascii=False), encoding="utf-8")
            tmp.replace(d / f"{sid}.json")
        except OSError:
            pass

    # -- messages in the provider's shape -----------------------------------
    def _user(self, run: Run, images_ok: bool) -> dict:
        imgs = []
        if images_ok:
            for f in run.images:
                f = Path(f)
                mime = _MIME.get(f.suffix.lower())
                if mime:
                    try:
                        imgs.append({"mime": mime, "data": base64.b64encode(f.read_bytes()).decode("ascii")})
                    except OSError:
                        pass
        if self.p.wire == "anthropic":
            content = [{"type": "image", "source": {"type": "base64", "media_type": i["mime"], "data": i["data"]}} for i in imgs]
            return {"role": "user", "content": content + [{"type": "text", "text": run.message}]}
        if not imgs:
            return {"role": "user", "content": run.message}
        return {"role": "user", "content": [{"type": "text", "text": run.message}] + [
            {"type": "image_url", "image_url": {"url": f"data:{i['mime']};base64,{i['data']}"}} for i in imgs]}

    def _results(self, p: prov.Provider, results: list, images_ok: bool) -> list:
        if p.wire == "anthropic":
            blocks = []
            for c, text, imgs, is_err in results:
                content = [{"type": "text", "text": text or ("(no output)" if not imgs else "")}]
                if imgs and images_ok:
                    content += [{"type": "image", "source": {"type": "base64", "media_type": i["mime"], "data": i["data"]}} for i in imgs]
                elif imgs:
                    content[0]["text"] += "\n(The tool also returned an image, which this model cannot take.)"
                content = [x for x in content if x.get("type") != "text" or x["text"]]
                blocks.append({"type": "tool_result", "tool_use_id": c["id"], "content": content or [{"type": "text", "text": "(no output)"}],
                               **({"is_error": True} if is_err else {})})
            return [{"role": "user", "content": blocks}]
        out, pics = [], []
        for c, text, imgs, is_err in results:
            note = ""
            if imgs:
                note = "\n(The image this tool returned follows in the next message.)" if images_ok else \
                       "\n(The tool also returned an image, which this model cannot take.)"
                if images_ok:
                    pics += imgs
            out.append({"role": "tool", "tool_call_id": c["id"], "content": ((("Error: " if is_err else "") + (text or "(no output)")) + note)})
        if pics:
            out.append({"role": "user", "content": [{"type": "text", "text": "Images returned by the tool calls above:"}] + [
                {"type": "image_url", "image_url": {"url": f"data:{i['mime']};base64,{i['data']}"}} for i in pics]})
        return out

    # -- one model turn ------------------------------------------------------
    def _step(self, p, base, key, model, system, specs, msgs, run, control, emit, minfo) -> dict:
        attempt, strip_images, no_usage = 0, False, (p.id, model) in _NO_STREAM_USAGE
        while True:
            attempt += 1
            send = _without_images(msgs) if strip_images else msgs
            if p.wire == "anthropic":
                mt = min(minfo.get("max_tokens") or ANTHROPIC_MAX_TOKENS, ANTHROPIC_MAX_TOKENS)
                body = {"model": model, "max_tokens": mt, "system": system, "messages": send, "tools": specs, "stream": True,
                        "cache_control": {"type": "ephemeral"}}
                if run.effort and run.effort in (minfo.get("efforts") or []):
                    body["output_config"] = {"effort": run.effort}
                url, parse = base + "/messages", self._anthropic
            else:
                sysmsg = {"role": "system", "content": system}
                body = {"model": model, "messages": [sysmsg] + send, "tools": specs, "stream": True}
                if p.stream_usage and not no_usage:
                    body["stream_options"] = {"include_usage": True}
                if p.reasoning_param == "openrouter":
                    body["usage"] = {"include": True}
                    if run.effort and run.effort in (minfo.get("efforts") or []):
                        body["reasoning"] = {"effort": run.effort}
                url, parse = base + "/chat/completions", self._openai
            streamed = {"any": False}
            try:
                return parse(prov.stream(p, url, key, body, holder=control.holder), control, emit, streamed)
            except prov.ProviderError as e:
                msg = str(e)
                if control.stopped:
                    return {"error": {"message": "Stopped.", "hint": ""}, "usage": {}}
                if e.status == 400 and not strip_images and re.search(r"image|vision|multimodal|content type", msg, re.I) \
                        and _has_images(msgs):
                    _NO_IMAGES.add((p.id, model))
                    strip_images = True
                    emit([{"t": "act", "by": p.label, "text": "This model does not take images; renders are described in words."}])
                    continue
                if e.status == 400 and "stream_options" in msg and not no_usage:
                    _NO_STREAM_USAGE.add((p.id, model))
                    no_usage = True
                    continue
                if (e.status in (429, 500, 502, 503, 504, 529) or e.status is None and not p.local) and attempt < 3 \
                        and not streamed["any"]:
                    wait = min(e.retry_after or (2.0 * attempt), 20.0)
                    emit([{"t": "live", "live": {"kind": "thinking", "name": "", "chars": 0, "text": ""}}])
                    end = time.time() + wait
                    while time.time() < end and not control.stopped:
                        time.sleep(0.1)
                    continue
                return {"error": explain(p, e, model), "usage": {}}

    def _anthropic(self, events, control, emit, streamed) -> dict:
        blocks: dict[int, dict] = {}
        raw_in: dict[int, str] = {}
        usage, stop, text_live = {}, None, ""
        for ev in events:
            if control.stopped:
                break
            if "_whole" in ev:
                ev = ev["_whole"]
                for i, b in enumerate(ev.get("content") or []):
                    blocks[i] = b
                u = ev.get("usage") or {}
                usage = _anth_usage(u)
                stop = ev.get("stop_reason")
                break
            t = ev.get("type")
            if t == "message_start":
                usage.update(_anth_usage((ev.get("message") or {}).get("usage") or {}))
            elif t == "content_block_start":
                i, b = ev.get("index", len(blocks)), dict(ev.get("content_block") or {})
                if b.get("type") == "tool_use":
                    b["input"] = {}
                    raw_in[i] = ""
                blocks[i] = b
                kind = {"tool_use": "tool", "thinking": "thinking", "redacted_thinking": "thinking"}.get(b.get("type"), "text")
                emit([{"t": "live", "live": {"kind": kind, "name": b.get("name", ""), "chars": 0, "text": text_live if kind == "text" else ""}}])
            elif t == "content_block_delta":
                streamed["any"] = True
                i, d = ev.get("index", 0), ev.get("delta") or {}
                b = blocks.setdefault(i, {"type": "text", "text": ""})
                dt = d.get("type")
                if dt == "text_delta":
                    b["text"] = b.get("text", "") + d.get("text", "")
                    text_live = (text_live + d.get("text", ""))[-LIVE_TEXT_MAX:]
                    emit([{"t": "live", "live": {"kind": "text", "name": "", "chars": len(text_live), "text": text_live}}])
                elif dt == "input_json_delta":
                    raw_in[i] = raw_in.get(i, "") + d.get("partial_json", "")
                    emit([{"t": "live", "live": {"kind": "tool", "name": b.get("name", ""), "chars": len(raw_in[i]), "text": ""}}])
                elif dt == "thinking_delta":
                    b["thinking"] = b.get("thinking", "") + d.get("thinking", "")
                elif dt == "signature_delta":
                    b["signature"] = b.get("signature", "") + d.get("signature", "")
            elif t == "message_delta":
                stop = (ev.get("delta") or {}).get("stop_reason") or stop
                u = ev.get("usage") or {}
                if u.get("output_tokens") is not None:
                    usage["output_tokens"] = u["output_tokens"]
            elif t == "error":
                e = ev.get("error") or {}
                raise prov.ProviderError(f"{self.p.label}: {e.get('message', e)}",
                                         status=529 if e.get("type") == "overloaded_error" else None)
        if control.stopped:
            return {"error": {"message": "Stopped.", "hint": ""}, "usage": usage}
        content, text, calls = [], "", []
        for i in sorted(blocks):
            b = blocks[i]
            if b.get("type") == "text":
                b = {k: v for k, v in b.items() if k in ("type", "text", "citations") and v is not None}
                if not b.get("text"):
                    continue
                text += b["text"]
            elif b.get("type") == "tool_use":
                bad = None
                if i in raw_in:
                    try:
                        b["input"] = json.loads(raw_in[i]) if raw_in[i].strip() else {}
                        if not isinstance(b["input"], dict):
                            raise ValueError("not an object")
                    except ValueError as e:
                        bad, b["input"] = f"{e}", {}
                calls.append({"id": b.get("id"), "name": b.get("name", ""), "args": b["input"], "bad": bad})
            content.append(b)
        emit([{"t": "live", "live": None}])
        return {"message": {"role": "assistant", "content": content or [{"type": "text", "text": "(no reply)"}]},
                "text": text, "calls": calls, "usage": usage, "stop": stop}

    def _openai(self, events, control, emit, streamed) -> dict:
        text, reasoning, calls, usage, cost, stop = "", "", {}, {}, None, None
        for ev in events:
            if control.stopped:
                break
            if "_whole" in ev:
                ev = ev["_whole"]
                ch = (ev.get("choices") or [{}])[0]
                m = ch.get("message") or {}
                text = m.get("content") or ""
                for j, tc in enumerate(m.get("tool_calls") or []):
                    calls[j] = dict(tc)
                stop = ch.get("finish_reason")
                usage, cost = _oai_usage(ev.get("usage") or {})
                break
            if ev.get("error"):
                e = ev["error"]
                raise prov.ProviderError(f"{self.p.label}: {e.get('message', e) if isinstance(e, dict) else e}")
            if ev.get("usage"):
                usage, c = _oai_usage(ev["usage"])
                cost = c if c is not None else cost
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                if ch.get("finish_reason"):
                    stop = ch["finish_reason"]
                if d.get("content"):
                    streamed["any"] = True
                    text += d["content"]
                    emit([{"t": "live", "live": {"kind": "text", "name": "", "chars": len(text), "text": text[-LIVE_TEXT_MAX:]}}])
                r = d.get("reasoning_content") or d.get("reasoning")
                if isinstance(r, str) and r:
                    streamed["any"] = True
                    reasoning += r
                    emit([{"t": "live", "live": {"kind": "thinking", "name": "", "chars": len(reasoning), "text": ""}}])
                for tc in d.get("tool_calls") or []:
                    streamed["any"] = True
                    j = tc.get("index", len(calls))
                    cur = calls.setdefault(j, {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                    for k, v in tc.items():               # keep what a provider adds (Gemini's thought signatures)
                        if k not in ("index", "function", "id", "type"):
                            cur[k] = v
                    if tc.get("id"):
                        cur["id"] = tc["id"]
                    f = tc.get("function") or {}
                    if f.get("name") and f["name"] != cur["function"]["name"]:
                        cur["function"]["name"] += f["name"]
                    if f.get("arguments"):
                        cur["function"]["arguments"] += f["arguments"] if isinstance(f["arguments"], str) else json.dumps(f["arguments"])
                    emit([{"t": "live", "live": {"kind": "tool", "name": cur["function"]["name"], "chars": len(cur["function"]["arguments"]), "text": ""}}])
        if control.stopped:
            return {"error": {"message": "Stopped.", "hint": ""}, "usage": usage}
        out_calls, msg_calls = [], []
        for j in sorted(calls):
            tc = calls[j]
            tc["id"] = tc.get("id") or "call_" + uuid.uuid4().hex[:12]
            f = tc.get("function") or {}
            raw, bad = f.get("arguments") or "", None
            if isinstance(raw, dict):
                args, raw = raw, json.dumps(raw)
            else:
                try:
                    args = json.loads(raw) if raw.strip() else {}
                    if not isinstance(args, dict):
                        raise ValueError("not an object")
                except ValueError as e:
                    args, bad = {}, str(e)
            tc["function"] = {"name": f.get("name", ""), "arguments": raw or "{}"}
            msg_calls.append(tc)
            out_calls.append({"id": tc["id"], "name": f.get("name", ""), "args": args, "bad": bad})
        msg = {"role": "assistant", "content": text or None}
        if msg_calls:
            msg["tool_calls"] = msg_calls
        if reasoning and self.p.echo_reasoning:
            msg["reasoning_content"] = reasoning
        if msg["content"] is None and not msg_calls:
            msg["content"] = ""
        emit([{"t": "live", "live": None}])
        return {"message": msg, "text": text, "calls": out_calls, "usage": usage, "cost": cost, "stop": stop}


def _anth_usage(u: dict) -> dict:
    return {"input_tokens": int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
            + int(u.get("cache_read_input_tokens") or 0),
            "cache_read_tokens": int(u.get("cache_read_input_tokens") or 0),
            "output_tokens": int(u.get("output_tokens") or 0)}


def _oai_usage(u: dict) -> tuple[dict, float | None]:
    det = u.get("prompt_tokens_details") or {}
    cost = u.get("cost")
    return ({"input_tokens": int(u.get("prompt_tokens") or 0), "output_tokens": int(u.get("completion_tokens") or 0),
             "cache_read_tokens": int((det.get("cached_tokens") if isinstance(det, dict) else 0) or 0)},
            float(cost) if isinstance(cost, (int, float)) else None)


def _has_images(msgs: list) -> bool:
    return any(_imgs_in(m) for m in msgs)


def _imgs_in(m) -> bool:
    c = m.get("content") if isinstance(m, dict) else None
    if not isinstance(c, list):
        return False
    for x in c:
        if isinstance(x, dict) and (x.get("type") in ("image", "image_url") or _imgs_in(x)):
            return True
    return False


def _without_images(msgs: list) -> list:
    def strip(c):
        if not isinstance(c, list):
            return c
        out = []
        for x in c:
            if isinstance(x, dict) and x.get("type") in ("image", "image_url"):
                out.append({"type": "text", "text": "(image left out: this model does not take images)"})
            elif isinstance(x, dict) and isinstance(x.get("content"), list):
                out.append(dict(x, content=strip(x["content"])))
            else:
                out.append(x)
        return out
    return [dict(m, content=strip(m.get("content"))) if isinstance(m, dict) else m for m in msgs]


def explain(p: prov.Provider, e: prov.ProviderError, model: str) -> dict:
    """A provider failure in plain words, with what to do in Form Studio."""
    s, msg = e.status, str(e)
    if s in (401, 403):
        return {"message": f"{p.label} refused the key ({s}).", "hint": "Replace the key in Settings › Agents."}
    if s == 404 or re.search(r"model.{0,40}(not found|does not exist|not exist|unknown)", msg, re.I):
        if p.local:
            return {"message": f"{p.label} has no model “{model}” loaded.", "hint": "Load it in " + p.label + ", or pick another model in the model menu."}
        return {"message": f"{p.label} does not offer the model “{model}” to this account.", "hint": "Pick another model in the model menu."}
    if s == 402 or re.search(r"credit|billing|quota|insufficient", msg, re.I):
        return {"message": msg, "hint": f"Check the billing or credit of your {p.label} account."}
    if s == 429:
        return {"message": f"{p.label} is rate-limiting this key. {msg}", "hint": "Wait a minute and send again, or pick another model."}
    if re.search(r"tool|function", msg, re.I) and s == 400:
        return {"message": msg, "hint": "This model may not support tool calls. Pick one that does; Form Studio needs them."}
    if p.local and s is None:
        return {"message": msg, "hint": p.hint}
    return {"message": msg, "hint": ""}


# Vendors people look for first when a provider resells many (OpenRouter lists several hundred models). Only an
# order for the sections of the menu; model ids always come from the provider's own list.
VENDOR_ORDER = ("anthropic", "openai", "google", "x-ai", "deepseek", "mistralai", "meta-llama", "qwen", "moonshotai",
                "z-ai", "minimax", "nvidia", "microsoft", "cohere", "amazon", "perplexity")
_VENDOR_NAMES = {"x-ai": "xAI", "meta-llama": "Meta", "mistralai": "Mistral", "openai": "OpenAI", "deepseek": "DeepSeek",
                 "moonshotai": "Moonshot AI", "z-ai": "Z.ai", "minimax": "MiniMax", "nvidia": "NVIDIA"}


def _vendor_name(v: str) -> str:
    return _VENDOR_NAMES.get(v) or v.replace("-", " ").title()


def _when(m: dict) -> float:
    c = m.get("created")
    if isinstance(c, (int, float)):
        return float(c)
    if isinstance(c, str) and c:
        from datetime import datetime
        try:
            return datetime.fromisoformat(c.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _ordered(models: list[dict]) -> list[dict]:
    """Vendor sections (the well-known ones first, then by name), newest first inside each; a provider without
    vendors keeps its own order unless its list is dated."""
    if not any(m.get("vendor") for m in models):
        return sorted(models, key=lambda m: -_when(m)) if any(_when(m) for m in models) else list(models)

    def vkey(m):
        v = m.get("vendor") or "~"
        return (VENDOR_ORDER.index(v) if v in VENDOR_ORDER else len(VENDOR_ORDER),
                (m.get("vendor_label") or _vendor_name(v)).lower() if v not in VENDOR_ORDER else "", -_when(m),
                bool(m.get("free")), m["id"])
    return sorted(models, key=vkey)


def all_api_adapters() -> list[ApiAdapter]:
    return [ApiAdapter(p) for p in prov.all_providers().values()]


def sync(adapters: dict) -> dict:
    """Bring the custom providers in `adapters` in line with the saved ones (added, edited, removed). In place."""
    want = {p.id: p for p in prov.all_providers().values() if p.custom}
    for aid in [k for k, a in adapters.items() if getattr(getattr(a, "p", None), "custom", False) and k not in want]:
        del adapters[aid]
    for pid, p in want.items():
        a = adapters.get(pid)
        if a is None or getattr(a, "p", None) != p:
            adapters[pid] = ApiAdapter(p)
    return adapters
