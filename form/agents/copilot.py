"""GitHub Copilot CLI, headless: `copilot -p … --output-format json --stream on` (JSON Lines of session events:
session.start, assistant.message_delta, assistant.message, tool.execution_start, tool.execution_complete,
assistant.usage, session.error, result).

Not yet verified with a live run. It follows `copilot --help` and `copilot help permissions` (Copilot CLI 1.0.113)
and the session event schema in GitHub's Copilot SDK; the parser is tested with samples in that shape. FORM's MCP server is added for this
run only with `--additional-mcp-config`; Form Studio's tools are allowed, shell and file writes are denied, and
Copilot's own question form is off (Form Studio's ask_user is used instead).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .base import LIVE_TEXT_MAX, Adapter, Parser, Run, help_text, short, tool_name

TOKEN_VARS = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")


class CopilotParser(Parser):
    def __init__(self):
        self.session: str | None = None
        self.model: str | None = None
        self.text = ""
        self.turns = 0
        self.error: str | None = None
        self.ended = False
        self.started = False

    def _flush(self) -> list[dict]:
        t, self.text = self.text, ""
        return [{"t": "text", "text": t}, {"t": "live", "live": None}] if t.strip() else []

    def _end(self, error=None) -> list[dict]:
        self.ended = True
        return self._flush() + [{"t": "end", "cost_usd": None, "turns": self.turns, "session": self.session,
                                 "error": error or self.error, "model": self.model}]

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except ValueError:
            return []
        if not isinstance(e, dict):
            return []
        t, d = e.get("type"), e.get("data") if isinstance(e.get("data"), dict) else {}
        if t in ("session.start", "session.resume"):
            self.session = d.get("sessionId") or self.session
            self.model = d.get("selectedModel") or self.model
            if self.started:
                return [{"t": "session", "session": self.session}]
            self.started = True
            return [{"t": "start", "model": self.model, "session": self.session}]
        if t == "session.model_change":
            self.model = d.get("newModel") or self.model
            return []
        if t == "assistant.message_delta":
            self.text = (self.text + str(d.get("deltaContent") or ""))[-LIVE_TEXT_MAX:]
            return [{"t": "live", "live": {"kind": "text", "name": "", "chars": len(self.text), "text": self.text}}]
        if t == "assistant.message":
            self.model = d.get("model") or self.model
            self.text = ""
            c = str(d.get("content") or "")
            return ([{"t": "text", "text": c}] if c.strip() else []) + [{"t": "live", "live": None}]
        if t == "tool.execution_start":
            self.turns += 1
            name = d.get("mcpToolName") if d.get("mcpServerName") == "form" else d.get("toolName")
            out = self._flush() + [{"t": "tool", "id": d.get("toolCallId"), "name": tool_name(str(name or "")),
                                    "input": short(d.get("arguments"))}]
            return out + [{"t": "live", "live": {"kind": "tool", "name": tool_name(str(name or "")), "chars": 0, "text": ""}}]
        if t == "tool.execution_complete":
            res, err = d.get("result") or {}, d.get("error")
            txt = res.get("content") if isinstance(res, dict) else res
            if err:
                txt = err.get("message") if isinstance(err, dict) else str(err)
            txt = txt if isinstance(txt, str) else json.dumps(txt, ensure_ascii=False, default=str) if txt is not None else ""
            return [{"t": "result", "id": d.get("toolCallId"), "ok": bool(d.get("success")) and not err, "image": False,
                     "text": txt[:300], "full": txt}, {"t": "live", "live": None}]
        if t == "assistant.usage":
            self.model = d.get("model") or self.model
            return []
        if t == "session.error":
            self.error = str(d.get("message") or d.get("errorType") or "Copilot reported an error")
            return []
        if t == "result":
            code = e.get("exitCode")
            return self._end(None if code in (None, 0) else (self.error or f"Copilot CLI exited with code {code}"))
        return []

    def finish(self) -> list[dict]:
        return [] if self.ended else self._end()


class Copilot(Adapter):
    id, label, cli = "copilot", "GitHub Copilot CLI", "copilot"
    install_hint = "Install GitHub Copilot CLI (copilot) and sign in to use it here."
    verified = "not run: not yet verified with a live reply"
    images, cost = True, False

    def signin(self, cfg, exe):
        for v in TOKEN_VARS:
            if os.environ.get(v):
                return {"signed_in": True, "how": f"{v} is set in the environment."}
        home = Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")
        try:
            conf = json.loads((home / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"signed_in": False, "how": "Not signed in. Run `copilot` once in a terminal and use /login."}
        users = [v for k, v in conf.items() if "user" in k.lower() and v] if isinstance(conf, dict) else []
        if users:
            return {"signed_in": True, "how": "Signed in to GitHub in Copilot CLI."}
        return {"signed_in": None, "how": "Sign-in could not be confirmed. If replies fail, run `copilot` and use /login."}

    def models(self, cfg, exe):
        """The choices `copilot --help` lists for --model, when it lists them."""
        out = [{"id": "default", "label": "Default", "note": "Whatever Copilot CLI is set to use"}]
        m = re.search(r"--model <model>(.*?)(?:\n\s+-|\Z)", help_text(exe), re.S)
        ch = re.search(r"choices:\s*(.*?)\)", m.group(1), re.S) if m else None
        from .models import pretty
        for mid in dict.fromkeys(re.findall(r'"([A-Za-z0-9][A-Za-z0-9.\-_:/]*)"', ch.group(1)) if ch else []):
            out.append({"id": mid, "label": pretty(mid), "note": mid + " (from `copilot --help`)"})
        return out

    def efforts(self, cfg, exe):
        m = re.search(r"--reasoning-effort <level>.*?possible values: ([a-z, ]+)\]", help_text(exe), re.S)
        return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []

    def command(self, run: Run, exe: str) -> list[str]:
        mcp = {"mcpServers": {"form": {"type": "local", "command": run.mcp.get("command", ""),
                                       "args": list(run.mcp.get("args", [])), "env": run.mcp.get("env", {}),
                                       "tools": ["*"], "timeout": int(run.tool_timeout_s * 1000)}}}
        prompt = run.message if run.session else (run.system + "\n\n" + run.message if run.system else run.message)
        cmd = [exe, "-p", prompt, "--output-format", "json", "--stream", "on",
               "--additional-mcp-config", json.dumps(mcp), "--disable-builtin-mcps", "--no-ask-user",
               "--allow-tool=form", "--deny-tool=shell", "--deny-tool=write"]
        if run.web:
            cmd.append("--allow-all-urls")
        if run.model and run.model != "default":
            cmd += ["--model", run.model]
        if run.effort:
            cmd += ["--reasoning-effort", run.effort]
        for img in run.images:
            cmd += ["--attachment", str(img)]
        if run.session:
            cmd += ["--resume", run.session]
        return cmd

    def parser(self) -> Parser:
        return CopilotParser()
