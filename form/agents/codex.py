"""Codex, headless: `codex exec --json …` (JSON Lines: thread.started, turn.*, item.*, error).

FORM's MCP server is passed with `-c mcp_servers.form.*` overrides, so nothing is written to the user's Codex
config. The sandbox is read-only: Codex can read the attachment folder and call FORM's tools; it cannot edit
files. Models come from Codex's own model cache file and config; none are made up here.
Codex reports token counts, not money, so FORM shows no cost for these runs.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

from .base import Adapter, Parser, Run, short, tool_name


def _home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _toml(v) -> str:
    """A Python value as a TOML value for `-c key=value`."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))} = {_toml(x)}" for k, x in v.items()) + "}"
    return json.dumps(str(v), ensure_ascii=False)


class CodexParser(Parser):
    def __init__(self):
        self.session: str | None = None
        self.turns = 0
        self.error: str | None = None
        self.started = False

    def _item(self, it: dict, done: bool) -> list[dict]:
        kind, iid = it.get("type"), it.get("id")
        if kind == "agent_message":
            return [{"t": "text", "text": it.get("text", "")}] if done and (it.get("text") or "").strip() else []
        if kind == "reasoning":
            return [] if done else [{"t": "live", "live": {"kind": "thinking", "name": "", "chars": 0, "text": ""}}]
        if kind == "mcp_tool_call":
            name = it.get("tool", "") if it.get("server") in (None, "form") else f"{it.get('server')}.{it.get('tool', '')}"
            if not done:
                self.turns += 1
                return [{"t": "tool", "id": iid, "name": tool_name(name), "input": short(it.get("arguments"))},
                        {"t": "live", "live": {"kind": "tool", "name": tool_name(name), "chars": 0, "text": ""}}]
            res, err = it.get("result") or {}, it.get("error")
            cont = res.get("content") if isinstance(res, dict) else None
            cont = cont if isinstance(cont, list) else []
            txt = " ".join(x.get("text", "") for x in cont if isinstance(x, dict) and x.get("type") == "text")
            if err:
                txt = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return [{"t": "result", "id": iid, "ok": not err and it.get("status") != "failed",
                     "image": any(isinstance(x, dict) and x.get("type") == "image" for x in cont),
                     "text": txt[:300], "full": txt}, {"t": "live", "live": None}]
        if kind in ("command_execution", "web_search", "file_change"):
            label = {"command_execution": "shell", "web_search": "web_search", "file_change": "file_change"}[kind]
            if not done:
                self.turns += 1
                return [{"t": "tool", "id": iid, "name": label, "input": short(it.get("command") or it.get("query") or "")}]
            ok = it.get("status") != "failed" and it.get("exit_code") in (None, 0)
            txt = str(it.get("aggregated_output") or "")
            return [{"t": "result", "id": iid, "ok": ok, "image": False, "text": txt[:300], "full": txt}]
        if kind == "error" and done:
            # An item-level error does not end the turn (a failed turn arrives as turn.failed). Codex uses it for
            # notices such as "Under-development features enabled": show those quietly, not as a failure.
            return [{"t": "act", "by": "Codex notice", "text": str(it.get("message", ""))[:400]}]
        return []

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except ValueError:
            return []
        if not isinstance(e, dict):
            return []
        t = e.get("type")
        if t == "thread.started":
            self.session = e.get("thread_id") or self.session
            return [{"t": "session", "session": self.session}]
        if t == "turn.started" and not self.started:
            self.started = True
            return [{"t": "start", "model": None, "session": self.session}]
        if t in ("item.started", "item.completed"):
            it = e.get("item") or {}
            done = t == "item.completed"
            out = self._item(it, done)
            if done and it.get("type") in ("web_search",) and not any(x["t"] == "tool" for x in out):
                pass
            return out
        if t == "turn.completed":
            return [{"t": "end", "cost_usd": None, "turns": self.turns, "session": self.session, "error": self.error,
                     "usage": e.get("usage")}]
        if t == "turn.failed":
            err = e.get("error") or {}
            self.error = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return [{"t": "end", "cost_usd": None, "turns": self.turns, "session": self.session, "error": self.error}]
        if t == "error":
            self.error = str(e.get("message", ""))
            return []
        return []


class Codex(Adapter):
    id, label, cli = "codex", "Codex", "codex"
    install_hint = "Install the Codex CLI (codex) and sign in to use it here."
    verified = "follows `codex exec --help` and the Codex non-interactive documentation; stream parsing is tested with recorded samples"
    images, cost = True, False

    def _config(self) -> dict:
        try:
            return tomllib.loads((_home() / "config.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def models(self, cfg, exe):
        conf = self._config()
        own = conf.get("model")
        out = [{"id": "default", "label": "Default",
                "note": f"From your Codex config: {own}" if own else "Whatever Codex is set to use"}]
        if isinstance(own, str) and own:
            out[0].update(configured=own, configured_label=self.model_label(own))
        try:
            cache = json.loads((_home() / "models_cache.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        for m in cache.get("models", []) if isinstance(cache, dict) else []:
            if not isinstance(m, dict) or not m.get("slug") or m.get("visibility") not in (None, "list"):
                continue
            out.append({"id": m["slug"], "label": m.get("display_name") or m["slug"],
                        "note": (m.get("description") or "") + " (from Codex's model list on this computer)",
                        "efforts": [x.get("effort") for x in m.get("supported_reasoning_levels") or [] if isinstance(x, dict) and x.get("effort")]})
        return out

    def signin(self, cfg, exe):
        if os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEX_API_KEY"):
            return {"signed_in": True, "how": "An OpenAI API key is set in the environment."}
        if (_home() / "auth.json").exists():
            return {"signed_in": True, "how": "Signed in to Codex on this computer."}
        return {"signed_in": False, "how": "Not signed in. Run `codex login` once in a terminal."}

    def resolve_model(self, session):
        """Codex's stream does not name the model; its own session file does (turn_context.model)."""
        if not session or not re.fullmatch(r"[0-9a-fA-F-]{8,64}", str(session)):
            return None
        files = sorted((_home() / "sessions").glob(f"*/*/*/rollout-*{session}.jsonl"))
        model = None
        for f in files[-1:]:
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        if '"turn_context"' not in line:
                            continue
                        try:
                            p = json.loads(line).get("payload") or {}
                        except ValueError:
                            continue
                        model = p.get("model") or model
            except OSError:
                pass
        return model

    def model_label(self, model_id):
        try:
            cache = json.loads((_home() / "models_cache.json").read_text(encoding="utf-8"))
            for m in cache.get("models", []):
                if isinstance(m, dict) and m.get("slug") == model_id and m.get("display_name"):
                    return m["display_name"]
        except (OSError, ValueError, AttributeError):
            pass
        return super().model_label(model_id)

    def efforts(self, cfg, exe):
        # model_reasoning_effort is a Codex config key; per-model lists come with each model above
        return ["low", "medium", "high"]

    def command(self, run: Run, exe: str) -> list[str]:
        cmd = [exe, "exec"]
        if run.session:
            cmd.append("resume")
        cmd += ["--json", "--skip-git-repo-check",
                "-c", "sandbox_mode=" + _toml("read-only"),
                "-c", "mcp_servers.form.command=" + _toml(run.mcp.get("command", "")),
                "-c", "mcp_servers.form.args=" + _toml(run.mcp.get("args", [])),
                "-c", "mcp_servers.form.env=" + _toml(run.mcp.get("env", {})),
                # Codex stops waiting for an MCP tool after tool_timeout_sec; ask_user waits for a person
                "-c", "mcp_servers.form.tool_timeout_sec=" + _toml(int(run.tool_timeout_s))]
        if run.model and run.model != "default":
            cmd += ["-m", run.model]
        if run.effort:
            cmd += ["-c", "model_reasoning_effort=" + _toml(run.effort)]
        for img in run.images:
            cmd += ["-i", str(img)]
        # Codex has no system-prompt flag: FORM's standing instructions open the first message of a session
        prompt = run.message if run.session else (run.system + "\n\n" + run.message if run.system else run.message)
        if run.images:
            cmd.append("--")           # -i takes several files; end the list before the positional arguments
        if run.session:
            cmd.append(run.session)
        cmd.append(prompt)
        return cmd

    def parser(self) -> Parser:
        return CodexParser()
