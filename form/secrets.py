"""Keys an agent CLI needs, kept by FORM so nobody has to open a terminal to set an environment variable.

Today that is one key: Gemini CLI runs headless only when it is signed in, and its only way to sign in without its
own interactive screen is an API key in GEMINI_API_KEY. The Settings sheet (Chat tab) and `form secrets` store it here.

Rules:
- One JSON file, `secrets.json` in FORM's user folder (`~/.config/form-studio`, or $FORM_SECRETS for tests), readable
  by this user only. Never studio.toml: that file is meant to be shared and backed up.
- A value is never returned by the API, the CLI or MCP: only whether it is set. MCP has no way to read or write it.
- A key is handed to its own agent only, as an environment variable, and only when that variable is not already set.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import fsutil

KNOWN = {
    "gemini_api_key": {
        "label": "Gemini API key",
        "agent": "gemini",
        "env": "GEMINI_API_KEY",
        "help": "Lets Gemini CLI run inside Form Studio. Create one at Google AI Studio; usage is billed to that Google account.",
        "url": "https://aistudio.google.com/apikey",
    },
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


def status() -> dict:
    """{name: {label, help, url, agent, set, from_env}}. Never the value."""
    d = _read()
    out = {}
    for name, spec in KNOWN.items():
        out[name] = {"name": name, "label": spec["label"], "help": spec["help"], "url": spec["url"], "agent": spec["agent"],
                     "set": bool(d.get(name)), "from_env": bool(os.environ.get(spec["env"]))}
    return out


def agent_env(agent: str) -> dict:
    """Environment variables to add when FORM starts this agent's CLI."""
    d = _read()
    return {spec["env"]: d[name] for name, spec in KNOWN.items()
            if spec["agent"] == agent and d.get(name) and not os.environ.get(spec["env"])}


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
