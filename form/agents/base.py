"""What FORM needs from an agent CLI to chat through it.

An adapter turns one message into a command line for a headless agent run, and turns the CLI's output stream into
FORM's own events, so the conversation store and the interface never see a vendor format:

    {"t": "start",  "model": "...", "session": "..."}          the CLI reported which model it resolved
    {"t": "text",   "text": "..."}                             a finished piece of the reply
    {"t": "tool",   "id": "...", "name": "render", "input": "view=sheet"}
    {"t": "result", "id": "...", "ok": true, "image": false, "text": "...", "full": "..."}
    {"t": "end",    "cost_usd": 0.12 | None, "turns": 4, "session": "...", "error": None}
    {"t": "error",  "text": "..."}
    {"t": "live",   "live": {...} | None}                      not stored: what is being produced right now

Model names are never invented here: an adapter lists only what its CLI or the CLI's own files document, plus
"default" (no model flag: the CLI decides) and whatever id the user types.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

LIVE_TEXT_MAX = 24000


@dataclass
class Run:
    """One message to one agent."""
    message: str                                  # the prompt, attachment notes included
    system: str = ""                              # FORM's standing instructions
    model: str = ""                               # "" or "default": let the CLI choose
    effort: str = ""                              # "" = the CLI's default
    session: str | None = None                    # the CLI's own session id, to continue it
    cwd: Path = Path(".")                         # the conversation's folder; the only folder the agent may read
    scratch: Path = Path(".")                     # temporary folder for config files, removed after the run
    mcp: dict = field(default_factory=dict)       # {"command": str, "args": [...], "env": {...}} for FORM's MCP server
    web: bool = True
    budget_usd: float = 3.0
    images: list = field(default_factory=list)    # absolute paths of attached images
    files: list = field(default_factory=list)     # absolute paths of every attachment the agent may read


class Parser:
    """Feed it the CLI's stdout one line at a time; it returns FORM events."""

    def feed(self, line: str) -> list[dict]:
        raise NotImplementedError


class Adapter:
    id = ""
    label = ""
    cli = ""                      # default command name
    install_hint = ""
    verified = ""                 # how this adapter was checked; shown as it is
    images = False                # the CLI takes images as input
    cost = False                  # the CLI reports cost in money

    # -- discovery -----------------------------------------------------------
    def executable(self, cfg: dict) -> str | None:
        c = cfg.get("chat", {})
        name = c.get(f"{self.id}_cli") or (c.get("cli") if self.id == "claude" else None) or self.cli
        return shutil.which(name)

    def models(self, cfg: dict, exe: str | None) -> list[dict]:
        """[{id, label, note, efforts?}] . The first entry is always the CLI's own default."""
        return [{"id": "default", "label": "Default", "note": f"Whatever {self.label} is set to use"}]

    def efforts(self, cfg: dict, exe: str | None) -> list[str]:
        return []

    def status(self, cfg: dict) -> dict:
        exe = self.executable(cfg)
        out = {"id": self.id, "label": self.label, "available": bool(exe), "cli": exe, "why": None,
               "images": self.images, "reports_cost": self.cost, "verified": self.verified}
        if not exe:
            out["why"] = self.install_hint
            out["models"], out["efforts"] = [], []
            return out
        try:
            out["models"], out["efforts"] = self.models(cfg, exe), self.efforts(cfg, exe)
        except Exception as e:                                    # a broken CLI must not break the app
            out["models"], out["efforts"] = Adapter.models(self, cfg, exe), []
            out["why"] = f"Could not read the model list ({type(e).__name__}); Default and a custom id still work."
        return out

    # -- one run -------------------------------------------------------------
    def command(self, run: Run, exe: str) -> list[str]:
        raise NotImplementedError

    def parser(self) -> Parser:
        raise NotImplementedError

    def resume_failed(self, stderr: str, events: list[dict]) -> bool:
        """True when the run died because the CLI no longer has the session (FORM then retries without it)."""
        s = (stderr or "").lower()
        return any(k in s for k in ("no conversation found", "session not found", "no session", "no rollout found",
                                    "could not find session", "no saved session"))


# ---- shared helpers ------------------------------------------------------------------------------------------------

def short(obj, n: int = 220) -> str:
    """A tool call's arguments on one line; design source is summarised, never shown in full."""
    if not obj:
        return ""
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            if k == "source":
                parts.append(f"source=<{len(str(v).splitlines())} lines>")
            else:
                parts.append(f"{k}={json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}")
        s = " ".join(parts)
    else:
        s = str(obj)
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_name(name: str) -> str:
    """FORM's tools without the MCP prefix each CLI adds (mcp__form__render, form.render, form__render)."""
    for p in ("mcp__form__", "form__", "form."):
        if name.startswith(p):
            return name[len(p):]
    return name


def help_text(exe: str, *args: str, timeout: float = 10) -> str:
    """`<cli> --help`, cached per executable for the life of the process."""
    key = (exe, args)
    if key not in _HELP:
        try:
            r = subprocess.run([exe, *args, "--help"], capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
            _HELP[key] = (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.SubprocessError):
            _HELP[key] = ""
    return _HELP[key]


_HELP: dict = {}
