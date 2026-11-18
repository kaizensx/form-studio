"""API keys Form Studio keeps, so nobody has to open a terminal to set an environment variable.

Two kinds of use: Gemini CLI runs headless only with GEMINI_API_KEY, and the API agents (form/agents/api.py) talk to
a model provider directly with that provider's key. The Settings sheet (Agents tab) and `form secrets` store them.

Rules:
- One JSON file, `secrets.json` in Form Studio's user folder (`~/.config/form-studio`, or $FORM_SECRETS for tests),
  readable by this user only. Never studio.toml: that file is meant to be shared and backed up.
- A value is never returned by the API, the CLI or MCP: only whether it is set. MCP has no way to read or write it.
- A key is handed only to the agents it belongs to: as an environment variable to a CLI (and only when that variable
  is not already set), or read in-process by an API agent for its own provider's requests.
- A key set in the environment wins over a stored one.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import fsutil


def _key(label, agents, env, help, url, alt=()):
    return {"label": label, "agents": list(agents), "agent": agents[0], "env": env, "alt": list(alt), "help": help, "url": url}


KNOWN = {
    "anthropic_api_key": _key("Anthropic API key", ["anthropic"], "ANTHROPIC_API_KEY",
                              "Claude models through the Anthropic API, billed to that Anthropic account.",
                              "https://console.anthropic.com/settings/keys"),
    "openai_api_key": _key("OpenAI API key", ["openai"], "OPENAI_API_KEY",
                           "OpenAI models through the OpenAI API, billed to that OpenAI account.",
                           "https://platform.openai.com/api-keys"),
    "gemini_api_key": _key("Gemini API key", ["gemini", "google"], "GEMINI_API_KEY",
                           "Gemini models through the Gemini API, and Gemini CLI inside Form Studio. Usage is billed to that Google account.",
                           "https://aistudio.google.com/apikey", alt=["GOOGLE_API_KEY"]),
    "openrouter_api_key": _key("OpenRouter API key", ["openrouter"], "OPENROUTER_API_KEY",
                               "Models from many providers through OpenRouter, billed to that OpenRouter account.",
                               "https://openrouter.ai/keys"),
    "mistral_api_key": _key("Mistral API key", ["mistral"], "MISTRAL_API_KEY",
                            "Mistral models through the Mistral API.", "https://console.mistral.ai/api-keys"),
    "xai_api_key": _key("xAI API key", ["xai"], "XAI_API_KEY", "Grok models through the xAI API.", "https://console.x.ai"),
    "deepseek_api_key": _key("DeepSeek API key", ["deepseek"], "DEEPSEEK_API_KEY", "DeepSeek models through the DeepSeek API.",
                             "https://platform.deepseek.com/api_keys"),
    "groq_api_key": _key("Groq API key", ["groq"], "GROQ_API_KEY", "Open models served by Groq.", "https://console.groq.com/keys"),
}


class SecretError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint

    def public(self) -> dict:
        return {"message": str(self), "hint": self.hint}


def path() -> Path:
    if os.environ.get("FORM_SECRETS"):
        return Path(os.environ["FORM_SECRETS"]).expanduser()
    return Path("~/.config/form-studio/secrets.json").expanduser()


def _read() -> dict:
    p = path()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if k in KNOWN and isinstance(v, str) and v} if isinstance(d, dict) else {}


def _write(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)     # owner only, from the first byte
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass                                                                   # Windows: the profile folder is private
    fsutil.replace(tmp, p)


def _check(name: str) -> dict:
    spec = KNOWN.get(name)
    if spec is None:
        raise SecretError(f"Unknown key “{name}”.", "Known: " + ", ".join(KNOWN))
    return spec


def set_value(name: str, value: str) -> dict:
    _check(name)
    v = (value or "").strip()
    if not v:
        raise SecretError("The key is empty.", "Paste the whole key, or use Remove to delete the stored one.")
    if len(v) > 400 or re.search(r"\s", v):
        raise SecretError("That does not look like an API key: it has spaces or line breaks, or is very long.",
                          "Copy the key again from the page that created it.")
    d = _read()
    d[name] = v
    _write(d)
    return status()[name]


def clear(name: str) -> dict:
    _check(name)
    d = _read()
    if d.pop(name, None) is not None:
        _write(d)
    return status()[name]


def _env_name(spec: dict) -> str | None:
    """The environment variable that holds this key for this process, if any."""
    return next((v for v in [spec["env"], *spec["alt"]] if os.environ.get(v)), None)


def status() -> dict:
    """{name: {label, help, url, agent, agents, env, set, from_env, env_name}}. Never the value."""
    d = _read()
    out = {}
    for name, spec in KNOWN.items():
        env = _env_name(spec)
        out[name] = {"name": name, "label": spec["label"], "help": spec["help"], "url": spec["url"], "agent": spec["agent"],
                     "agents": spec["agents"], "env": spec["env"], "set": bool(d.get(name)), "from_env": bool(env),
                     "env_name": env}
    return out


def for_agent(agent: str) -> str | None:
    """The secret name that belongs to an agent (an API provider), or None."""
    return next((n for n, spec in KNOWN.items() if agent in spec["agents"]), None)


def value(name: str) -> tuple[str | None, str]:
    """(key, where) for in-process use by an API agent: the environment first, then the stored file. Never logged."""
    spec = _check(name)
    env = _env_name(spec)
    if env:
        return os.environ[env], "env:" + env
    v = _read().get(name)
    return (v, "stored") if v else (None, "")


def agent_env(agent: str) -> dict:
    """Environment variables to add when Form Studio starts this agent's CLI."""
    d = _read()
    return {spec["env"]: d[name] for name, spec in KNOWN.items()
            if agent in spec["agents"] and d.get(name) and not os.environ.get(spec["env"])}


def main(argv=None) -> int:
    """form secrets [status] | set NAME (reads the value from stdin or a hidden prompt) | clear NAME"""
    import getpass
    import sys
    argv = list(argv or [])

    def out(o):
        print(json.dumps(o, indent=1, ensure_ascii=False))
    try:
        if not argv or argv == ["status"]:
            out({"file": str(path()), "keys": list(status().values())})
            return 0
        if len(argv) == 2 and argv[0] == "set":
            # never from the command line: it would end up in the shell history
            v = sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass(f"{_check(argv[1])['label']}: ")
            out(set_value(argv[1], v))
            return 0
        if len(argv) == 2 and argv[0] == "clear":
            out(clear(argv[1]))
            return 0
        raise SecretError("Usage: form secrets [status] | set NAME | clear NAME",
                          "set reads the value from stdin or asks for it; it is never taken from the command line.")
    except SecretError as e:
        print(json.dumps({"error": e.public()}, ensure_ascii=False), file=sys.stderr)
        return 2
