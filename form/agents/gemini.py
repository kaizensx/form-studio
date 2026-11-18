"""Gemini CLI, headless: `gemini -p … --output-format stream-json` (JSON Lines: init, message, tool_use,
tool_result, error, result).

Not yet verified with a live reply (that needs a Gemini sign-in or API key). It follows the Gemini CLI
headless-mode reference and MCP settings documentation, and its stream parser is tested with samples in that
documented shape. FORM's MCP server goes into `.gemini/settings.json` inside
the conversation's own folder (project-level settings), never into the user's settings.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import LIVE_TEXT_MAX, Adapter, Parser, Run, short, tool_name

# What Gemini CLI prints when it has no way to sign in (seen with Gemini CLI 0.68.0, never signed in).
NOT_SIGNED_IN = ("please set an auth method", "gemini_api_key")


class GeminiParser(Parser):
    def __init__(self):
        self.session: str | None = None
        self.text = ""
        self.turns = 0

    def _flush(self) -> list[dict]:
        if not self.text.strip():
            self.text = ""
            return []
        out = [{"t": "text", "text": self.text}, {"t": "live", "live": None}]
        self.text = ""
        return out

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except ValueError:
            return []
        if not isinstance(e, dict):
            return []
        t = e.get("type")
        if t == "init":
            self.session = e.get("session_id") or self.session
            return [{"t": "start", "model": e.get("model"), "session": self.session}]
        if t == "message":
            if e.get("role") != "assistant":
                return []
            self.text = (self.text + str(e.get("content") or ""))[-LIVE_TEXT_MAX:]
            if e.get("delta"):
                return [{"t": "live", "live": {"kind": "text", "name": "", "chars": len(self.text), "text": self.text}}]
            return self._flush()
        if t == "tool_use":
            self.turns += 1
            return self._flush() + [{"t": "tool", "id": e.get("tool_id"), "name": tool_name(str(e.get("tool_name", ""))),
                                     "input": short(e.get("parameters"))}]
        if t == "tool_result":
            txt = e.get("output")
            txt = txt if isinstance(txt, str) else json.dumps(txt, ensure_ascii=False, default=str) if txt is not None else ""
            err = e.get("error")
            if err:
                txt = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return [{"t": "result", "id": e.get("tool_id"), "ok": e.get("status", "success") == "success" and not err,
                     "image": False, "text": txt[:300], "full": txt}]
        if t == "error":
            return [{"t": "error", "text": str(e.get("message", ""))}]
        if t == "result":
            err = None
            if e.get("status") not in (None, "success"):
                er = e.get("error")
                err = (er.get("message") if isinstance(er, dict) else er) or str(e.get("status"))
            return self._flush() + [{"t": "end", "cost_usd": None, "turns": self.turns, "session": self.session,
                                     "error": err, "usage": e.get("stats")}]
        return []


class Gemini(Adapter):
    id, label, cli = "gemini", "Gemini CLI", "gemini"
    install_hint = "Install the Gemini CLI (gemini) and sign in to use it here."
    verified = "not run: not yet verified with a live reply"
    images, cost = False, False

    def signin(self, cfg, exe):
        from ..installer import gemini_signed_in
        ok, how = gemini_signed_in(cfg)
        return {"signed_in": ok, "how": how}

    def explain(self, error: str) -> dict | None:
        s = (error or "").lower()
        if all(k in s for k in NOT_SIGNED_IN[:1]) or ("auth method" in s and "gemini" in s):
            return {"message": "Gemini CLI is not signed in, so it cannot answer.",
                    "hint": "Add a Gemini API key in Settings, Agents tab. Form Studio keeps it in a private file on this computer "
                            "and gives it only to Gemini CLI."}
        return None

    def command(self, run: Run, exe: str) -> list[str]:
        conf = Path(run.cwd) / ".gemini"
        conf.mkdir(parents=True, exist_ok=True)
        # trust: FORM's own tools run without a confirmation prompt (there is nobody to answer one in a headless run)
        (conf / "settings.json").write_text(json.dumps({"mcpServers": {"form": dict(run.mcp, trust=True, timeout=int(run.tool_timeout_s * 1000))}}, indent=1),
                                            encoding="utf-8")
        prompt = run.message if run.session else (run.system + "\n\n" + run.message if run.system else run.message)
        cmd = [exe, "-p", prompt, "--output-format", "stream-json", "--allowed-mcp-server-names", "form"]
        if run.model and run.model != "default":
            cmd += ["-m", run.model]
        if run.session:
            cmd += ["--resume", run.session]
        return cmd

    def parser(self) -> Parser:
        return GeminiParser()
