"""Qwen Code, headless: `qwen -p … -o stream-json --include-partial-messages` (Claude Code's stream shape:
system/init with the model id, assistant, user tool_result, stream_event deltas, result).

Not yet verified with a live run. It follows `qwen --help` (Qwen Code 0.28.0) and its stream-json output adapter; the
stream parser is tested with samples in that shape. FORM's MCP server is passed with `--mcp-config` (inline JSON;
nothing is written to the user's settings). Shell commands and file edits need an approval nobody can give in a
headless run, so they are refused; FORM's server is marked trusted so its tools run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import Adapter, Parser, Run, read_json, setting
from .claude import ClaudeParser

KEY_VARS = ("OPENAI_API_KEY", "DASHSCOPE_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


class QwenParser(ClaudeParser):
    session_totals = False                 # not known for Qwen Code: its result is read as this run's own cost

    def feed(self, line: str) -> list[dict]:
        out = super().feed(line)
        if any(e["t"] == "end" for e in out):
            try:
                e = json.loads(line)
            except ValueError:
                return out
            er = e.get("error")
            if e.get("is_error") and isinstance(er, dict) and er.get("message"):
                for ev in out:
                    if ev["t"] == "end":
                        ev["error"] = er["message"]
        return out


class Qwen(Adapter):
    id, label, cli = "qwen", "Qwen Code", "qwen"
    install_hint = "Install Qwen Code (qwen) and give it an API key to use it here."
    verified = "not run: not yet verified with a live reply"
    images, cost = False, False

    def signin(self, cfg, exe):
        for v in KEY_VARS:
            if os.environ.get(v):
                return {"signed_in": True, "how": f"{v} is set in the environment."}
        home = Path(os.environ.get("QWEN_HOME") or Path.home() / ".qwen")
        try:
            st = json.loads((home / "settings.json").read_text(encoding="utf-8"))
            kind = ((st.get("security") or {}).get("auth") or {}).get("selectedType")
            if kind:
                return {"signed_in": True, "how": f"Qwen Code is set to sign in with {kind}."}
        except (OSError, ValueError, AttributeError):
            pass
        return {"signed_in": False, "how": "No API key found. Set one up by running `qwen` once in a terminal."}

    def models(self, cfg, exe):
        home = Path(os.environ.get("QWEN_HOME") or Path.home() / ".qwen")
        own = setting(read_json(home / "settings.json"), "model", "name")
        row = {"id": "default", "label": "Default", "note": "Whatever Qwen Code is set to use"}
        if own:
            row.update(configured=own, note=f"From your Qwen Code settings: {own}")
        return [row]

    def command(self, run: Run, exe: str) -> list[str]:
        mcp = {"mcpServers": {"form": dict(run.mcp, trust=True, timeout=int(run.tool_timeout_s * 1000))}}
        cmd = [exe, "-p", run.message, "-o", "stream-json", "--include-partial-messages",
               "--mcp-config", json.dumps(mcp), "--allowed-mcp-server-names", "form",
               "--approval-mode", "default", "--append-system-prompt", run.system]
        if run.model and run.model != "default":
            cmd += ["-m", run.model]
        if run.session:
            cmd += ["-r", run.session]
        return cmd

    def parser(self) -> Parser:
        return QwenParser()
