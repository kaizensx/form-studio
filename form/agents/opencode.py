"""OpenCode, headless: `opencode run --format json …` (JSON Lines: text, tool_use, step_start, step_finish,
error; every line carries sessionID).

Not yet verified with a live run. It follows `opencode run --help` (OpenCode 1.19.6) and its run command's source; the stream parser is
tested with samples in that shape. OpenCode prints a text part only when it is finished (no live typing) and a tool
only when it has returned; the stream never names the model, so it is read afterwards with `opencode export`.
FORM's MCP server and the permissions (Form Studio's tools allowed, everything else refused) are passed in
OPENCODE_CONFIG_CONTENT for this run only; the user's config files are not touched.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .base import Adapter, Parser, Run, short, tool_name

_LISTS: dict = {}


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "opencode"


def _find(obj, key):
    """The last value of `key` anywhere in a JSON tree."""
    found = None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                found = v
            else:
                found = _find(v, key) or found
    elif isinstance(obj, list):
        for v in obj:
            found = _find(v, key) or found
    return found


class OpenCodeParser(Parser):
    def __init__(self):
        self.session: str | None = None
        self.started = False
        self.turns = 0
        self.cost: float | None = None
        self.error: str | None = None

    def feed(self, line: str) -> list[dict]:
        try:
            e = json.loads(line)
        except ValueError:
            return []
        if not isinstance(e, dict):
            return []
        out = []
        if e.get("sessionID") and e["sessionID"] != self.session:
            self.session = e["sessionID"]
            out.append({"t": "session", "session": self.session})
        if not self.started:
            self.started = True
            out.append({"t": "start", "model": None, "session": self.session})
        t, part = e.get("type"), e.get("part") or {}
        if t == "text" and str(part.get("text") or "").strip():
            out.append({"t": "text", "text": part["text"]})
        elif t == "tool_use":
            st = part.get("state") or {}
            name = str(part.get("tool") or "")
            name = name[len("form_"):] if name.startswith("form_") else tool_name(name)
            iid = part.get("callID") or part.get("id")
            self.turns += 1
            ok = st.get("status") == "completed"
            txt = st.get("output") if ok else st.get("error")
            txt = txt if isinstance(txt, str) else json.dumps(txt, ensure_ascii=False, default=str) if txt is not None else ""
            out += [{"t": "tool", "id": iid, "name": name, "input": short(st.get("input"))},
                    {"t": "result", "id": iid, "ok": ok, "image": False, "text": txt[:300], "full": txt}]
        elif t == "step_finish" and isinstance(part.get("cost"), (int, float)):
            self.cost = (self.cost or 0.0) + float(part["cost"])
        elif t == "error":
            er = e.get("error") or {}
            msg = ((er.get("data") or {}).get("message") or er.get("name")) if isinstance(er, dict) else str(er)
            self.error = str(msg or e.get("message") or "OpenCode reported an error")
        return out

    def finish(self) -> list[dict]:
        return [{"t": "end", "cost_usd": self.cost, "turns": self.turns, "session": self.session, "error": self.error}]


class OpenCode(Adapter):
    id, label, cli = "opencode", "OpenCode", "opencode"
    install_hint = "Install OpenCode (opencode) and connect a model provider to use it here."
    verified = "not run: not yet verified with a live reply"
    images, cost = True, True

    def _providers(self) -> list[str]:
        try:
            d = json.loads((_data_home() / "auth.json").read_text(encoding="utf-8"))
            return list(d) if isinstance(d, dict) else []
        except (OSError, ValueError):
            return []

    def signin(self, cfg, exe):
        ps = self._providers()
        if ps:
            return {"signed_in": True, "how": "Connected providers: " + ", ".join(ps[:4]) + "."}
        return {"signed_in": None, "how": "No provider is connected; OpenCode's free models may still answer. "
                                          "Run `opencode auth login` in a terminal to add one."}

    def models(self, cfg, exe):
        """`opencode models` lists provider/model ids; only the providers you connected (and OpenCode's own) are shown."""
        out = [{"id": "default", "label": "Default", "note": "Whatever OpenCode is set to use"}]
        if exe not in _LISTS:
            try:
                r = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
                                   encoding="utf-8", errors="replace")
                _LISTS[exe] = [ln.strip() for ln in (r.stdout or "").splitlines() if "/" in ln and " " not in ln.strip()]
            except (OSError, subprocess.SubprocessError):
                _LISTS[exe] = []
        mine = set(self._providers()) | {"opencode"}
        ids = [m for m in _LISTS[exe] if m.split("/", 1)[0] in mine][:40]
        for m in ids:
            out.append({"id": m, "label": self.model_label(m), "note": m + " (from `opencode models`)"})
        return out

    def run_env(self, run: Run) -> dict:
        perm = {"*": "deny", "form_*": "allow"}
        if run.files:
            perm["read"] = "allow"
        if run.web:
            perm["webfetch"] = "allow"
        conf = {"mcp": {"form": {"type": "local", "command": [run.mcp.get("command", "")] + list(run.mcp.get("args", [])),
                                 "environment": run.mcp.get("env", {}), "enabled": True,
                                 "timeout": int(run.tool_timeout_s * 1000)}},
                "permission": perm}
        return {"OPENCODE_CONFIG_CONTENT": json.dumps(conf)}

    def command(self, run: Run, exe: str) -> list[str]:
        # no system-prompt flag: FORM's standing instructions open the first message of a session
        prompt = run.message if run.session else (run.system + "\n\n" + run.message if run.system else run.message)
        if prompt.startswith("-"):
            prompt = " " + prompt                      # never read as an option
        cmd = [exe, "run", "--format", "json"]
        if run.model and run.model != "default":
            cmd += ["-m", run.model]
        if run.session:
            cmd += ["-s", run.session]
        for img in run.images:
            cmd += ["-f", str(img)]
        cmd.append(prompt)
        return cmd

    def resolve_model(self, session):
        exe = self.executable({})
        if not exe or not session:
            return None
        try:
            r = subprocess.run([exe, "export", str(session)], capture_output=True, text=True, timeout=20,
                               stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
            text = r.stdout or ""
            data = json.loads(text[text.find("{"):]) if "{" in text else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        model, prov = _find(data, "modelID"), _find(data, "providerID")
        return f"{prov}/{model}" if model and prov else model

    def parser(self) -> Parser:
        return OpenCodeParser()
