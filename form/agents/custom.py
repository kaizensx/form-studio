"""Model providers the person adds by URL: any server that speaks one of the wire formats Form Studio knows.

Settings › Agents & models › "Add a provider…" and `form providers add` ask for a name (optional), a base URL and an API key
(optional: a server on this computer often needs none), then `detect()` works out the rest without a model call:

1. The models endpoint: GET <base>/models, trying the URL as typed, with and without /v1, and the usual prefixes
   (/api/v1, /openai/v1, /api), plus Ollama's /api/tags. The answer's shape names the wire format:
   - OpenAI-compatible: {"object": "list", "data": [{"id": ...}]}  (OpenAI, OpenRouter, vLLM, LiteLLM, LM Studio, …)
   - Anthropic-compatible: {"data": [{"type": "model", "id", "display_name"}], "has_more", "first_id"}
   - Gemini: {"models": [{"name": "models/…", "supportedGenerationMethods"}]}; Form Studio then uses Gemini's
     OpenAI-compatible endpoint next to it (<base>/openai).
2. The chat endpoint: an empty POST to <base>/chat/completions or <base>/messages. The server refuses it as invalid
   (400/422), which shows the endpoint is there; nothing is generated and nothing is billed.
3. Which models take tools and images: from the list's own metadata when it gives it (OpenRouter's
   supported_parameters, Mistral's capabilities, Anthropic's capabilities, Ollama's /api/show). Otherwise unknown,
   until the person presses Test on a model (`probe()`): one tiny request with a "ping" tool (or a 1-pixel image).

Nothing is saved until the person saves the result. The URL, name and format go to providers.json next to Form
Studio's secrets file (owner-only, like it); the key goes into the secrets file (form/secrets.py) under
custom_<slug>_api_key and is never shown or printed again. Each saved provider becomes an API agent
(form/agents/api.py) in the model picker, Settings and `form chat --agent custom-<slug>`.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import fsutil, secrets
from . import providers as prov

FORMATS = {"openai": "OpenAI-compatible", "anthropic": "Anthropic-compatible", "gemini": "Gemini (OpenAI-compatible endpoint)"}
_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "list": []}
# a 1×1 PNG, for the image test
_PIXEL = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class ProviderSetupError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint

    def public(self) -> dict:
        return {"message": str(self), "hint": self.hint}


# ---- storage ---------------------------------------------------------------------------------------------------------

def path():
    return secrets.path().with_name("providers.json")


def records() -> list[dict]:
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = d.get("providers") if isinstance(d, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and re.fullmatch(r"custom-[a-z0-9-]{1,48}", str(r.get("id", "")))
            and r.get("wire") in ("openai", "anthropic") and str(r.get("base", "")).startswith(("http://", "https://"))]


def _write(rows: list[dict]) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"providers": rows}, f, indent=1, ensure_ascii=False)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    fsutil.replace(tmp, p)
    with _LOCK:
        _CACHE["key"] = None


def providers() -> list[prov.Provider]:
    """Every saved provider as a Provider. Re-read only when the file changed."""
    p = path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(p), None, None)
    with _LOCK:
        if _CACHE["key"] == key:
            return list(_CACHE["list"])
    out = [_provider(r) for r in records()]
    with _LOCK:
        _CACHE["key"], _CACHE["list"] = key, out
    return list(out)


def _provider(r: dict) -> prov.Provider:
    name = secrets.custom_name(r["id"][len("custom-"):])
    return prov.Provider(
        r["id"], str(r.get("name") or _host(r["base"])), r["wire"], r["base"].rstrip("/"),
        key=name if r.get("has_key") else None, local=bool(r.get("local")), docs=r["base"], simple_schema=True,
        skip=prov._NOT_CHAT, custom=True, probed=dict(r.get("probed") or {}),
        hint=f"Check {r.get('name') or _host(r['base'])} in Settings › Agents & models › Your providers (Test).",
        verified=f"{FORMATS.get(r.get('format') or r['wire'], r['wire'])}; the connection was tested when you added it")


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc or url


def _host_is(url: str, domain: str) -> bool:
    """True when the URL's host is the domain or one of its subdomains (not a host that merely contains it)."""
    h = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
    return h == domain or h.endswith("." + domain)


def _is_local(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".lan", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        return False


def _slug(name: str, base: str, taken: set) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (name or _host(base).split(":")[0]).lower()).strip("-")[:32] or "provider"
    s, n = raw, 2
    while "custom-" + s in taken:
        s, n = f"{raw}-{n}", n + 1
    return s


def listing() -> list[dict]:
    """For the API and the CLI: every saved provider, with whether a key is stored (never the key)."""
    out = []
    for r in records():
        name = secrets.custom_name(r["id"][len("custom-"):])
        k, _ = secrets.value(name) if r.get("has_key") else (None, "")
        out.append({"id": r["id"], "name": r.get("name") or _host(r["base"]), "base": r["base"], "input": r.get("input"),
                    "wire": r["wire"], "format": FORMATS.get(r.get("format") or r["wire"]), "local": bool(r.get("local")),
                    "key_set": bool(k), "added": r.get("added"), "models": r.get("count"), "tools": r.get("tools"),
                    "probed": r.get("probed") or {}})
    return out


def save(name: str, url: str, key: str | None = None, pid: str | None = None, keep_key: bool = True,
         found: dict | None = None) -> dict:
    """Detect (unless `found` is a detect() result for the same URL and key) and save. Editing (`pid` given): an empty
    key keeps the stored one when keep_key, so a key never has to be pasted again to rename a provider."""
    rows = records()
    old = next((r for r in rows if r["id"] == pid), None) if pid else None
    if pid and not old:
        raise ProviderSetupError(f"No provider “{pid}”.", "form providers list shows the ones saved.")
    key = (key or "").strip() or None
    sname = secrets.custom_name((pid or "x-x")[len("custom-"):]) if pid else None
    if not key and old and keep_key and old.get("has_key"):
        key = secrets.value(sname)[0]
    got = found if found and found.get("ok") else detect(url, key)
    if not got.get("ok"):
        raise ProviderSetupError(got["message"], got.get("hint", ""))
    if not pid:
        pid = "custom-" + _slug(name, got["base"], {r["id"] for r in rows})
        sname = secrets.custom_name(pid[len("custom-"):])
    rec = {"id": pid, "name": (name or "").strip()[:60] or got.get("name") or _host(got["base"]), "base": got["base"],
           "input": url.strip(), "wire": got["wire"], "format": got["format_id"], "local": got["local"],
           "has_key": bool(key), "added": (old or {}).get("added") or time.time(), "count": got["count"],
           "tools": got["tools"], "probed": (old or {}).get("probed") if old and old.get("base") == got["base"] else {}}
    if key:
        secrets.set_value(sname, key)
    elif old and old.get("has_key"):
        secrets.clear(sname)
    rows = [r for r in rows if r["id"] != pid] + [rec]
    _write(rows)
    prov.forget(pid)
    return {"provider": next(x for x in listing() if x["id"] == pid), "detected": got}


def remove(pid: str) -> dict:
    rows = records()
    if not any(r["id"] == pid for r in rows):
        raise ProviderSetupError(f"No provider “{pid}”.", "form providers list shows the ones saved.")
    _write([r for r in rows if r["id"] != pid])
    try:
        secrets.clear(secrets.custom_name(pid[len("custom-"):]))
    except secrets.SecretError:
        pass
    prov.forget(pid)
    return {"removed": pid, "providers": listing()}


def stored_key(pid: str) -> str | None:
    r = next((r for r in records() if r["id"] == pid), None)
    if not r or not r.get("has_key"):
        return None
    return secrets.value(secrets.custom_name(pid[len("custom-"):]))[0]


# ---- detection -------------------------------------------------------------------------------------------------------

def normalize(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        raise ProviderSetupError("Enter the server's address.", "For example https://api.example.com/v1 or http://localhost:8000.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        host = u.split("/", 1)[0].split(":")[0]
        u = ("http://" if _is_local("http://" + host) else "https://") + u
    pu = urllib.parse.urlparse(u)
    if pu.scheme not in ("http", "https") or not pu.netloc:
        raise ProviderSetupError(f"“{url}” is not a web address.", "Use http:// or https:// followed by the server's address.")
    if pu.query or pu.fragment:
        u = urllib.parse.urlunparse(pu._replace(query="", fragment=""))
    for tail in ("/chat/completions", "/completions", "/messages", "/models", "/api/tags"):
        if u.lower().endswith(tail):
            u = u[: -len(tail)]
            break
    return u.rstrip("/")


def candidates(u: str) -> list[str]:
    out = [u]
    if re.search(r"/v\d+(beta\d*)?$", u):
        out.append(re.sub(r"/v\d+(beta\d*)?$", "", u))
    else:
        out += [u + "/v1", u + "/api/v1", u + "/openai/v1", u + "/api"]
    return list(dict.fromkeys(x for x in out if x.startswith(("http://", "https://"))))


def _headers(key: str | None, wire: str | None = None) -> dict:
    h = {"accept": "application/json", "content-type": "application/json", "user-agent": "FormStudio"}
    if wire == "anthropic":
        # only when talking Anthropic: a gateway that sees this header answers in Anthropic's format and lists less
        h["anthropic-version"] = prov.ANTHROPIC_VERSION
    if key:
        # the key goes only to the server the person typed; which header it reads is what detection finds out
        if wire in (None, "openai"):
            h["authorization"] = "Bearer " + key
        if wire in (None, "anthropic"):
            h["x-api-key"] = key
        if wire is None:
            h["x-goog-api-key"] = key
    return h


def _request(url: str, key: str | None, body: dict | None = None, wire: str | None = None, timeout: float = 6.0):
    """(status, parsed JSON or None, error kind or None). Never raises for HTTP or network failures."""
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=_headers(key, wire), method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if _is_local(url) else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read(8_000_000)
            try:
                return r.status, json.loads(raw.decode("utf-8", "replace") or "null"), None
            except ValueError:
                return r.status, None, "not_json"
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(200_000)
            d = json.loads(raw.decode("utf-8", "replace") or "null")
        except (OSError, ValueError):
            d = None
        return e.code, d, None
    except (urllib.error.URLError, OSError, ValueError) as e:
        r = re.sub(r"^\[Errno -?\d+\]\s*", "", str(getattr(e, "reason", e)))
        return None, None, "timeout" if "timed out" in r else "connect:" + r[:160].lower()


def _shape(d) -> str | None:
    """Which wire format a models answer is in, from its shape alone."""
    if isinstance(d, dict) and isinstance(d.get("data"), list):
        items = [m for m in d["data"] if isinstance(m, dict)]
        if items and all(m.get("type") == "model" for m in items) and ("has_more" in d or "first_id" in d or
                                                                      any("display_name" in m for m in items)):
            return "anthropic"
        if not items and ("has_more" in d or "first_id" in d) and d.get("object") != "list":
            return "anthropic"
        if all("id" in m for m in items):
            return "openai"
    if isinstance(d, dict) and isinstance(d.get("models"), list):
        items = [m for m in d["models"] if isinstance(m, dict)]
        if items and any(str(m.get("name", "")).startswith("models/") for m in items):
            return "gemini"
        if items and all("name" in m and ("digest" in m or "model" in m) for m in items):
            return "ollama"
    return None


def _err_text(d) -> str:
    if isinstance(d, dict):
        e = d.get("error", d)
        if isinstance(e, dict):
            return str(e.get("message") or e.get("detail") or "")[:300]
        if isinstance(e, str):
            return e[:300]
        if d.get("message"):
            return str(d["message"])[:300]
    return ""


def detect(url: str, key: str | None = None, timeout: float = 6.0) -> dict:
    """What a server is, from its own answers. Returns {"ok": True, wire, format, format_id, base, local, count,
    models, tools, images, message, warnings} or {"ok": False, error, message, hint, tried}. Never includes the key."""
    try:
        u = normalize(url)
    except ProviderSetupError as e:
        return {"ok": False, "error": "bad_url", "message": str(e), "hint": e.hint, "tried": []}
    key = (key or "").strip() or None
    tried, auth, last_err = [], None, None
    found = None
    for c in candidates(u):
        tried.append(c + "/models")
        status, d, err = _request(c + "/models", key, timeout=timeout)
        if status == 400 and "anthropic-version" in json.dumps(d or {}).lower():
            status, d, err = _request(c + "/models", key, wire="anthropic", timeout=timeout)   # Anthropic asks for it
        if err and err.startswith("connect:") or err == "timeout":
            last_err = err
            if len(tried) == 1:
                break                         # nothing answers at that address at all; other paths will not either
            continue
        if status in (401, 403):
            auth = (status, _err_text(d))
            break
        if status == 200 and err is None:
            kind = _shape(d)
            if kind == "gemini":
                tried.append(c + "/openai/models")
                s2, d2, e2 = _request(c + "/openai/models", key, timeout=timeout)
                if s2 == 200 and _shape(d2) == "openai":
                    found = ("openai", c + "/openai", d2, "gemini")
                    break
                return {"ok": False, "error": "format", "tried": tried,
                        "message": "This is Gemini's own API. Form Studio talks to Gemini through its OpenAI-compatible endpoint, which did not answer here.",
                        "hint": "Use https://generativelanguage.googleapis.com/v1beta/openai, or add the key under Gemini API."}
            if kind == "openai":
                found = (kind, c, d, kind)
                break
            if kind == "anthropic" and not found:
                # gateways (OpenRouter and others) answer Anthropic-style on one path and OpenAI-style on another:
                # the OpenAI one lists every model and calls tools the same way for all of them, so keep looking for
                # it and use the Anthropic answer only when nothing else answers (Anthropic itself, or a proxy of it)
                found = (kind, c, d, kind)
                if _host_is(c, "anthropic.com"):
                    break
    if not found and not auth and not (last_err and len(tried) == 1):
        root = re.sub(r"/(v\d+|api(/v\d+)?|openai(/v\d+)?)$", "", u)          # Ollama's own list, then its /v1
        tried.append(root + "/api/tags")
        status, d, err = _request(root + "/api/tags", key, timeout=timeout)
        if status == 200 and _shape(d) == "ollama":
            s2, d2, _ = _request(root + "/v1/models", key, timeout=timeout)
            if s2 == 200 and _shape(d2) == "openai":
                found = ("openai", root + "/v1", d2, "openai")
    if auth:
        return {"ok": False, "error": "auth", "tried": tried,
                "message": f"The server refused {'the key' if key else 'to answer without a key'} ({auth[0]}).",
                "hint": ("Check the key: copy it again from the provider's dashboard." if key else "This server needs an API key.")
                        + (f" It said: {auth[1]}" if auth[1] else "")}
    if not found:
        if last_err and (len(tried) == 1 or last_err == "timeout"):
            why = "it did not answer in time" if last_err == "timeout" else last_err.split(":", 1)[1]
            return {"ok": False, "error": "connect", "tried": tried,
                    "message": f"Could not connect to {_host(u)} ({why}).",
                    "hint": "Check the address and that the server is running." + (" On this computer, start it first." if _is_local(u) else "")}
        return {"ok": False, "error": "not_found", "tried": tried,
                "message": f"No models list was found at {u}.",
                "hint": "Form Studio looked for an OpenAI-, Anthropic- or Gemini-style models endpoint at: "
                        + ", ".join(t.replace(u, "…") or "/" for t in tried) + ". Use the base URL from the provider's documentation."}
    wire, base, d, fmt = found
    p = prov.Provider("custom-probe", _host(base), wire, base, skip=prov._NOT_CHAT, custom=True)
    models = prov._parse_models(p, d)
    warnings = []
    if not models:
        return {"ok": False, "error": "no_models", "tried": tried,
                "message": f"{_host(base)} answers as {FORMATS[fmt]} but lists no chat models.",
                "hint": "Load or enable a model on the server, then try again."}
    _ollama_caps(base, key, models, timeout)
    chat_url = base + ("/messages" if wire == "anthropic" else "/chat/completions")
    s3, d3, e3 = _request(chat_url, key, body={}, wire=wire, timeout=timeout)
    if s3 in (404, 405) or e3 and e3 != "not_json":
        warnings.append(f"The models list answered, but {chat_url} did not ({s3 or e3}). Replies may fail.")
    yes = sum(1 for m in models if m.get("tools") is True)
    no = sum(1 for m in models if m.get("tools") is False)
    unknown = len(models) - yes - no
    tools = "yes" if yes and not no and not unknown else "no" if no and not yes and not unknown else "some" if yes else "unknown"
    t_text = {"yes": "tools supported", "some": f"tools supported by {yes} of {len(models)}",
              "no": "no model supports tool calls", "unknown": "tool support not listed (test a model)"}[tools]
    if tools == "no":
        warnings.append("Form Studio's agent works by calling tools, and this server says none of its models can. "
                        "Pick another server or model.")
    imgs = sum(1 for m in models if m.get("images") is True)
    return {"ok": True, "wire": wire, "format": FORMATS[fmt], "format_id": fmt, "base": base, "local": _is_local(base),
            "name": _host(base), "count": len(models), "tools": tools, "images": imgs, "tried": tried,
            "models": [{k: m.get(k) for k in ("id", "label", "tools", "images", "free", "vendor", "context")} for m in models],
            "message": f"Connected: {FORMATS[fmt]}, {len(models)} model{'s' if len(models) != 1 else ''}, {t_text}",
            "warnings": warnings}


def _ollama_caps(base: str, key: str | None, models: list[dict], timeout: float) -> None:
    """Ollama names each model's capabilities ("tools", "vision") in /api/show; ask for a few, never many."""
    root = re.sub(r"/v1$", "", base)
    if not _is_local(base) or len(models) > 30:
        return
    s, d, _ = _request(root + "/api/tags", key, timeout=2)
    if s != 200 or _shape(d) != "ollama":
        return
    for m in models:
        s, d, _ = _request(root + "/api/show", key, body={"model": m["id"]}, timeout=3)
        caps = d.get("capabilities") if s == 200 and isinstance(d, dict) else None
        if isinstance(caps, list):
            m["tools"], m["images"] = "tools" in caps, "vision" in caps


def explain_failure(p: prov.Provider, e: prov.ProviderError) -> str:
    if e.status in (401, 403):
        return f"{p.label} refused the key ({e.status}). Edit it in Settings › Agents & models › Your providers."
    if e.status == 404:
        return f"{p.label} no longer lists models at {p.base}. Edit its address in Settings › Agents & models."
    return f"{p.label} did not answer: {e}"


# ---- testing one model (only when the person asks) -------------------------------------------------------------------

def probe(pid: str, model: str, what: str = "tools") -> dict:
    """One small request to see whether `model` calls a tool (what="tools") or takes an image (what="images").
    Saves the answer with the provider, so the picker shows it. Costs a few tokens; only run on the person's click."""
    p = next((x for x in providers() if x.id == pid), None)
    if not p:
        raise ProviderSetupError(f"No provider “{pid}”.", "form providers list shows the ones saved.")
    if what not in ("tools", "images"):
        raise ProviderSetupError("Test either tools or images.")
    key = stored_key(pid)
    msg = "Call the ping tool now." if what == "tools" else "What colour is this one-pixel image? Answer in one word."
    if p.wire == "anthropic":
        content = msg if what == "tools" else [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _PIXEL}},
                                              {"type": "text", "text": msg}]
        body = {"model": model, "max_tokens": 48, "messages": [{"role": "user", "content": content}]}
        if what == "tools":
            body.update(tools=[{"name": "ping", "description": "Answers pong. Call it when asked to ping.",
                                "input_schema": {"type": "object", "properties": {}}}], tool_choice={"type": "any"})
        url = p.base + "/messages"
    else:
        content = msg if what == "tools" else [{"type": "text", "text": msg},
                                              {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _PIXEL}}]
        body = {"model": model, "max_tokens": 48, "stream": False, "messages": [{"role": "user", "content": content}]}
        if what == "tools":
            body["tools"] = [{"type": "function", "function": {"name": "ping", "description": "Answers pong. Call it when asked to ping.",
                                                               "parameters": {"type": "object", "properties": {}}}}]
        url = p.base + "/chat/completions"
    status, d, err = _request(url, key, body=body, wire=p.wire, timeout=60)
    text = _err_text(d)
    result: bool | None
    if err:
        return {"ok": False, "model": model, "what": what, "message": f"{p.label} did not answer ({err.split(':', 1)[-1]}).", "result": None}
    if status in (401, 403):
        return {"ok": False, "model": model, "what": what, "message": f"{p.label} refused the key ({status}).", "result": None}
    if status == 404 and re.search(r"model", text, re.I):
        return {"ok": False, "model": model, "what": what, "message": f"{p.label} does not know the model “{model}”.", "result": None}
    if status != 200:
        refused = status in (400, 422, 500) and re.search(r"tool|function" if what == "tools" else r"image|vision|multimodal|content", text, re.I)
        result = False if refused else None
        message = (("This model does not take tool calls" if what == "tools" else "This model does not take images")
                   + (f": {text}" if text else ".")) if refused else f"{p.label} answered {status}: {text or 'no details'}"
    elif what == "tools":
        called = (any(b.get("type") == "tool_use" for b in d.get("content") or [] if isinstance(b, dict)) if p.wire == "anthropic"
                  else bool(((d.get("choices") or [{}])[0].get("message") or {}).get("tool_calls")))
        result = True if called else None
        message = "Tool calls work with this model." if called else \
            "The model answered without calling the tool. It may still work; a model that calls tools reliably is better."
    else:
        result, message = True, "This model takes images."
    if result is not None:
        rows = records()
        for r in rows:
            if r["id"] == pid:
                r.setdefault("probed", {}).setdefault(model, {})[what] = result
        _write(rows)
        prov.forget(pid)
    return {"ok": result is not False, "model": model, "what": what, "result": result, "message": message}


# ---- form providers ... ----------------------------------------------------------------------------------------------

USAGE = """form providers list
form providers add URL [--name NAME] [--no-key]     the key is read from stdin or a hidden prompt, never an argument
form providers edit ID [--url URL] [--name NAME] [--key | --no-key]
form providers test ID [--model MODEL [--tools | --images]]
form providers remove ID"""


def main(argv=None) -> int:
    import argparse
    import getpass

    def out(o):
        print(json.dumps(o, indent=1, ensure_ascii=False))

    def read_key(label: str) -> str:
        # never from the command line: it would end up in the shell history and the process list
        if not sys.stdin.isatty():
            return sys.stdin.readline().strip()
        return getpass.getpass(f"API key for {label} (Enter for none): ").strip()

    argv = list(argv or [])
    ap = argparse.ArgumentParser(prog="form providers", usage=USAGE, add_help=True)
    ap.add_argument("cmd", nargs="?", default="list", choices=["list", "add", "edit", "test", "remove"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--name", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-key", action="store_true")
    ap.add_argument("--key", action="store_true", help="edit: ask for a new key")
    ap.add_argument("--tools", action="store_true")
    ap.add_argument("--images", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            out({"providers": listing(), "file": str(path())})
            return 0
        if a.cmd == "add":
            if not a.target:
                raise ProviderSetupError("Give the server's address.", USAGE)
            key = None if a.no_key else read_key(a.name or a.target)
            got = detect(a.target, key)
            if not got["ok"]:
                out({"error": {"message": got["message"], "hint": got.get("hint", "")}, "tried": got.get("tried")})
                return 2
            done = save(a.name or "", a.target, key, found=got)
            out({k: v for k, v in done.items()})
            return 0
        if a.cmd == "edit":
            r = next((x for x in records() if x["id"] == a.target), None)
            if not r:
                raise ProviderSetupError(f"No provider “{a.target}”.", "form providers list shows the ones saved.")
            key = read_key(r.get("name") or a.target) if a.key else None
            out(save(a.name if a.name is not None else r.get("name", ""), a.url or r.get("input") or r["base"], key,
                     pid=a.target, keep_key=not a.no_key))
            return 0
        if a.cmd == "remove":
            out(remove(a.target or ""))
            return 0
        if a.cmd == "test":
            r = next((x for x in records() if x["id"] == a.target), None)
            if not r:
                raise ProviderSetupError(f"No provider “{a.target}”.", "form providers list shows the ones saved.")
            if a.model:
                out(probe(a.target, a.model, "images" if a.images else "tools"))
                return 0
            got = detect(r["base"], stored_key(a.target))
            if len(got.get("models") or []) > 50:
                got.pop("models")                # the count says it; a long list is for the app's menu
            out(got)
            return 0 if got["ok"] else 2
    except (ProviderSetupError, secrets.SecretError) as e:
        print(json.dumps({"error": {"message": str(e), "hint": getattr(e, "hint", "")}}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0
