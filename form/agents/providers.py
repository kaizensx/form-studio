"""Model providers Form Studio can talk to directly over their HTTP APIs, without an agent CLI.

Two wire formats cover them all:
- "anthropic": the Anthropic Messages API (POST /v1/messages, server-sent events, tool_use / tool_result blocks).
- "openai": the Chat Completions API (POST /chat/completions, streamed deltas, tool_calls / role "tool"), which
  OpenAI, OpenRouter, Mistral, xAI, DeepSeek, Groq, Gemini's OpenAI-compatible endpoint and the local servers
  (Ollama, LM Studio, llama.cpp's server) all speak.

Detection, without asking anyone:
- a key stored by Form Studio (form/secrets.py) or set in the standard environment variable;
- a local server answering GET <base>/models on its default port (or the URL in [chat] <id>_url).

Models are always read from the provider's own models endpoint. None are written here. A provider's Default is the
model last used with it in Form Studio (or [chat] <id>_model, or the only model it lists, or what a local server has
loaded); otherwise the picker asks for one. Nothing is chosen for the person from a list of hundreds.

Providers the person adds by URL (Settings › Agents & models › Add a provider, `form providers add`) live in
form/agents/custom.py and are merged in by `all_providers()`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .. import secrets

ANTHROPIC_VERSION = "2026-10-21"
LIST_TTL = 900.0                  # seconds a model list is reused
LOCAL_TTL = 20.0                  # seconds a local server's presence is reused
FAIL_TTL = 60.0


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    wire: str                                  # "anthropic" | "openai"
    base: str                                  # default base URL, ending before /models or /chat/completions
    key: str | None = None                     # secret name in form/secrets.py; None: no key (a local server)
    local: bool = False
    docs: str = ""                             # the API reference the request format follows
    stream_usage: bool = False                 # send stream_options.include_usage (the server documents it)
    echo_reasoning: bool = False               # send reasoning_content back with tool calls (DeepSeek)
    reasoning_param: str = ""                  # how an effort is sent: "openrouter"
    simple_schema: bool = False                # tool schemas without title/default/anyOf-null (Gemini, local servers)
    skip: str = ""                             # model ids that are not chat models (embeddings, speech, images)
    hint: str = ""                             # how to make it available, shown when it is not
    verified: str = "not run: not yet verified with a live reply"
    extra_headers: dict = field(default_factory=dict)
    custom: bool = False                       # added by the person (form/agents/custom.py), not built in
    probed: dict = field(default_factory=dict, hash=False)   # custom: {model: {"tools", "images"}} from a test


_NOT_CHAT = r"embed|tts|whisper|dall-e|davinci|babbage|moderation|transcri|realtime|audio|image|imagen|veo|aqa|sora|guard|rerank|ocr"
_NOT_INTERACTIVE = r":batch$"      # OpenRouter's batch variants answer later, in bulk: no use for a conversation

PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("anthropic", "Anthropic API", "anthropic", "https://api.anthropic.com/v1", key="anthropic_api_key",
             docs="https://docs.anthropic.com/en/api/messages", hint="Add an Anthropic API key, or set ANTHROPIC_API_KEY."),
    Provider("openai", "OpenAI API", "openai", "https://api.openai.com/v1", key="openai_api_key", stream_usage=True,
             docs="https://platform.openai.com/docs/api-reference/chat", skip=_NOT_CHAT,
             hint="Add an OpenAI API key, or set OPENAI_API_KEY."),
    Provider("google", "Gemini API", "openai", "https://generativelanguage.googleapis.com/v1beta/openai", key="gemini_api_key",
             docs="https://ai.google.dev/gemini-api/docs/openai", simple_schema=True, skip=_NOT_CHAT,
             hint="Add a Gemini API key, or set GEMINI_API_KEY or GOOGLE_API_KEY."),
    Provider("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", key="openrouter_api_key",
             docs="https://openrouter.ai/docs/api-reference/overview", reasoning_param="openrouter", skip=_NOT_CHAT,
             hint="Add an OpenRouter API key, or set OPENROUTER_API_KEY."),
    Provider("mistral", "Mistral API", "openai", "https://api.mistral.ai/v1", key="mistral_api_key",
             docs="https://docs.mistral.ai/api/", skip=_NOT_CHAT, hint="Add a Mistral API key, or set MISTRAL_API_KEY."),
    Provider("xai", "xAI API", "openai", "https://api.x.ai/v1", key="xai_api_key", stream_usage=True,
             docs="https://docs.x.ai/docs/api-reference", skip=_NOT_CHAT, hint="Add an xAI API key, or set XAI_API_KEY."),
    Provider("deepseek", "DeepSeek API", "openai", "https://api.deepseek.com", key="deepseek_api_key", stream_usage=True,
             echo_reasoning=True, docs="https://api-docs.deepseek.com/", skip=_NOT_CHAT,
             hint="Add a DeepSeek API key, or set DEEPSEEK_API_KEY."),
    Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1", key="groq_api_key", stream_usage=True,
             docs="https://console.groq.com/docs/api-reference", skip=_NOT_CHAT, hint="Add a Groq API key, or set GROQ_API_KEY."),
    Provider("ollama", "Ollama", "openai", "http://127.0.0.1:11434/v1", local=True, stream_usage=True, simple_schema=True,
             docs="https://docs.ollama.com/api/openai-compatibility", skip=_NOT_CHAT,
             hint="Start Ollama (it listens on port 11434) with a model that supports tools."),
    Provider("lmstudio", "LM Studio", "openai", "http://127.0.0.1:1234/v1", local=True, stream_usage=True, simple_schema=True,
             docs="https://lmstudio.ai/docs/developer/openai-compat", skip=_NOT_CHAT,
             hint="Start LM Studio's local server (port 1234) and load a model that supports tools."),
    Provider("llamacpp", "llama.cpp server", "openai", "http://127.0.0.1:8080/v1", local=True, simple_schema=True,
             docs="https://github.com/ggml-org/llama.cpp/tree/master/tools/server", skip=_NOT_CHAT,
             hint="Start llama-server (port 8080) with --jinja so the model can call tools."),
)}


def all_providers() -> dict[str, Provider]:
    """The built-in providers and the ones the person added, by id."""
    from . import custom
    return {**PROVIDERS, **{p.id: p for p in custom.providers()}}


def get(pid: str) -> Provider | None:
    return all_providers().get(pid)


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, hint: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.status, self.hint, self.retry_after = status, hint, retry_after


# ---- where and with what ------------------------------------------------------------------------------------------

def base_url(p: Provider, cfg: dict) -> str:
    c = cfg.get("chat", {}) if isinstance(cfg, dict) else {}
    url = c.get(f"{p.id}_url")
    if not url and p.id == "ollama" and os.environ.get("OLLAMA_HOST"):
        h = os.environ["OLLAMA_HOST"].strip()
        h = h if "://" in h else "http://" + h
        url = h.rstrip("/") + "/v1"
    return str(url or p.base).rstrip("/")


def _configured(p: Provider, cfg: dict) -> bool:
    """[chat] <id>_url is set: the provider is reached where this configuration says (a test's fake server)."""
    return bool((cfg.get("chat", {}) if isinstance(cfg, dict) else {}).get(f"{p.id}_url"))


def credentials(p: Provider) -> tuple[str | None, str]:
    """(key, where it came from). Never shown, never logged."""
    if not p.key:
        return None, ""
    try:
        return secrets.value(p.key)
    except secrets.SecretError:
        return None, ""


def headers(p: Provider, key: str | None) -> dict:
    h = {"content-type": "application/json", "accept": "application/json", "user-agent": "FormStudio"}
    if p.wire == "anthropic":
        if key:
            h["x-api-key"] = key
        h["anthropic-version"] = ANTHROPIC_VERSION
    elif key:
        h["authorization"] = "Bearer " + key
    if p.id == "openrouter":
        h["x-title"] = "Form Studio"
    h.update(p.extra_headers)
    return h


def _opener(local: bool):
    # a local server is never reached through a proxy, whatever HTTP_PROXY says
    return urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()


def _error_text(raw: bytes) -> str:
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw.decode("utf-8", "replace").strip()[:400]
    if isinstance(d, list) and d:
        d = d[0]
    if isinstance(d, dict):
        e = d.get("error", d)
        if isinstance(e, dict):
            return str(e.get("message") or e.get("detail") or json.dumps(e))[:600]
        if isinstance(e, str):
            return e[:600]
        if d.get("message"):
            return str(d["message"])[:600]
        if d.get("detail"):
            return str(d["detail"])[:600]
    return json.dumps(d)[:400]


def _raise(p: Provider, e: urllib.error.HTTPError) -> None:
    try:
        raw = e.read()
    except OSError:
        raw = b""
    msg = _error_text(raw) or e.reason or "no details"
    ra = None
    try:
        ra = float(e.headers.get("retry-after")) if e.headers and e.headers.get("retry-after") else None
    except ValueError:
        ra = None
    raise ProviderError(f"{p.label} answered {e.code}: {msg}", status=e.code, retry_after=ra)


def get_json(p: Provider, url: str, key: str | None, timeout: float = 6.0) -> dict:
    req = urllib.request.Request(url, headers=headers(p, key), method="GET")
    try:
        with _opener(p.local).open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        _raise(p, e)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ProviderError(f"{p.label} could not be reached at {url.rsplit('/', 1)[0]} ({_reason(e)}).")
    return {}


def _reason(e) -> str:
    r = getattr(e, "reason", None) or e
    return str(r)[:160]


def stream(p: Provider, url: str, key: str | None, body: dict, timeout: float = 300.0, holder: dict | None = None):
    """POST body and yield each server-sent event's data (a dict). holder["resp"] is the open response (to close it)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=dict(headers(p, key), accept="text/event-stream"),
                                 method="POST")
    try:
        resp = _opener(p.local).open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        _raise(p, e)
    except (urllib.error.URLError, OSError) as e:
        raise ProviderError(f"{p.label} could not be reached at {url.rsplit('/', 2)[0]} ({_reason(e)}).",
                            hint=p.hint if p.local else "")
    if holder is not None:
        holder["resp"] = resp
    ctype = (resp.headers.get("content-type") or "").lower()
    try:
        if "event-stream" not in ctype:           # some servers answer a stream request with one JSON body
            raw = resp.read()
            d = json.loads(raw.decode("utf-8", "replace") or "{}")
            if isinstance(d, dict) and d.get("error"):
                raise ProviderError(f"{p.label}: {_error_text(raw)}")
            yield {"_whole": d}
            return
        data: list[str] = []
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if data:
                    s = "\n".join(data)
                    data = []
                    if s.strip() == "[DONE]":
                        return
                    try:
                        yield json.loads(s)
                    except ValueError:
                        continue
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
        if data and "\n".join(data).strip() not in ("", "[DONE]"):
            try:
                yield json.loads("\n".join(data))
            except ValueError:
                pass
    except (OSError, ValueError) as e:
        if holder is not None and holder.get("closed"):
            return
        raise ProviderError(f"The connection to {p.label} broke off ({_reason(e)}).")
    finally:
        try:
            resp.close()
        except OSError:
            pass


# ---- models --------------------------------------------------------------------------------------------------------

_CACHE: dict = {}
_CLOCK = threading.Lock()


def _parse_models(p: Provider, d: dict) -> list[dict]:
    rows = d.get("data") if isinstance(d, dict) else None
    if rows is None and isinstance(d, dict) and isinstance(d.get("models"), list):
        rows = d["models"]
    out = []
    for m in rows or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        mid = str(m["id"])
        if mid.startswith("models/"):
            mid = mid[len("models/"):]
        if p.skip and re.search(p.skip, mid, re.I) and p.id != "anthropic":
            continue
        if re.search(_NOT_INTERACTIVE, mid):
            continue
        row = {"id": mid, "label": str(m.get("display_name") or m.get("name") or "") or None,
               "created": m.get("created") or m.get("created_at") or 0, "images": None, "efforts": [], "tools": None,
               "max_tokens": m.get("max_tokens") if isinstance(m.get("max_tokens"), int) else None,
               "context": m.get("context_length") if isinstance(m.get("context_length"), int) else None,
               "free": None, "vendor": None, "vendor_label": None}
        if "/" in mid:                                               # vendor/model (OpenRouter, Groq's meta-llama/…)
            row["vendor"] = mid.split("/", 1)[0]
            lab = row["label"] or ""
            if ": " in lab:                                          # OpenRouter names them "Vendor: Model"
                row["vendor_label"], row["label"] = lab.split(": ", 1)
        price = m.get("pricing")
        if isinstance(price, dict) and price.get("prompt") is not None and price.get("completion") is not None:
            try:
                row["free"] = float(price["prompt"]) == 0 and float(price["completion"]) == 0
            except (TypeError, ValueError):
                row["free"] = None
        if mid.endswith(":free"):
            row["free"] = True
        caps = m.get("capabilities")
        if p.wire == "anthropic" and isinstance(caps, dict):
            img = caps.get("image_input")
            row["images"] = bool(img.get("supported")) if isinstance(img, dict) else None
            eff = caps.get("effort")
            if isinstance(eff, dict) and eff.get("supported"):
                row["efforts"] = [k for k, v in eff.items() if k != "supported" and isinstance(v, dict) and v.get("supported")]
        elif isinstance(caps, dict):                                 # Mistral: {completion_chat, function_calling, vision}
            if caps.get("completion_chat") is False:
                continue
            row["tools"] = caps.get("function_calling")
            row["images"] = caps.get("vision")
        if isinstance(m.get("supported_parameters"), list):           # OpenRouter, and servers that copy its shape
            sp = m.get("supported_parameters") or []
            row["tools"] = "tools" in sp
            mods = (m.get("architecture") or {}).get("input_modalities") or []
            row["images"] = "image" in mods
            if "reasoning" in sp:
                row["efforts"] = ["low", "medium", "high"]
        probe = p.probed.get(mid) if p.probed else None               # a custom provider's model, tested by the person
        if isinstance(probe, dict):
            for k in ("tools", "images"):
                if probe.get(k) is not None:
                    row[k] = probe[k]
        if row["tools"] is False and not p.custom:
            continue                                                  # Form Studio needs tool calls
        out.append(row)
    return out


def _fetch(p: Provider, cfg: dict) -> dict:
    key, where = credentials(p)
    base = base_url(p, cfg)
    if p.key and not key:
        return {"available": False, "why": p.hint, "models": [], "base": base, "where": ""}
    if not p.local and not p.custom and os.environ.get("FORM_PROVIDERS_OFFLINE") == "1" and not _configured(p, cfg):
        return {"available": False, "why": "Not checked: provider lookups are off for this run (FORM_PROVIDERS_OFFLINE).",
                "models": [], "base": base, "where": where}
    url = base + ("/models?limit=1000" if p.wire == "anthropic" else "/models")
    try:
        d = get_json(p, url, key, timeout=1.5 if p.local and not p.custom else 6.0)
    except ProviderError as e:
        if p.local and not p.custom:
            return {"available": False, "why": p.hint, "models": [], "base": base, "where": ""}
        if p.custom:
            from .custom import explain_failure
            return {"available": False, "why": explain_failure(p, e), "models": [], "base": base, "where": where, "error": True}
        why = str(e)
        if e.status in (401, 403):
            why = f"The {p.label} key was refused ({e.status}). Replace it in Settings › Agents & models."
        return {"available": False, "why": why, "models": [], "base": base, "where": where, "error": True}
    models = _parse_models(p, d)
    if p.local and not models:
        return {"available": False, "why": f"{p.label} is running at {base} but has no model loaded.", "models": [],
                "base": base, "where": "local"}
    return {"available": True, "why": None, "models": models, "base": base, "where": where or "local"}


def _ckey(p: Provider, cfg: dict) -> tuple:
    key, _ = credentials(p)
    return (p.id, base_url(p, cfg), hashlib.sha256((key or "").encode()).hexdigest()[:12])


def info(p: Provider, cfg: dict, refresh: bool = False) -> dict:
    """What is known about one provider now: {available, why, models, base, where}. Cached; never raises."""
    k = _ckey(p, cfg)
    with _CLOCK:
        hit = _CACHE.get(k)
    now = time.time()
    if hit and not refresh:
        ttl = (LOCAL_TTL if p.local else LIST_TTL) if hit[1].get("available") else (LOCAL_TTL if p.local else FAIL_TTL)
        if now - hit[0] < ttl:
            return hit[1]
    if p.key and not credentials(p)[0]:
        return {"available": False, "why": p.hint, "models": [], "base": base_url(p, cfg), "where": ""}
    try:
        got = _fetch(p, cfg)
    except Exception as e:                                       # a provider must never break the agent list
        got = {"available": False, "why": f"{p.label}: {type(e).__name__}", "models": [], "base": base_url(p, cfg), "where": ""}
    with _CLOCK:
        _CACHE[k] = (now, got)
    return got


def warm(cfg: dict, ids=None, timeout: float = 7.0) -> None:
    """Ask every detectable provider at once, so a status read waits for the slowest one, not for their sum."""
    todo = [p for p in all_providers().values() if (ids is None or p.id in ids) and (p.local or not p.key or credentials(p)[0])]
    if not todo:
        return
    ex = ThreadPoolExecutor(max_workers=len(todo), thread_name_prefix="form-providers")
    futs = [ex.submit(info, p, cfg) for p in todo]
    end = time.time() + timeout
    for f in futs:
        try:
            f.result(timeout=max(0.1, end - time.time()))
        except Exception:
            pass
    ex.shutdown(wait=False)                  # a slow provider finishes in the background and fills the cache


def forget(pid: str | None = None) -> None:
    """Drop cached lists (a key was saved or removed)."""
    with _CLOCK:
        for k in [k for k in _CACHE if pid is None or k[0] == pid]:
            _CACHE.pop(k, None)
