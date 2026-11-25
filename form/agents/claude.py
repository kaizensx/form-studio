"""Claude Code, headless: `claude -p … --output-format stream-json`.

Tools: FORM's MCP tools; web search and fetch when enabled; Read only when the message has attachments, and then
only for the conversation's own folder (the working directory of the run). No shell, no file edits.
`--restricted` (when the installed CLI has it) also keeps the user's own hooks, plugins and settings files out of
the run and confines the file tools to that folder.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .base import LIVE_TEXT_MAX, Adapter, Parser, Run, help_text, read_json, short, tool_name

# Aliases the Claude Code documentation lists for --model; the CLI resolves each to its current model.
# Anything `claude --help` itself names (e.g. 'fable') is added in front of these at run time.
DOCUMENTED_ALIASES = ("opus", "sonnet", "haiku")


# Claude Code's result event: `total_cost_usd` covers the whole session when a run resumes one (the session's earlier
# spend is restored from its transcript), so summing it over the runs of one conversation counts earlier replies again.
# Before 2.1.277 a resumed `claude -p` started its totals at zero, so the value covered that run only.
# https://code.claude.com/docs/en/agent-sdk/cost-tracking ("Accumulate costs across multiple calls")
SESSION_TOTALS_SINCE = (2, 1, 277)


def _version(text) -> tuple | None:
    m = re.match(r"\s*(\d+)\.(\d+)\.(\d+)", str(text or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def cost_scope(version) -> str:
    """"session" when this Claude Code's total_cost_usd includes the resumed session's earlier spend, else "call".
    A CLI that does not say its version is read as the current behaviour."""
    v = _version(version)
    return "call" if v is not None and v < SESSION_TOTALS_SINCE else "session"


class ClaudeParser(Parser):
    #: total_cost_usd is a running session total (Claude Code); a CLI that only borrows the stream shape sets False
    session_totals = True

    def __init__(self):
        self.live: dict | None = None
        self.session: str | None = None
        self.version: str | None = None

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except ValueError:
            return []
        if not isinstance(e, dict):
            return []
        t, out = e.get("type"), []
        if t == "stream_event":
            ev = e.get("event", {})
            et = ev.get("type")
            if et == "content_block_start":
                cb = ev.get("content_block", {})
                kind = "tool" if cb.get("type") == "tool_use" else cb.get("type")
                self.live = {"kind": kind, "name": tool_name(cb.get("name", "")), "chars": 0, "text": ""}
            elif et == "content_block_delta" and self.live:
                d = ev.get("delta", {})
                chunk = d.get("partial_json") or d.get("text") or d.get("thinking") or ""
                self.live["chars"] += len(chunk)
                if d.get("type") == "text_delta":
                    self.live["text"] = (self.live["text"] + chunk)[-LIVE_TEXT_MAX:]
            elif et == "content_block_stop":
                self.live = None
            else:
                return []
            return [{"t": "live", "live": dict(self.live) if self.live else None}]
        if t == "system" and e.get("subtype") == "init":
            self.session = e.get("session_id") or self.session
            self.version = e.get("claude_code_version") or self.version
            out.append({"t": "start", "model": e.get("model"), "session": self.session})
        elif t == "assistant":
            for c in e.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    out.append({"t": "text", "text": c["text"]})
                elif c.get("type") == "tool_use":
                    out.append({"t": "tool", "id": c.get("id"), "name": tool_name(c.get("name", "")),
                                "input": short(c.get("input"))})
        elif t == "user":
            for c in (e.get("message", {}).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    cont = c.get("content")
                    cont = cont if isinstance(cont, list) else [{"type": "text", "text": str(cont or "")}]
                    txt = " ".join(x.get("text", "") for x in cont if isinstance(x, dict) and x.get("type") == "text")
                    out.append({"t": "result", "id": c.get("tool_use_id"), "ok": not c.get("is_error"),
                                "image": any(isinstance(x, dict) and x.get("type") == "image" for x in cont),
                                "text": txt[:300], "full": txt})
        elif t == "result":
            self.session = e.get("session_id") or self.session
            err = (e.get("result") or e.get("subtype")) if e.get("is_error") else None
            end = {"t": "end", "cost_usd": e.get("total_cost_usd"), "turns": e.get("num_turns"),
                   "session": self.session, "error": err}
            if self.session_totals and e.get("total_cost_usd") is not None:
                # form/chat.py turns a session total into this run's own spend (cost_usd) with the total it saw before
                end.update(cost_total_usd=e["total_cost_usd"], cost_scope=cost_scope(self.version))
            out.append(end)
        return out


class Claude(Adapter):
    sandbox = ("you have no shell and cannot write files: only Form Studio's tools, web search and web fetch where they "
               "are on, and Read for the person's attached files.")
    id, label, cli = "claude", "Claude Code", "claude"
    # How Claude Code names FORM's MCP tools (the server is "form" in the run's --mcp-config). The instructions name
    # tools with this prefix for Claude: a bare "design_guide" is not a tool in its list ("No such tool available").
    tool_prefix = "mcp__form__"
    install_hint = "Install Claude Code (claude) to chat here. Everything else works without it."
    verified = "run on this Form Studio version"
    images, cost = True, True

    def models(self, cfg, exe):
        text = help_text(exe)
        m = re.search(r"--model <model>(.*?)(?:\n\s+-|\Z)", text, re.S)
        named = re.findall(r"'([a-z][a-z0-9.\-\[\]]*)'", m.group(1)) if m else []
        out = [dict({"id": "default", "label": "Default",
                     "note": "Claude Code chooses for your account. Its version shows here after a reply with Default."},
                    **self._configured(text))]
        for a in list(dict.fromkeys(named + list(DOCUMENTED_ALIASES))):
            out.append({"id": a, "label": a.capitalize(), "alias": True,
                        "note": "Alias for the latest " + a + " model. The version shows here after its first reply."})
        return out

    @staticmethod
    def _configured(help_out: str) -> dict:
        """The model Claude Code's own settings name for a run with no --model: ANTHROPIC_MODEL, else the "model" key
        of ~/.claude/settings.json (left out of the run by --restricted, so it does not count then)."""
        env = os.environ.get("ANTHROPIC_MODEL", "").strip()
        if env:
            return {"configured": env, "note": f"ANTHROPIC_MODEL is set to {env}"}
        if "--restricted" in help_out:
            return {}
        home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        own = read_json(home / "settings.json").get("model")
        if isinstance(own, str) and own.strip():
            return {"configured": own.strip(), "note": f"From your Claude Code settings: {own.strip()}"}
        return {}

    def efforts(self, cfg, exe):
        m = re.search(r"--effort <level>.*?\(([a-z, \n]+)\)", help_text(exe), re.S)
        return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []

    def command(self, run: Run, exe: str) -> list[str]:
        text = help_text(exe)
        mcp_file = Path(run.scratch) / "mcp.json"
        mcp_file.write_text(json.dumps({"mcpServers": {"form": run.mcp}}), encoding="utf-8")
        tools = (["WebSearch", "WebFetch"] if run.web else []) + (["Read"] if run.files else [])
        if self.tool_search(run) != "false":
            # with tool search on, Claude Code defers most MCP tools behind ToolSearch; without it in --tools the
            # deferred tools cannot be reached (the agent then called bare names: "No such tool available")
            tools.append("ToolSearch")
        allowed = ["mcp__form__*"] + [t for t in tools if t != "Read"]
        if run.files:
            # absolute paths in permission rules start with a double slash
            allowed.append("Read(/" + Path(run.cwd).as_posix().rstrip("/") + "/**)")
        cmd = [exe, "-p", run.message, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--mcp-config", str(mcp_file), "--strict-mcp-config",
               "--tools", ",".join(tools) if tools else "",
               "--allowedTools", ",".join(allowed),
               "--append-system-prompt", run.system,
               "--max-budget-usd", str(run.budget_usd)]
        if "--restricted" in text:
            cmd.append("--restricted")
        if run.model and run.model != "default":
            cmd += ["--model", run.model]
        if run.effort and "--effort" in text:
            cmd += ["--effort", run.effort]
        if run.session:
            cmd += ["--resume", run.session]
        return cmd

    @staticmethod
    def tool_search(run: Run) -> str:
        """"auto" (the default: Form Studio's tools marked anthropic/alwaysLoad load up front, the rest are found
        with ToolSearch) or "false" (every tool up front, as before 1.1.0): [chat] tool_search, or
        FORM_TOOL_SEARCH=false for one run."""
        v = (os.environ.get("FORM_TOOL_SEARCH") or getattr(run, "tool_search", "") or "auto").strip().lower()
        return "false" if v in ("false", "off", "0", "no") else "auto"

    def run_env(self, run: Run) -> dict:
        return {"ENABLE_TOOL_SEARCH": self.tool_search(run)}

    def parser(self) -> Parser:
        return ClaudeParser()
