"""Chat in the bench: each message runs Claude Code headless on the user's own account, with FORM's tools.

The spawned agent talks to FORM through its own `form-mcp --no-bench` process over the same project folder,
so everything it does appears on the bench through the activity log, exactly as when you use Claude Code.
Allowed tools: FORM's MCP tools, plus web search/fetch for datasheets when enabled. No shell, no file edits.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

PROMPT = """\
You are working inside FORM, a design studio for 3D-printed parts. The user is looking at FORM's page: every FORM
tool you call shows up there live (3D model, drafts, checks, slice), so you do not need to describe geometry at length.
- Use FORM tools for all design work. Built-in recipes (dock, gridfinity, hook, planter, coupon): create_project.
  Anything else: call design_guide, then write the design as code with create_design; iterate with update_design.
- After creating or changing a design, render(view="sheet") and look at it; fix what is wrong before replying.
- Look up exact dimensions of commercial parts: find the official datasheet or mechanical drawing with web search,
  then open it with FORM's read_document (it shows PDF pages as images; web fetch loses a drawing's dimensions).
  Name the source. Put such numbers in params with group "brief" and the source in doc.
- Ask the user only for measurements that change the fit or safety, and only when you cannot find them.
- Reply briefly: what you made, the key numbers, what is assumed or unverified, and what the user should check.
  Slices are simulations and fit yields are models; say so. You cannot approve releases; point to the Release tab.
Current project on the page: {project}.
"""


def status(cfg: dict) -> dict:
    c = cfg.get("chat", {})
    exe = shutil.which(c.get("cli", "claude")) if c.get("enabled", True) else None
    return {"available": bool(exe), "cli": exe, "model": c.get("model", "opus"),
            "web": bool(c.get("web", True)),
            "note": None if exe else ("Chat is off in studio.toml." if not c.get("enabled", True) else
                                      "Install Claude Code (claude) to chat here. Everything else works without it.")}


class ChatJob:
    def __init__(self, message: str, project: str | None, session: str | None):
        self.id = uuid.uuid4().hex[:10]
        self.message, self.project, self.session = message, project, session
        self.events: list[dict] = [{"t": "user", "text": message, "ts": time.time()}]
        self.state, self.cost, self.proc, self.error = "running", None, None, None
        self.started = time.time()
        self.live: dict | None = None          # what Claude is producing right now (streamed), for the page

    def public(self, start: int = 0) -> dict:
        return {"id": self.id, "state": self.state, "session": self.session, "cost_usd": self.cost,
                "events": self.events[start:], "next": len(self.events), "error": self.error, "live": self.live,
                "seconds": round(time.time() - self.started, 1)}


class Chat:
    def __init__(self, cfg: dict, data_dir: Path, mcp_command: str):
        self.cfg, self.data, self.mcp = cfg, Path(data_dir), mcp_command
        self.jobs: dict[str, ChatJob] = {}

    def start(self, message: str, project: str | None = None, session: str | None = None) -> ChatJob:
        st = status(self.cfg)
        if not st["available"]:
            raise RuntimeError(st["note"])
        if any(j.state == "running" for j in self.jobs.values()):
            raise RuntimeError("Claude is still working on the previous message. Wait, or press Stop.")
        job = ChatJob(message, project, session)
        self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, st), daemon=True).start()
        return job

    def stop(self, jid: str) -> None:
        j = self.jobs.get(jid)
        if j and j.proc and j.proc.poll() is None:
            j.proc.terminate()
            j.state = "stopped"

    def _run(self, job: ChatJob, st: dict) -> None:
        c = self.cfg.get("chat", {})
        # the launcher path may contain spaces ("Application Support"): never split it
        cmd0, args0 = (self.mcp, []) if Path(self.mcp).exists() else (sys.executable, ["-m", "form.mcp_server"])
        mcp_cfg = {"mcpServers": {"form": {"command": cmd0, "args": args0 + ["--no-bench"],
                                           "env": {"FORM_DATA": str(self.data),
                                                   **({"FORM_CONFIG": self.cfg["_path"]} if Path(self.cfg["_path"]).exists() else {})}}}}
        tmp = Path(tempfile.mkdtemp(prefix="form-chat-"))
        (tmp / "mcp.json").write_text(json.dumps(mcp_cfg))
        tools = ["WebSearch", "WebFetch"] if st["web"] else []
        cmd = [st["cli"], "-p", job.message, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--model", st["model"], "--mcp-config", str(tmp / "mcp.json"), "--strict-mcp-config",
               "--tools", ",".join(tools) if tools else "",
               "--allowedTools", ",".join(["mcp__form__*"] + tools),
               "--append-system-prompt", PROMPT.format(project=job.project or "none (start a new one if asked)"),
               "--max-budget-usd", str(c.get("budget_usd_per_message", 3.0))]
        if job.session:
            cmd += ["--resume", job.session]
        try:
            job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                        text=True, cwd=str(self.data), bufsize=1)
            for line in job.proc.stdout:
                self._event(job, line)
            job.proc.wait()
            if job.state == "running":
                if job.proc.returncode == 0:
                    job.state = "done"
                else:
                    job.state = "failed"
                    job.error = (job.proc.stderr.read() or "")[-800:] or f"claude exited with {job.proc.returncode}"
        except OSError as e:
            job.state, job.error = "failed", str(e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _event(self, job: ChatJob, line: str) -> None:
        try:
            e = json.loads(line)
        except ValueError:
            return
        t, now = e.get("type"), time.time()
        if t == "stream_event":
            ev = e.get("event", {})
            et = ev.get("type")
            if et == "content_block_start":
                cb = ev.get("content_block", {})
                kind = "tool" if cb.get("type") == "tool_use" else cb.get("type")
                job.live = {"kind": kind, "name": cb.get("name", "").replace("mcp__form__", ""), "chars": 0, "text": ""}
            elif et == "content_block_delta" and job.live:
                d = ev.get("delta", {})
                chunk = d.get("partial_json") or d.get("text") or d.get("thinking") or ""
                job.live["chars"] += len(chunk)
                if d.get("type") == "text_delta":
                    job.live["text"] = (job.live["text"] + chunk)[-600:]
            elif et == "content_block_stop":
                job.live = None
            return
        if t == "system" and e.get("subtype") == "init":
            job.session = e.get("session_id") or job.session
            job.events.append({"t": "start", "model": e.get("model"), "ts": now})
        elif t == "assistant":
            for c in e.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    job.events.append({"t": "text", "text": c["text"], "ts": now})
                elif c.get("type") == "tool_use":
                    name = c.get("name", "").replace("mcp__form__", "")
                    job.events.append({"t": "tool", "id": c.get("id"), "name": name, "input": _short(c.get("input")), "ts": now})
        elif t == "user":
            for c in (e.get("message", {}).get("content") or []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    cont = c.get("content")
                    cont = cont if isinstance(cont, list) else [{"type": "text", "text": str(cont or "")}]
                    txt = " ".join(x.get("text", "") for x in cont if isinstance(x, dict) and x.get("type") == "text")
                    job.events.append({"t": "result", "id": c.get("tool_use_id"), "ok": not c.get("is_error"),
                                       "image": any(isinstance(x, dict) and x.get("type") == "image" for x in cont),
                                       "text": txt[:300], "ts": now})
        elif t == "result":
            job.cost = e.get("total_cost_usd")
            job.session = e.get("session_id") or job.session
            if e.get("is_error"):
                job.error = e.get("result") or e.get("subtype")
            job.events.append({"t": "end", "cost_usd": job.cost, "turns": e.get("num_turns"), "ts": now})


def _short(obj, n=220) -> str:
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
