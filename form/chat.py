"""Chat: each message runs an agent with Form Studio's tools: an agent CLI headless on the user's own account, or an
API agent that talks to a model provider directly (form/agents/api.py).

The agent (Claude Code, Codex, an API provider, … see form/agents) talks to Form Studio through its own
`form-mcp --no-bench` process over the same data folder, so everything it does appears in the app through the activity
log, exactly as when you use that agent from a terminal. Allowed: Form Studio's MCP tools, web search/fetch for
datasheets when enabled (CLI agents), and reading the files attached to the conversation. No shell, no file edits.

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

from . import __version__
from . import agents as agents_mod
from . import ask as ask_mod
from .agents import compat
from .agents import providers as providers_mod
from .agents.models import Learned
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
- Ask the user only for measurements that change the fit or safety, or to settle an intent you cannot tell apart,
  and only when you cannot find the answer yourself: use Form Studio's ask_user (one question at a time, with
  choices when there are obvious options, at most three questions per task). Before an action the user should
  agree to (deleting, replacing their design), ask_user with kind="confirm".
- When the reply is done, call suggest_replies once with up to three short next steps the user might want.
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
    agent = c.get("agent") or ""
    st = agent_status if agent_status is not None else [a.status(cfg) for a in _adapters(cfg).values()]
    ok = [a["id"] for a in st if a["available"]]
    if agent not in ok and ok:
        agent = ok[0]
    return {"agent": agent, "model": str(c.get("model") or "default"), "effort": str(c.get("effort") or "")}


def status(cfg: dict) -> dict:
    c = cfg.get("chat", {})
    on = c.get("enabled", True)
    ads = list(_adapters(cfg).values()) if on else []
    if any(getattr(a, "inline", False) for a in ads) and c.get("api_agents", True):
        providers_mod.warm(cfg, {a.id for a in ads if getattr(a, "inline", False)})     # all at once, not one by one
    if not c.get("api_agents", True):
        ads = [a for a in ads if not getattr(a, "inline", False)]
    ags = [a.status(cfg) for a in ads]
    if cfg.get("data", {}).get("dir"):                    # the versions each alias resolved to on its last run
        learned = Learned(Path(cfg["data"]["dir"]))
        learned.seed()
        ags = [learned.decorate(a) for a in ags]
    d = defaults(cfg, ags)
    cur = next((a for a in ags if a["id"] == d["agent"] and a["available"]), None)
    note = None
    if not on:
        note = "Chat is off in studio.toml."
    elif not cur:
        note = ("Connect an agent to chat here: an agent CLI such as Claude Code, Codex or Gemini CLI, an API key from a "
                "model provider, or a local model server such as Ollama. Everything else works without one.")
    return {"available": bool(cur), "cli": cur["cli"] if cur else None, "model": d["model"], "web": bool(c.get("web", True)),
            "note": note, "agents": ags, "default": d, "max_running": MAX_RUNNING,
            "label": cur["label"] if cur else "your agent"}


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
        self.ask = False                       # someone can answer ask_user (the app, or a terminal)
        self.asked: set = set()                # question ids already shown in the conversation
        self.waiting: dict | None = None       # the open question, while the agent waits for an answer
        self.unread = 0                        # output lines that were not the CLI's event format
        self.model_id: str | None = None       # the model the CLI reported for this run
        self.head0: int | None = None          # the project's head revision when the message was sent

    def public(self, start: int = 0) -> dict:
        return {"id": self.id, "state": self.state, "session": self.session, "cost_usd": self.cost,
                "events": self.events[start:], "next": len(self.events), "error": self.error, "live": self.live,
                "conversation": self.conversation, "agent": self.agent, "asking": self.waiting,
                "seconds": round(time.time() - self.started, 1)}


class Chat:
    def __init__(self, cfg: dict, data_dir: Path, mcp_command: str, adapters: dict | None = None):
        self.cfg, self.data, self.mcp = cfg, Path(data_dir), mcp_command
        self.adapters = adapters or _adapters(cfg)
        self.store = Conversations(self.data)
        self.learned = Learned(self.data)
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
                    "seconds": round(time.time() - j.started, 1) if run else None,
                    "asking": j.waiting if run else None})
        ad = self.adapters.get(out.get("agent"))
        for ev in out.get("items", []):                  # conversations saved before model names were shown
            if ev.get("t") == "start" and ev.get("model") and not ev.get("label"):
                ev["label"] = ad.model_label(ev["model"]) if ad else ev["model"]
        if out.get("resolved_model") and not out.get("resolved_agent"):     # saved before the agent was recorded with it
            out["resolved_agent"] = next((e.get("agent") for e in reversed(self.store.events(cid))
                                          if e.get("t") in ("start", "end") and e.get("model")), None)
        if out.get("resolved_model") and (out.get("resolved_agent") or out.get("agent")) != out.get("agent"):
            out["resolved_model"] = None              # saved under the agent used before; not this one's model
        if out.get("resolved_model"):
            out["resolved_label"] = ad.model_label(out["resolved_model"]) if ad else out["resolved_model"]
        return out

    def list(self, project: str | None = None, q: str | None = None) -> list[dict]:
        busy = {j.conversation: ("asking" if j.waiting else "running") for j in self.running()}
        return [dict(m, state=busy.get(m["id"], "idle")) for m in self.store.list(project, q)]

    def delete(self, cid: str) -> None:
        for j in self.running(cid):
            self.stop(j.id)
        self.store.delete(cid)

    # ---- sending -----------------------------------------------------------------------------------------------
    def send(self, message: str, conversation: str | None = None, project: str | None = None, agent: str | None = None,
             model: str | None = None, effort: str | None = None, attachments: list[str] | None = None,
             ask: bool = True) -> ChatJob:
        """ask: a person can answer the agent's questions (the app; `form chat` in a terminal)."""
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
            job.ask = bool(ask)
            job.head0 = self._head(job.project)
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
        if j.conversation:
            ask_mod.close_all(self.ask_dir(j.conversation), "stopped")
        if j.proc and j.proc.poll() is None:
            try:
                j.proc.terminate()
            except OSError:
                pass
        return True

    def note(self, cid: str, by: str, text: str) -> dict:
        """Record what another agent did while this conversation was open (shown as a quiet line)."""
        return self.store.append(cid, {"t": "act", "by": str(by)[:60], "text": str(text)[:400]})

    # ---- questions from the agent (ask_user) -------------------------------------------------------------------
    def ask_dir(self, cid: str) -> Path:
        return self.store.dir(cid) / "ask"

    def answer(self, cid: str, qid: str, text: str = "", choices: list | None = None) -> dict:
        """The person's answer to the agent's question: handed to the waiting tool and kept in the conversation."""
        try:
            a = ask_mod.answer(self.ask_dir(cid), qid, text, choices)
        except ask_mod.AskError as e:
            raise ConversationError(str(e))
        j = self.job_for(cid)
        ev = {"t": "answer", "id": qid, "text": a["text"], "choices": a["choices"]}
        if j and j.state == "running":
            if j.waiting and j.waiting.get("id") == qid:
                j.waiting = None
            self._add(j, ev)
            return ev
        return self.store.append(cid, ev)

    def _watch_asks(self, job: ChatJob) -> None:
        """While the agent runs: show each new question in the conversation, and close the ones nobody answered."""
        folder = self.ask_dir(job.conversation)
        while job.state == "running":
            try:
                for q in ask_mod.questions(folder):
                    if q["id"] not in job.asked and q["state"] == "open":
                        job.asked.add(q["id"])
                        self._add(job, {"t": "ask", "id": q["id"], "question": q["question"], "choices": q["choices"],
                                        "multi": q["multi"], "free": q["free"], "why": q["why"], "kind": q["kind"],
                                        "timeout": q.get("timeout")})
                        job.waiting = {k: q[k] for k in ("id", "question", "choices", "multi", "free", "why", "kind")}
                    elif q["id"] in job.asked and q["state"] == "closed" and job.waiting and job.waiting["id"] == q["id"]:
                        job.waiting = None
                        self._add(job, {"t": "answer", "id": q["id"], "closed": q.get("reason") or "timeout"})
            except (OSError, ConversationError):
                pass
            time.sleep(0.2)

    def _close_asks(self, job: ChatJob) -> None:
        if not job.conversation:
            return
        reason = "stopped" if job.stop_asked else "ended"
        ask_mod.close_all(self.ask_dir(job.conversation), reason)
        if job.waiting:
            self._add(job, {"t": "answer", "id": job.waiting["id"], "closed": reason})
            job.waiting = None

    # ---- one run -----------------------------------------------------------------------------------------------
    def _head(self, pid: str | None) -> int | None:
        if not pid:
            return None
        try:
            return int(json.loads((self.data / pid / "project.json").read_text(encoding="utf-8")).get("head"))
        except (OSError, ValueError, TypeError):
            return None

    def _project_ids(self) -> set:
        try:
            return {d.name for d in self.data.iterdir() if (d / "project.json").exists()}
        except OSError:
            return set()

    def _mcp(self, job: ChatJob | None = None) -> dict:
        # the launcher path may contain spaces ("Application Support"): never split it
        if getattr(sys, "frozen", False):           # the packaged app is its own MCP server; never a form-mcp on PATH
            cmd0, args0 = sys.executable, ["-m", "form.mcp_server"]
        else:
            cmd0, args0 = (self.mcp, []) if Path(self.mcp).exists() else (sys.executable, ["-m", "form.mcp_server"])
        env = {"FORM_DATA": str(self.data)}
        if self.cfg.get("_path") and Path(str(self.cfg["_path"])).exists():
            env["FORM_CONFIG"] = self.cfg["_path"]
        if job is not None and job.ask and job.conversation:          # ask_user reaches this conversation
            env[ask_mod.ENV_DIR] = str(self.ask_dir(job.conversation))
            env[ask_mod.ENV_TIMEOUT] = str(int(self._ask_timeout()))
        return {"command": cmd0, "args": args0 + ["--no-bench"], "env": env}

    def _ask_timeout(self) -> float:
        try:
            return max(30.0, float(self.cfg.get("chat", {}).get("ask_timeout_s", ask_mod.DEFAULT_TIMEOUT)))
        except (TypeError, ValueError):
            return ask_mod.DEFAULT_TIMEOUT

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
        if getattr(adapter, "inline", False):
            return self._run_inline(job, adapter)
        c = self.cfg.get("chat", {})
        cwd = self.store.dir(job.conversation) if job.conversation else self.data
        had_history = bool(job.conversation) and self.store.meta(job.conversation).get("messages", 0) > 1
        if job.conversation:
            threading.Thread(target=self._watch_asks, args=(job,), daemon=True, name=f"form-ask-{job.id}").start()
        try:
            for attempt in (1, 2):
                tmp = Path(tempfile.mkdtemp(prefix="form-chat-"))
                fdir = self.store.files_dir(job.conversation) if job.conversation else cwd
                files = [fdir / a["file"] for a in job.attachments]
                run = Run(message=self._prompt(job, with_recap=had_history and not job.session),
                          system=PROMPT.format(project=job.project or "none (start a new one if asked)"),
                          model=job.model, effort=job.effort, session=job.session, cwd=cwd, scratch=tmp, mcp=self._mcp(job),
                          tool_timeout_s=self._ask_timeout() + 300,
                          web=bool(c.get("web", True)), budget_usd=float(c.get("budget_usd_per_message", 3.0)),
                          images=[f for f, a in zip(files, job.attachments) if a["kind"] == "image"], files=files)
                job.parser = adapter.parser()
                n0, err_text = len(job.events), ""
                saved0 = self.store.meta(job.conversation).get("events", 0) if job.conversation else 0
                try:
                    cmd = adapter.command(run, exe)
                    job.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                                text=True, encoding="utf-8", errors="replace", cwd=str(cwd), bufsize=1,
                                                env=dict(os.environ, **getattr(adapter, "env", {}), **secrets.agent_env(adapter.id),
                                                         **adapter.run_env(run)))
                    err_buf: list[str] = []
                    drain = threading.Thread(target=lambda p=job.proc: err_buf.extend(p.stderr), daemon=True)
                    drain.start()
                    for line in job.proc.stdout:
                        if line.strip() and not line.lstrip().startswith(("{", "[")):
                            job.unread += 1
                        self._event(job, line)
                    job.proc.wait()
                    self._event(job, None)                      # what the parser still owes (CLIs without an end event)
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
            self._close_asks(job)                           # before the state changes: a reader sees it with the end
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
                    known = adapter.explain(job.error) or compat.diagnose(
                        adapter.id, adapter.label, exe, rc, err_text, job.unread,
                        sum(1 for e in job.events[n0:] if e["t"] in ("start", "text", "tool", "end")), __version__)
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
            self._close_asks(job)

    def _run_inline(self, job: ChatJob, adapter) -> None:
        """An API agent: the loop runs in this thread (form/agents/api.py); its events take the same path as a CLI's."""
        from .agents.api import Control, SessionGone
        c = self.cfg.get("chat", {})
        cwd = self.store.dir(job.conversation) if job.conversation else self.data
        had_history = bool(job.conversation) and self.store.meta(job.conversation).get("messages", 0) > 1
        if job.conversation:
            threading.Thread(target=self._watch_asks, args=(job,), daemon=True, name=f"form-ask-{job.id}").start()
        failure = None
        try:
            for attempt in (1, 2):
                fdir = self.store.files_dir(job.conversation) if job.conversation else cwd
                files = [fdir / a["file"] for a in job.attachments]
                run = Run(message=self._prompt(job, with_recap=had_history and not job.session),
                          system=PROMPT.format(project=job.project or "none (start a new one if asked)"),
                          model=job.model, effort=job.effort, session=job.session, cwd=cwd, scratch=cwd, mcp=self._mcp(job),
                          tool_timeout_s=self._ask_timeout() + 300, web=False,
                          budget_usd=float(c.get("budget_usd_per_message", 3.0)),
                          images=[f for f, a in zip(files, job.attachments) if a["kind"] == "image"], files=files)
                job.parser = None
                job.proc = Control()
                try:
                    failure = adapter.execute(run, self.cfg, lambda evs: self._events(job, evs), job.proc)
                except SessionGone:
                    if attempt == 1 and job.session:      # the saved history is gone: send again with a transcript
                        job.session = None
                        if job.conversation:
                            self.store.update(job.conversation, session=None, session_agent=None)
                        continue
                    raise
                break
            self._close_asks(job)
            if job.stop_asked:
                if not any(e["t"] == "end" for e in job.events[1:]):
                    self._add(job, {"t": "end", "stopped": True, "cost_usd": None, "steps": job.steps,
                                    "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                job.state = "stopped"
            elif failure:
                job.error = failure["message"]
                self._add(job, {"t": "error", "text": failure["message"], "hint": failure.get("hint", "")})
                job.state = "failed"
            else:
                job.state = "done"
        except (OSError, ConversationError, RuntimeError, ValueError) as e:
            job.error = str(e) or type(e).__name__
            self._add(job, {"t": "error", "text": job.error})
            job.state = "failed"
        finally:
            job.live = None
            self._close_asks(job)

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
        self._events(job, job.parser.finish() if line is None else job.parser.feed(line))

    def _events(self, job: ChatJob, evs: list[dict]) -> None:
        """FORM events from an agent (a CLI's parsed output, or an API agent directly): update what is live, save the rest."""
        adapter = self.adapters[job.agent]
        for ev in evs:
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
                if ev.get("model"):
                    job.model_id = ev["model"]
                    ev["label"] = adapter.model_label(ev["model"])
                    self.learned.learn(job.agent, job.model, ev["model"], ev["label"])
            elif t == "tool":
                job.steps += 1
                job.tools[ev.get("id")] = ev.get("name", "")
            elif t == "result":
                full = ev.pop("full", "") or ""
                self._enrich(job, ev, full)
                if ev.get("name") == "suggest_replies" and ev.get("ok"):
                    opts = self._suggestions(full)
                    self._add(job, ev)
                    if opts:
                        self._add(job, {"t": "suggest", "options": opts})
                    continue
            elif t == "end":
                job.cost = ev.get("cost_usd")
                err = ev.pop("error", None)
                ev.update({"steps": job.steps, "seconds": round(time.time() - job.started, 1), "agent": job.agent})
                self._end_model(job, adapter, ev)
                pid = job.project
                h1 = self._head(pid)
                if pid and h1 is not None and h1 != job.head0:
                    ev["change"] = {"project": pid, "from": job.head0, "to": h1}
                self._add(job, ev)
                if err:
                    job.error = str(err)
                    self._add(job, {"t": "error", "text": job.error})
                continue
            self._add(job, ev)

    def _end_model(self, job: ChatJob, adapter, ev: dict) -> None:
        """Name the model on the reply's footer: from the stream, or from the CLI's own files when it did not say."""
        model = ev.pop("model", None) or job.model_id
        if not model:
            try:
                model = adapter.resolve_model(job.session)
            except Exception:
                model = None
            if model and job.conversation:
                try:
                    self.store.update(job.conversation, resolved_model=model, resolved_agent=job.agent)
                except ConversationError:
                    pass
        if model:
            if model != job.model_id:
                self.learned.learn(job.agent, job.model, model, adapter.model_label(model))
            job.model_id = model
            ev["model"], ev["label"] = model, adapter.model_label(model)

    @staticmethod
    def _suggestions(full: str) -> list[str]:
        try:
            d = json.loads(full)
            opts = d.get("shown") if isinstance(d, dict) else None
        except ValueError:
            opts = None
        if opts is None:
            m = re.search(r"\[.*\]", full, re.S)
            try:
                opts = json.loads(m.group(0)) if m else []
            except ValueError:
                opts = []
        return ask_mod.clean_suggestions(opts if isinstance(opts, list) else [])

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
    """form chat "message" [--project ID] [--conversation ID] [--model X] [--agent ID] [--effort L]
    [--attach FILE ...] [--json]: send one message, stream the reply, save the conversation."""
    import argparse
    from . import config
    ap = argparse.ArgumentParser(prog="form chat", description="Send one message to an agent with Form Studio's tools; the conversation is saved.")
    ap.add_argument("message")
    ap.add_argument("--project")
    ap.add_argument("--conversation", help="continue this conversation (id from `form conversations list`)")
    ap.add_argument("--agent", help="an agent CLI (claude, codex, gemini, cursor, opencode, qwen, copilot) or an API provider "
                                    "(anthropic, openai, google, openrouter, mistral, xai, deepseek, groq, ollama, lmstudio, "
                                    "llamacpp); default: [chat] agent")
    ap.add_argument("--model", help="a model alias or id the agent accepts (default: [chat] model)")
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
        interactive = not a.json and sys.stdin.isatty()     # someone at this terminal can answer the agent's questions
        job = chat.send(a.message, cid, a.project, a.agent, a.model, a.effort, ids, ask=interactive)
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
                    name = ev.get("label") or ev.get("model") or "not reported"
                    print(f"[{ev.get('agent')} · model {name}]", file=sys.stderr, flush=True)
                elif t == "ask" and interactive:
                    _ask_terminal(chat, job, ev)
                elif t == "suggest":
                    print("  next: " + " | ".join(ev.get("options", [])), file=sys.stderr, flush=True)
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


def ask_parse(reply: str, q: dict) -> tuple[list[str], str]:
    """A terminal answer: numbers pick choices ("1" or "1,3"), anything else is the answer in words."""
    cs, r = q.get("choices") or [], reply.strip()
    nums = [x for x in re.split(r"[,\s]+", r) if x]
    if cs and nums and all(x.isdigit() and 1 <= int(x) <= len(cs) for x in nums):
        picked = [cs[int(x) - 1] for x in nums]
        return (picked if q.get("multi") else picked[:1]), ""
    if cs and r in cs:
        return [r], ""
    return [], r


def _ask_terminal(chat: "Chat", job: ChatJob, q: dict) -> None:
    print("\n? " + q.get("question", ""), file=sys.stderr, flush=True)
    if q.get("why"):
        print("  (" + q["why"] + ")", file=sys.stderr, flush=True)
    for i, c in enumerate(q.get("choices") or [], 1):
        print(f"  {i}. {c}", file=sys.stderr, flush=True)
    hint = ("numbers, comma-separated" if q.get("multi") else "a number") if q.get("choices") else ""
    hint += (" or " if hint else "") + "your answer" if q.get("free") else ""
    while True:
        try:
            reply = input(f"  answer ({hint}): ")
        except EOFError:
            return
        picked, text = ask_parse(reply, q)
        if not picked and not text:
            continue
        try:
            chat.answer(job.conversation, q["id"], text, picked)
            return
        except ConversationError as e:
            print(f"  {e}", file=sys.stderr, flush=True)
            if "Pick" not in str(e):
                return


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
