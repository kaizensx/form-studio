"""Cursor CLI, headless: `cursor-agent -p … --output-format stream-json --stream-partial-output` (JSON Lines:
system/init, assistant, tool_call started/completed, result).

NOT RUN: Cursor's CLI is installed only by its own script, which was not run on the machine this adapter was written
on. It follows Cursor's CLI reference (parameters, output format, MCP, permissions) and its parser is tested with
samples in that documented shape. FORM's MCP server goes into `.cursor/mcp.json` inside the conversation's own
folder, with `.cursor/cli.json` allowing only Form Studio's tools (shell and file writes denied); the user's own
Cursor settings are not touched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import LIVE_TEXT_MAX, Adapter, Parser, Run, short, tool_name


class CursorParser(Parser):
    def __init__(self):
        self.session: str | None = None
        self.text = ""
        self.turns = 0
        self.ended = False

    def _flush(self) -> list[dict]:
        t, self.text = self.text, ""
        return [{"t": "text", "text": t}, {"t": "live", "live": None}] if t.strip() else []

    @staticmethod
    def _call(tc: dict) -> tuple[str, dict, dict]:
        """(name, args, the call's own dict) from {"<x>ToolCall": {...}} or {"function": {...}}."""
        for k, v in (tc or {}).items():
            if isinstance(v, dict) and (k.endswith("ToolCall") or k == "function"):
                name = v.get("toolName") or v.get("name") or (k[:-len("ToolCall")] if k.endswith("ToolCall") else k)
                if v.get("providerIdentifier") not in (None, "form"):
                    name = f"{v['providerIdentifier']}.{name}"
                args = v.get("args") if v.get("args") is not None else v.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        pass
                return tool_name(str(name)), args, v
        return "tool", {}, {}

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except ValueError:
            return []
        if not isinstance(e, dict):
            return []
        t = e.get("type")
        self.session = e.get("session_id") or self.session
        if t == "system" and e.get("subtype") == "init":
            return [{"t": "start", "model": e.get("model"), "session": self.session}]
        if t == "assistant":
            txt = "".join(c.get("text", "") for c in (e.get("message") or {}).get("content", [])
                          if isinstance(c, dict) and c.get("type") == "text")
            if "timestamp_ms" in e and "model_call_id" not in e:          # a piece of text as it is written
                self.text = (self.text + txt)[-LIVE_TEXT_MAX:]
                return [{"t": "live", "live": {"kind": "text", "name": "", "chars": len(self.text), "text": self.text}}]
            if self.text:                                                  # the whole message again: already have it
                return self._flush()
            return [{"t": "text", "text": txt}] if txt.strip() else []
        if t == "tool_call":
            name, args, v = self._call(e.get("tool_call") or {})
            iid = e.get("call_id")
            if e.get("subtype") == "started":
                self.turns += 1
                return self._flush() + [{"t": "tool", "id": iid, "name": name, "input": short(args)},
                                        {"t": "live", "live": {"kind": "tool", "name": name, "chars": 0, "text": ""}}]
            res = v.get("result") or {}
            ok = isinstance(res, dict) and "success" in res and not res.get("error")
            body = res.get("success") if ok else (res.get("error") or res.get("failure") or res) if isinstance(res, dict) else res
            txt = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str)
            return [{"t": "result", "id": iid, "ok": ok, "image": False, "text": txt[:300], "full": txt},
                    {"t": "live", "live": None}]
        if t == "result":
            self.ended = True
            err = (e.get("result") or e.get("subtype")) if e.get("is_error") else None
            return self._flush() + [{"t": "end", "cost_usd": None, "turns": self.turns, "session": self.session,
                                     "error": err}]
        return []

    def finish(self) -> list[dict]:
        return self._flush() if not self.ended else []


class Cursor(Adapter):
    id, label, cli = "cursor", "Cursor CLI", "cursor-agent"
    install_hint = "Install Cursor's CLI (cursor-agent) and sign in to use it here."
    verified = "not run: written from Cursor's CLI documentation; the first real run is a test"
    images, cost = False, False

    def executable(self, cfg):
        import shutil
        c = cfg.get("chat", {})
        return shutil.which(c.get("cursor_cli") or "cursor-agent")

    def signin(self, cfg, exe):
        if os.environ.get("CURSOR_API_KEY"):
            return {"signed_in": True, "how": "CURSOR_API_KEY is set in the environment."}
        return {"signed_in": None, "how": "Sign-in is not checked here. If replies fail, run `cursor-agent login` once."}

    def command(self, run: Run, exe: str) -> list[str]:
        conf = Path(run.cwd) / ".cursor"
        conf.mkdir(parents=True, exist_ok=True)
        (conf / "mcp.json").write_text(json.dumps({"mcpServers": {"form": dict(run.mcp, type="stdio")}}, indent=1),
                                       encoding="utf-8")
        allow = ["Mcp(form:*)"] + (["Read(**)"] if run.files else []) + (["WebFetch(*)"] if run.web else [])
        (conf / "cli.json").write_text(json.dumps({"permissions": {"allow": allow, "deny": ["Shell(*)", "Write(**)"]}},
                                                  indent=1), encoding="utf-8")
        prompt = run.message if run.session else (run.system + "\n\n" + run.message if run.system else run.message)
        cmd = [exe, "-p", prompt, "--output-format", "stream-json", "--stream-partial-output",
               "--approve-mcps", "--trust", "--workspace", str(run.cwd)]
        if run.model and run.model != "default":
            cmd += ["--model", run.model]
        if run.session:
            cmd += ["--resume", run.session]
        return cmd

    def parser(self) -> Parser:
        return CursorParser()
