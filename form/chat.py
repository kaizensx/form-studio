"""Chat: each message runs an agent CLI headless on the user's own account, with FORM's tools.

The agent (Claude Code, Codex, … see form/agents) talks to FORM through its own `form-mcp --no-bench` process over
the same data folder, so everything it does appears in the app through the activity log, exactly as when you use
that agent from a terminal. Allowed: FORM's MCP tools, web search/fetch for datasheets when enabled, and reading
the files attached to the conversation. No shell, no file edits.

Every message belongs to a conversation (form/conversations.py) that is saved as it streams. One message runs at
a time per conversation; up to MAX_RUNNING conversations run at once.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from . import secrets
import tomllib
import uuid
from pathlib import Path

from . import agents as agents_mod
from .agents.base import Run, short as _short  # noqa: F401  (_short: kept for callers of the old name)
from .conversations import ConversationError, Conversations

MAX_RUNNING = 3
RECAP_CHARS = 6000

PROMPT = """\
You are working inside Form Studio, a design studio for 3D-printed parts. The user is looking at Form Studio's page: every Form Studio
tool you call shows up there live (3D model, drafts, checks, slice), so you do not need to describe geometry at length.
- Use Form Studio tools for all design work. Built-in recipes (dock, gridfinity, hook, planter, coupon, enclosure, gear_pair, knob): create_project.
  Anything else: call design_guide, then write the design as code with create_design; iterate with update_design.
- After creating or changing a design, render(view="sheet") and look at it; fix what is wrong before replying.
- Look up exact dimensions of commercial parts: find the official datasheet or mechanical drawing with web search,
  then open it with Form Studio's read_document (it shows PDF pages as images; web fetch loses a drawing's dimensions).
  Name the source. Put such numbers in params with group "brief" and the source in doc.
- Ask the user only for measurements that change the fit or safety, and only when you cannot find them.
- Files the user attaches are listed at the end of their message with full paths. Look at images and PDFs before
  answering. A dimension read off a photo or sketch is an estimate: say so and record it as assumed, not measured.
  STEP/STL parts: import_reference(project, path), never read them as text.
- Reply briefly: what you made, the key numbers, what is assumed or unverified, and what the user should check.
  Slices are simulations and fit yields are models; say so. You cannot approve releases; point to the Release tab.
Current project on the page: {project}.
"""


def _adapters(cfg: dict) -> dict:
    return cfg.get("_adapters") or agents_mod.ADAPTERS


def defaults(cfg: dict, agent_status: list[dict] | None = None) -> dict:
    """The agent, model and effort a new conversation starts with ([chat] in studio.toml)."""
    c = cfg.get("chat", {})
    agent = c.get("agent") or "claude"
    st = agent_status if agent_status is not None else [a.status(cfg) for a in _adapters(cfg).values()]
    ok = [a["id"] for a in st if a["available"]]
    if agent not in ok and ok:
        agent = ok[0]
    return {"agent": agent, "model": str(c.get("model") or "default"), "effort": str(c.get("effort") or "")}


def status(cfg: dict) -> dict:
    c = cfg.get("chat", {})
    on = c.get("enabled", True)
    ags = [a.status(cfg) for a in _adapters(cfg).values()] if on else []
    d = defaults(cfg, ags)
    cur = next((a for a in ags if a["id"] == d["agent"] and a["available"]), None)
    note = None
    if not on:
        note = "Chat is off in studio.toml."
    elif not cur:
        note = "Install Claude Code (claude) or Codex (codex) to chat here. Everything else works without it."
    return {"available": bool(cur), "cli": cur["cli"] if cur else None, "model": d["model"], "web": bool(c.get("web", True)),
            "note": note, "agents": ags, "default": d, "max_running": MAX_RUNNING,
            "label": cur["label"] if cur else "Claude Code"}


def set_defaults_text(text: str, values: dict) -> str:
    """Set keys in the [chat] table of TOML text; every other line stays as it was."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start = next((i for i, ln in enumerate(lines) if re.match(r"^\s*\[chat\]\s*(#.*)?$", ln)), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append("[chat]\n")
        start = len(lines) - 1
    for key, val in values.items():
        end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
        new = f"{key} = {json.dumps(str(val), ensure_ascii=False)}"
        for i in range(start + 1, end):
            m = re.match(rf"^(\s*){re.escape(key)}\s*=\s*(\"[^\"]*\"|'[^']*'|[^#\s]+)(\s*#.*)?(\r?\n)?$", lines[i])
            if m:
                lines[i] = f"{m.group(1)}{new}{m.group(3) or ''}{m.group(4) or chr(10)}"
                break
        else:
            lines.insert(start + 1, new + "\n")
    return "".join(lines)


def set_defaults(cfg: dict, agent: str | None = None, model: str | None = None, effort: str | None = None) -> dict:
    """Remember the choice for new conversations: in memory at once, and in [chat] of studio.toml when it can be
    written (the file is backed up once, as studio.toml.bak-form-chat; nothing else in it changes)."""
    vals = {k: str(v) for k, v in (("agent", agent), ("model", model), ("effort", effort)) if v is not None}
    if "agent" in vals and vals["agent"] not in _adapters(cfg):
        raise ValueError(f"Unknown agent “{vals['agent']}”.")
    cfg.setdefault("chat", {}).update(vals)
    from .slicer import config_target
    path, saved, why = config_target(cfg), False, None
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        new = set_defaults_text(old or "# Form Studio configuration (written by Form Studio)\n", vals)
        before, after = (tomllib.loads(old) if old else {}), tomllib.loads(new)
        a, b = dict(after), dict(before)
        a_c, b_c = dict(a.pop("chat", {})), dict(b.pop("chat", {}))
        for k in vals:
            a_c.pop(k, None), b_c.pop(k, None)
        if a != b or a_c != b_c or any(after["chat"].get(k) != v for k, v in vals.items()):
            raise ValueError("the file would change in other places")
        backup = path.with_name(path.name + ".bak-form-chat")
        if path.exists() and not backup.exists():
            shutil.copyfile(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        saved = True
    except (OSError, ValueError) as e:
        why = f"Kept for this session only: {path} could not be updated ({e})."
    return {"default": defaults(cfg), "saved": saved, "path": str(path), "note": why}


class ChatJob:
    def __init__(self, message: str, project: str | None, session: str | None, conversation: str | None = None,
                 agent: str = "claude", model: str = "default", effort: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.message, self.project, self.session, self.conversation = message, project, session, conversation
        self.agent, self.model, self.effort = agent, model, effort
        self.events: list[dict] = [{"t": "user", "text": message, "ts": time.time()}]
        self.state, self.cost, self.proc, self.error = "running", None, None, None
        self.started = time.time()
        self.live: dict | None = None          # what the agent is producing right now (streamed), for the page
        self.parser = None
        self.tools: dict = {}                  # tool call id -> name, to recognise what a result belongs to
        self.steps = 0
        self.before: set | None = None         # project ids that existed when the message was sent
        self.attachments: list[dict] = []
        self.stop_asked = False

    def public(self, start: int = 0) -> dict:
        return {"id": self.id, "state": self.state, "session": self.session, "cost_usd": self.cost,
                "events": self.events[start:], "next": len(self.events), "error": self.error, "live": self.live,
                "conversation": self.conversation, "agent": self.agent,
                "seconds": round(time.time() - self.started, 1)}


class Chat:
    def __init__(self, cfg: dict, data_dir: Path, mcp_command: str, adapters: dict | None = None):
        self.cfg, self.data, self.mcp = cfg, Path(data_dir), mcp_command
        self.adapters = adapters or _adapters(cfg)
        self.store = Conversations(self.data)
        self.jobs: dict[str, ChatJob] = {}
        self._lock = threading.Lock()

    # ---- state -------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        return status(dict(self.cfg, _adapters=self.adapters))

    def running(self, cid: str | None = None) -> list[ChatJob]:
        return [j for j in self.jobs.values() if j.state == "running" and (cid is None or j.conversation == cid)]

    def job_for(self, cid: str) -> ChatJob | None:
        """The conversation's running job, or else its most recent one in this process."""
        js = [j for j in self.jobs.values() if j.conversation == cid]
        return next((j for j in js if j.state == "running"), js[-1] if js else None)

    def conversation(self, cid: str, start: int = 0) -> dict:
        """A conversation with its events from `start`, plus what is streaming right now."""
        out = self.store.get(cid, start)
        j = self.job_for(cid)
        run = bool(j and j.state == "running")
        out.update({"state": "running" if run else "idle", "live": j.live if run else None, "job": j.id if run else None,
                    "seconds": round(time.time() - j.started, 1) if run else None})
        return out

    def list(self, project: str | None = None, q: str | None = None) -> list[dict]:
        busy = {j.conversation for j in self.running()}
        return [dict(m, state="running" if m["id"] in busy else "idle") for m in self.store.list(project, q)]

    def delete(self, cid: str) -> None:
        for j in self.running(cid):
            self.stop(j.id)
        self.store.delete(cid)

    # ---- sending -----------------------------------------------------------------------------------------------
    def send(self, message: str, conversation: str | None = None, project: str | None = None, agent: str | None = None,
             model: str | None = None, effort: str | None = None, attachments: list[str] | None = None) -> ChatJob:
        message = (message or "").strip()
        if not message:
            raise RuntimeError("Write a message first.")
        st = self.status()
        if not self.cfg.get("chat", {}).get("enabled", True):
            raise RuntimeError(st["note"])
        with self._lock:
            if conversation:
                meta = self.store.meta(conversation)
                if self.running(conversation):
                    raise RuntimeError("This conversation is still answering the previous message. Wait, or press Stop.")
            else:
                meta = None
            if len(self.running()) >= MAX_RUNNING:
                raise RuntimeError(f"{MAX_RUNNING} conversations are already running. Wait for one to finish, or stop one.")
            d = st["default"]
            agent = agent or (meta["agent"] if meta else d["agent"])
            adapter = self.adapters.get(agent)
            if not adapter:
                raise RuntimeError(f"Unknown agent “{agent}”. Known: {', '.join(self.adapters)}.")
            exe = adapter.executable(self.cfg)
            if not exe:
                raise RuntimeError(adapter.install_hint or f"{adapter.label} is not installed.")
            # the configured default model and effort belong to the default agent: "opus" means nothing to Codex
            mine = agent == d["agent"]
            model = model or (meta["model"] if meta else (d["model"] if mine else "")) or "default"
            effort = effort if effort is not None else (meta["effort"] if meta else (d["effort"] if mine else ""))
            if meta is None:
                meta = self.store.create(project, agent, model, effort or "")
            fields = {"agent": agent, "model": model, "effort": effort or ""}
            if project and not meta.get("project"):
                fields["project"] = project
            meta = self.store.update(meta["id"], **fields)
            cid = meta["id"]
            session = meta.get("session") if meta.get("session_agent") == agent else None
            job = ChatJob(message, meta.get("project") or project, session, cid, agent, model, effort or "")
            job.attachments = self.store.attachments(cid, attachments or [])
            job.before = self._project_ids()
            user = {"t": "user", "text": message}
            if job.attachments:
                user["attachments"] = job.attachments
            job.events[0] = self.store.append(cid, user)
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, adapter, exe), daemon=True, name=f"form-chat-{job.id}").start()
        return job

    def start(self, message: str, project: str | None = None, session: str | None = None) -> ChatJob:
        """The older entry point (web bench): continue the conversation that owns `session`, or start a new one."""
        cid = None
        if session:
            cid = next((m["id"] for m in self.store.list() if m.get("session") == session), None)
        try:
            return self.send(message, cid, project)
        except ConversationError as e:
            raise RuntimeError(str(e))

    def stop(self, jid: str) -> bool:
        """Stop a running message, by job id or conversation id."""
        j = self.jobs.get(jid) or next(iter(self.running(jid)), None)
        if not j or j.state != "running":
            return False
        j.stop_asked = True
        if j.proc and j.proc.poll() is None:
            try:
                j.proc.terminate()
            except OSError:
                pass
        return True

    def note(self, cid: str, by: str, text: str) -> dict:
        """Record what another agent did while this conversation was open (shown as a quiet line)."""
        return self.store.append(cid, {"t": "act", "by": str(by)[:60], "text": str(text)[:400]})

    # ---- one run -----------------------------------------------------------------------------------------------
    def _project_ids(self) -> set:
        try:
            return {d.name for d in self.data.iterdir() if (d / "project.json").exists()}
        except OSError:
            return set()

    def _mcp(self) -> dict:
        # the launcher path may contain spaces ("Application Support"): never split it
        cmd0, args0 = (self.mcp, []) if Path(self.mcp).exists() else (sys.executable, ["-m", "form.mcp_server"])
        env = {"FORM_DATA": str(self.data)}
        if Path(str(self.cfg.get("_path", ""))).exists():
            env["FORM_CONFIG"] = self.cfg["_path"]
        return {"command": cmd0, "args": args0 + ["--no-bench"], "env": env}

    def _prompt(self, job: ChatJob, with_recap: bool) -> str:
        parts = []
        if with_recap and job.conversation:
            lines = []
            for e in self.store.events(job.conversation)[:-1]:
                if e.get("t") == "user":
                    lines.append("User: " + str(e.get("text", "")))
                elif e.get("t") == "text":
                    lines.append("Assistant: " + str(e.get("text", "")))
            recap = "\n".join(lines)[-RECAP_CHARS:]
            if recap.strip():
                parts.append("Earlier in this conversation (the earlier agent session is not available, so this is a "
                             "transcript; check the project with Form Studio's tools rather than trusting it):\n" + recap + "\n\nNow:")
        parts.append(job.message)
        if job.attachments:
            d = self.store.files_dir(job.conversation)
            what = {"image": "image", "pdf": "PDF; read_document(path) also opens it page by page",
                    "cad": "CAD part; use import_reference(project, path)"}
            parts.append("Attached files:\n" + "\n".join(f"- {d / a['file']} ({what.get(a['kind'], a['kind'])})" for a in job.attachments))
        return "\n\n".join(parts)

    def _run(self, job: ChatJob, adapter, exe: str) -> None:
        c = self.cfg.get("chat", {})
        cwd = self.store.dir(job.conversation) if job.conversation else self.data
        had_history = bool(job.conversation) and self.store.meta(job.conversation).get("messages", 0) > 1
        try:
            for attempt in (1, 2):
                tmp = Path(tempfile.mkdtemp(prefix="form-chat-"))
                fdir = self.store.files_dir(job.conversation) if job.conversation else cwd
                files = [fdir / a["file"] for a in job.attachments]
                run = Run(message=self._prompt(job, with_recap=had_history and not job.session),
                          system=PROMPT.format(project=job.project or "none (start a new one if asked)"),
                          model=job.model, effort=job.effort, session=job.session, cwd=cwd, scratch=tmp, mcp=self._mcp(),
                          web=bool(c.get("web", True)), budget_usd=float(c.get("budget_usd_per_message", 3.0)),
                          images=[f for f, a in zip(files, job.attachments) if a["kind"] == "image"], files=files)
                job.parser = adapter.parser()
                n0, err_text = len(job.events), ""
                saved0 = self.store.meta(job.conversation).get("events", 0) if job.conversation else 0
                try:
                    cmd = adapter.command(run, exe)
                    job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                                text=True, encoding="utf-8", errors="replace", cwd=str(cwd), bufsize=1,
                                                env=dict(os.environ, **getattr(adapter, "env", {}), **secrets.agent_env(adapter.id)))
                    err_buf: list[str] = []
                    drain = threading.Thread(target=lambda p=job.proc: err_buf.extend(p.stderr), daemon=True)
                    drain.start()
                    for line in job.proc.stdout:
                        self._event(job, line)
                    job.proc.wait()
                    drain.join(timeout=2)
                    err_text = "".join(err_buf)
                    for pipe in (job.proc.stdout, job.proc.stderr):
                        try:
                            pipe.close()
                        except (OSError, ValueError):
                            pass
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
                rc = job.proc.returncode
                said = any(e["t"] in ("text", "tool") for e in job.events[n0:])
                if (attempt == 1 and job.session and not job.stop_asked and rc != 0 and not said
                        and adapter.resume_failed(err_text + " " + (job.error or ""), job.events[n0:])):
                    # the CLI no longer has that session: say so, then send again with a transcript instead
                    job.session, job.error = None, None
                    del job.events[n0:]
                    if job.conversation:
                        self.store.truncate(job.conversation, saved0)
                        self.store.update(job.conversation, session=None, session_agent=None)
                    continue
                break
            ended = any(e["t"] == "end" for e in job.events[n0:])
            # Save the last events first and only then say the job is over: a reader that sees "failed" or
            # "stopped" must also find its error or end event (found on a slow Windows runner).
            if job.stop_asked:
                if not ended:
                    self._add(job, {"t": "end", "stopped": True, "cost_usd": None, "steps": job.steps,
                                    "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                job.state = "stopped"
            elif rc == 0 and not job.error:
                job.state = "done"
            else:
                if not job.error:
                    job.error = err_text.strip()[-800:] or f"{adapter.label} exited with code {rc}"
                    known = adapter.explain(job.error)
                    if known:                                   # a known failure, said plainly with the fix inside FORM
                        job.error = known["message"]
                        self._add(job, {"t": "error", "text": known["message"], "hint": known.get("hint", "")})
                    else:
                        self._add(job, {"t": "error", "text": job.error})
                job.state = "failed"
        except (OSError, ConversationError) as e:
            job.error = str(e)
            self._add(job, {"t": "error", "text": job.error})
            job.state = "failed"
        finally:
            job.live = None

    def _add(self, job: ChatJob, ev: dict) -> None:
        if job.conversation:
            try:
                ev = self.store.append(job.conversation, ev)
            except ConversationError:
                ev = dict(ev, ts=time.time())       # the conversation was deleted while it ran
        else:
            ev = dict(ev, ts=time.time())
        job.events.append(ev)

    def _event(self, job: ChatJob, line: str) -> None:
        """One line of the CLI's output: update what is live, save what is finished."""
        if job.parser is None:
            job.parser = self.adapters[job.agent].parser()
        for ev in job.parser.feed(line):
            t = ev["t"]
            if t == "live":
                job.live = ev["live"]
                continue
            if ev.get("session"):
                if job.session != ev["session"]:
                    job.session = ev["session"]
                    if job.conversation:
                        try:
                            self.store.update(job.conversation, session=job.session, session_agent=job.agent)
                        except ConversationError:
                            pass
            if t == "session":
                continue
            ev = {k: v for k, v in ev.items() if k != "session"}
            if t == "start":
                ev["agent"] = job.agent
                ev["asked"] = job.model
            elif t == "tool":
                job.steps += 1
                job.tools[ev.get("id")] = ev.get("name", "")
            elif t == "result":
                full = ev.pop("full", "") or ""
                self._enrich(job, ev, full)
            elif t == "end":
                job.cost = ev.get("cost_usd")
                err = ev.pop("error", None)
                ev.update({"steps": job.steps, "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                self._add(job, ev)
                if err:
                    job.error = str(err)
                    self._add(job, {"t": "error", "text": job.error})
                continue
            self._add(job, ev)

    def _enrich(self, job: ChatJob, ev: dict, full: str) -> None:
        """Make a tool result useful to the page: the render it produced, the project it created."""
        name = job.tools.get(ev.get("id"), "")
        ev["name"] = name
        m = re.search(r"File: (.+?\.png)\s*$", full.strip())
        if m and ev.get("ok"):
            try:
                f = Path(m.group(1)).resolve()
                rel = f.relative_to(self.data.resolve())
                if len(rel.parts) == 4 and rel.parts[1:3] == ("artifacts", "renders") and f.is_file():
                    ev["img"] = {"project": rel.parts[0], "file": rel.parts[3]}
            except (OSError, ValueError):
                pass
        if name.startswith("create_") and ev.get("ok") and job.before is not None:
            new = self._project_ids() - job.before
            hit = [p for p in new if f'"{p}"' in full] or (list(new) if len(new) == 1 else [])
            if hit:
                ev["project"] = hit[0]
                job.project = job.project or hit[0]
                if job.conversation:
                    try:
                        if not self.store.meta(job.conversation).get("project"):
                            self.store.update(job.conversation, project=hit[0])
                    except ConversationError:
                        pass


# ---- command line: `form chat …`, `form conversations …` ----------------------------------------------------------

def main_chat(argv: list[str]) -> int:
    """form chat "message" [--project ID] [--conversation ID] [--model X] [--agent claude|codex] [--effort L]
    [--attach FILE ...] [--json]: send one message, stream the reply, save the conversation."""
    import argparse
    from . import config
    ap = argparse.ArgumentParser(prog="form chat", description="Send one message to an agent with Form Studio's tools; the conversation is saved.")
    ap.add_argument("message")
    ap.add_argument("--project")
    ap.add_argument("--conversation", help="continue this conversation (id from `form conversations list`)")
    ap.add_argument("--agent", help="claude, codex or gemini (default: [chat] agent)")
    ap.add_argument("--model", help="a model alias or id the agent's CLI accepts (default: [chat] model)")
    ap.add_argument("--effort")
    ap.add_argument("--attach", action="append", default=[], metavar="FILE", help="image, PDF, STEP or STL (repeat)")
    ap.add_argument("--json", action="store_true", help="print one JSON event per line instead of text")
    a = ap.parse_args(argv)
    cfg = config.load()
    from .setup import mcp_command
    chat = Chat(cfg, Path(cfg["data"]["dir"]), mcp_command())

    def fail(msg: str) -> int:
        print(json.dumps({"error": {"message": msg}}, ensure_ascii=False), file=sys.stderr if not a.json else sys.stdout)
        return 2
    try:
        cid = a.conversation
        if a.attach:
            if not cid:
                d = chat.status()["default"]
                ag = a.agent or d["agent"]
                mine = ag == d["agent"]                    # defaults for model and effort are the default agent's
                cid = chat.store.create(a.project, ag, a.model or (d["model"] if mine else "default"),
                                        a.effort or (d["effort"] if mine else ""))["id"]
            ids = [chat.store.attach(cid, Path(f))["id"] for f in a.attach]
        else:
            ids = []
        job = chat.send(a.message, cid, a.project, a.agent, a.model, a.effort, ids)
    except (RuntimeError, ConversationError) as e:
        return fail(str(e))
    seen, shown_live = 1, 0
    if a.json:
        print(json.dumps({"t": "conversation", "id": job.conversation, "job": job.id, "agent": job.agent, "model": job.model}), flush=True)
    try:
        while True:
            running = job.state == "running"
            evs = job.events[seen:]
            seen += len(evs)
            for ev in evs:
                if a.json:
                    print(json.dumps(ev, ensure_ascii=False, default=str), flush=True)
                    continue
                t = ev["t"]
                if t == "start":
                    print(f"[{ev.get('agent')} · model {ev.get('model') or 'not reported'}]", file=sys.stderr, flush=True)
                elif t == "text":
                    print(ev["text"][shown_live:] if shown_live else ev["text"], flush=True)
                    shown_live = 0
                elif t == "tool":
                    print(f"  · {ev['name']} {ev.get('input', '')}", file=sys.stderr, flush=True)
                elif t == "error":
                    print(f"error: {ev['text']}", file=sys.stderr, flush=True)
                elif t == "end":
                    cost = ("cost not reported" if ev.get("cost_usd") is None else "under $0.01" if ev["cost_usd"] < 0.01 else f"${ev['cost_usd']:.2f}")
                    print(f"[{ev.get('steps', 0)} steps · {cost} · {ev.get('seconds')} s"
                          + (" · stopped" if ev.get("stopped") else "") + f" · conversation {job.conversation}]", file=sys.stderr, flush=True)
            L = job.live
            if not a.json and L and L.get("kind") == "text" and len(L.get("text", "")) > shown_live and len(L["text"]) < 20000:
                sys.stdout.write(L["text"][shown_live:])
                sys.stdout.flush()
                shown_live = len(L["text"])
            if not running and seen >= len(job.events):
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        chat.stop(job.id)
        time.sleep(0.5)
    if a.json:
        print(json.dumps({"t": "done", "state": job.state, "conversation": job.conversation, "session": job.session,
                          "cost_usd": job.cost, "error": job.error}, ensure_ascii=False), flush=True)
    return 0 if job.state == "done" else 1


def main_conversations(argv: list[str]) -> int:
    """form conversations list [--project ID] [--search TEXT] | show ID | delete ID | rename ID TITLE | pin ID [--off]"""
    import argparse
    from . import config
    ap = argparse.ArgumentParser(prog="form conversations", description="Saved conversations (JSON).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--project")
    ls.add_argument("--search")
    for name in ("show", "delete", "pin"):
        p = sub.add_parser(name)
        p.add_argument("id")
        if name == "pin":
            p.add_argument("--off", action="store_true")
    rn = sub.add_parser("rename")
    rn.add_argument("id")
    rn.add_argument("title")
    a = ap.parse_args(argv)
    cfg = config.load()
    store = Conversations(Path(cfg["data"]["dir"]))

    def out(obj):
        print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))
    try:
        if a.cmd == "list":
            out(store.list(a.project, a.search))
        elif a.cmd == "show":
            out(store.get(a.id))
        elif a.cmd == "delete":
            store.delete(a.id)
            out({"deleted": a.id})
        elif a.cmd == "rename":
            out(store.rename(a.id, a.title))
        elif a.cmd == "pin":
            out(store.pin(a.id, not a.off))
    except ConversationError as e:
        out({"error": {"message": str(e)}})
        return 2
    return 0
