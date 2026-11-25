"""Background work that outlives the call that started it: MCP tasks and pipeline jobs, on disk in the data folder.

    store = TaskStore(st.root)
    rec = store.create("run_pipeline", "desk-stand")      # durable before it returns: tasks/get finds it at once
    store.progress(rec["taskId"], "Checks")              # the status message an agent and the app read
    store.finish(rec["taskId"], "completed", result={...})
    store.get(task_id)                                   # any process; a task whose process stopped reads "failed"
    store.request_cancel(task_id)                        # cooperative: the work stops at its next stage

A task record is <data>/.tasks/<taskId>.json; taskId is <kind>.<project>.<random>, with enough randomness that it
cannot be guessed. Records live TTL_MS (24 h) from creation, then they are purged. A cancel is a marker file next to
the record (<taskId>.cancel), so a cancel from another process (the app) never races the worker's own writes.

The work itself runs with a TaskRun in a context variable (run(...)); code deep in the engine asks cancelled() at
its stage boundaries (Studio._k, between pipeline steps, before a revision is saved) and stops there, and background
jobs the work starts (a pipeline job, a refinement) register as children: a cancel reaches them too, and the MCP
tasks extension (form/mcp_tasks.py) follows them before it calls the task finished.

Pipeline jobs (Studio.run) are kept by JobBook, a dict-like book that writes each job to <data>/.tasks/jobs/<id>.json:
get_job and the app's /job/<id> find a job after the server that ran it has restarted.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterator, MutableMapping
from pathlib import Path
from typing import Any

DIR = ".tasks"
TTL_MS = 24 * 3600 * 1000
POLL_MS = 1000
STATUSES = ("working", "input_required", "completed", "failed", "cancelled")
TERMINAL = ("completed", "failed", "cancelled")
EVENTS_KEPT = 40
PROGRESS_EVERY_S = 0.25           # progress writes at most this often (the last one always lands)
INTERNAL_ERROR = -32603
GONE = "The Form Studio process that was running this task stopped (the server was restarted or quit)."

_lock = threading.RLock()
_LIVE: dict[str, "TaskRun"] = {}                     # task id -> its run, for the tasks running in this process
_CURRENT: contextvars.ContextVar["TaskRun | None"] = contextvars.ContextVar("form_task", default=None)


def _alive(os_pid) -> bool:
    try:
        os.kill(int(os_pid), 0)
        return True
    except PermissionError:                         # exists, owned by someone else
        return True
    except (OSError, TypeError, ValueError):
        return False


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + f".{int((ts % 1) * 1000):03d}Z"


def _safe(part: str, n: int = 48) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(part or "")).strip("-")[:n] or "-"


def _fname(tid: str) -> str:
    """A task id as a file name: its own dots kept, nothing that leaves the folder."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(tid or "")).lstrip(".")[:200] or "-"


def _write_json(f: Path, body: dict) -> None:
    from . import fsutil
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(body, indent=1, default=str), encoding="utf-8")
    fsutil.replace(tmp, f)


def _read_json(f: Path) -> dict | None:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class TaskStore:
    """The task records of one data folder."""

    def __init__(self, root: Path | str):
        self.dir = Path(root) / DIR
        self._purged = 0.0

    # ---- records ---------------------------------------------------------
    def path(self, tid: str) -> Path:
        return self.dir / f"{_fname(tid)}.json"

    def _marker(self, tid: str) -> Path:
        return self.dir / f"{_fname(tid)}.cancel"

    @staticmethod
    def new_id(kind: str, project: str | None = None) -> str:
        return f"{_safe(kind, 32)}.{_safe(project or 'new')}.{secrets.token_hex(12)}"

    def create(self, kind: str, project: str | None = None, tool: str = "", **extra) -> dict:
        """A new working task, written to disk before it returns."""
        self.purge()
        now = time.time()
        tid = self.new_id(kind, project)
        rec = {"taskId": tid, "kind": kind, "project": project or None, "tool": tool or kind, "status": "working",
               "statusMessage": "Started", "created": now, "updated": now, "ttlMs": TTL_MS, "pollIntervalMs": POLL_MS,
               "os_pid": os.getpid(), "events": [], **extra}
        with _lock:
            _write_json(self.path(tid), rec)
        return rec

    def _load(self, tid: str) -> dict | None:
        rec = _read_json(self.path(tid))
        return rec if isinstance(rec, dict) and rec.get("taskId") == tid else None

    def get(self, tid: str) -> dict | None:
        """The record, or None (unknown or expired). A task still working in a process that is gone reads failed."""
        if not isinstance(tid, str) or not tid:
            return None
        with _lock:
            rec = self._load(tid)
            if rec is None:
                return None
            if self._expired(rec):
                self._drop(tid)
                return None
            if rec["status"] not in TERMINAL and tid not in _LIVE and not _alive(rec.get("os_pid")):
                rec = self._set(rec, status="failed", statusMessage=GONE,
                                error={"code": INTERNAL_ERROR, "message": GONE})
            if rec["status"] not in TERMINAL and self._marker(tid).exists():
                rec["cancel_requested"] = True
            return rec

    def _set(self, rec: dict, **fields) -> dict:
        rec = {**rec, **fields, "updated": time.time()}
        _write_json(self.path(rec["taskId"]), rec)
        return rec

    def update(self, tid: str, **fields) -> dict | None:
        with _lock:
            rec = self._load(tid)
            if rec is None or rec["status"] in TERMINAL:
                return rec
            return self._set(rec, **fields)

    def progress(self, tid: str, text: str, fraction: float | None = None, event: bool = True) -> None:
        with _lock:
            rec = self._load(tid)
            if rec is None or rec["status"] in TERMINAL:
                return
            fields: dict[str, Any] = {"statusMessage": str(text)[:400]}
            if fraction is not None:
                fields["progress"] = max(0.0, min(1.0, float(fraction)))
            if event and text and text != rec.get("statusMessage"):
                fields["events"] = (rec.get("events") or [])[-(EVENTS_KEPT - 1):] + \
                    [{"ts": time.time(), "text": str(text)[:400]}]
            self._set(rec, **fields)

    def finish(self, tid: str, status: str, result: dict | None = None, error: dict | None = None,
               message: str | None = None, **extra) -> dict | None:
        assert status in TERMINAL, status
        with _lock:
            rec = self._load(tid)
            if rec is None:
                return None
            fields: dict[str, Any] = {"status": status, "finished": time.time(), **extra}
            if message is not None:
                fields["statusMessage"] = str(message)[:1000]
            if status == "completed":
                fields["result"] = result if result is not None else {}
            if status == "failed":
                fields["error"] = error or {"code": INTERNAL_ERROR, "message": message or "The task failed."}
            rec = self._set(rec, **fields)
            self._marker(tid).unlink(missing_ok=True)
            return rec

    # ---- cancel ----------------------------------------------------------
    def request_cancel(self, tid: str) -> dict | None:
        """Ask a task to stop. None for an unknown task; a finished task is left as it is."""
        rec = self.get(tid)
        if rec is None:
            return None
        if rec["status"] in TERMINAL:
            return rec
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._marker(tid).write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        run = _LIVE.get(tid)
        if run is not None:
            run.cancel()
        return {**rec, "cancel_requested": True}

    def cancel_requested(self, tid: str) -> bool:
        return self._marker(tid).exists()

    # ---- listing and expiry ------------------------------------------------
    @staticmethod
    def _expired(rec: dict) -> bool:
        ttl = rec.get("ttlMs")
        return ttl is not None and (time.time() - float(rec.get("created") or 0)) * 1000 > float(ttl)

    def _drop(self, tid: str) -> None:
        self.path(tid).unlink(missing_ok=True)
        self._marker(tid).unlink(missing_ok=True)

    def purge(self, force: bool = False) -> int:
        """Remove expired task records (at most once a minute unless force)."""
        if not force and time.time() - self._purged < 60:
            return 0
        self._purged = time.time()
        n = 0
        try:
            files = list(self.dir.glob("*.json"))
        except OSError:
            return 0
        for f in files:
            rec = _read_json(f)
            if isinstance(rec, dict) and rec.get("taskId") and self._expired(rec) and rec["taskId"] not in _LIVE:
                with _lock:
                    self._drop(rec["taskId"])
                n += 1
        return n

    def list(self, project: str | None = None, active: bool = False) -> list[dict]:
        """Every task record (newest first): one progress and cancel list for the bench and the app."""
        out = []
        try:
            files = list(self.dir.glob("*.json"))
        except OSError:
            return out
        for f in files:
            rec = _read_json(f)
            if not isinstance(rec, dict) or not rec.get("taskId"):
                continue
            rec = self.get(rec["taskId"])
            if rec is None or (project and rec.get("project") != project) or (active and rec["status"] in TERMINAL):
                continue
            out.append(rec)
        return sorted(out, key=lambda r: -float(r.get("created") or 0))

    # ---- wire shapes (io.modelcontextprotocol/tasks, schema 2026-07-28) -------
    @staticmethod
    def task(rec: dict) -> dict:
        """The Task fields of a record."""
        out = {"taskId": rec["taskId"], "status": rec["status"], "createdAt": _iso(float(rec["created"])),
               "lastUpdatedAt": _iso(float(rec.get("updated") or rec["created"])), "ttlMs": rec.get("ttlMs"),
               "pollIntervalMs": rec.get("pollIntervalMs", POLL_MS)}
        if rec.get("statusMessage"):
            out["statusMessage"] = rec["statusMessage"]
        return out

    def created(self, rec: dict) -> dict:
        """CreateTaskResult: what tools/call returns in place of its result."""
        return {"resultType": "task", **self.task(rec)}

    def detailed(self, rec: dict) -> dict:
        """GetTaskResult: the task with its status's own field (result, error or inputRequests)."""
        out = {"resultType": "complete", **self.task(rec)}
        if rec["status"] == "completed":
            out["result"] = rec.get("result") or {}
        elif rec["status"] == "failed":
            out["error"] = rec.get("error") or {"code": INTERNAL_ERROR, "message": rec.get("statusMessage") or "failed"}
        elif rec["status"] == "input_required":
            out["inputRequests"] = rec.get("inputRequests") or {}
        if rec.get("kept"):                         # what a cancelled task kept: revisions, or a draft
            out["_meta"] = {"form/kept": rec["kept"]}
        return out


# ---- the run of one task, in a context variable ------------------------------

class TaskRun:
    """One task running in this process: its cancel flag, the background jobs it started, what it kept."""

    def __init__(self, store: TaskStore, tid: str, tool: str = ""):
        self.store, self.id, self.tool = store, tid, tool
        self._event = threading.Event()
        self._checked = 0.0
        self._last_progress = 0.0
        self._pending: tuple | None = None
        self.children: list[dict] = []
        self.saved: dict[str, int] = {}             # project -> head saved while this task ran
        self.draft: dict | None = None              # the last stage built for a design that was not saved
        self._lock = threading.Lock()

    # cancel
    def cancel(self) -> None:
        self._event.set()
        for c in list(self.children):
            try:
                c["cancel"]()
            except Exception:                        # noqa: BLE001 - a child that cannot stop finishes on its own
                pass

    def cancelled(self) -> bool:
        if self._event.is_set():
            return True
        now = time.monotonic()
        if now - self._checked >= 0.2:              # a cancel from another process: the marker file
            self._checked = now
            if self.store.cancel_requested(self.id):
                self.cancel()
                return True
        return False

    # progress
    def progress(self, text: str, fraction: float | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress < PROGRESS_EVERY_S:
            self._pending = (text, fraction)
            return
        self._last_progress = now
        self._pending = None
        self.store.progress(self.id, text, fraction)

    def flush(self) -> None:
        p = self._pending
        if p:
            self._pending = None
            self.store.progress(self.id, p[0], p[1])

    # children and what was kept
    def add_child(self, kind: str, cid: str, project: str | None, cancel: Callable[[], Any],
                  done: Callable[[], bool], text: Callable[[], str] = lambda: "") -> None:
        with self._lock:
            self.children.append({"kind": kind, "id": cid, "project": project, "cancel": cancel, "done": done,
                                  "text": text})
        if self._event.is_set():
            try:
                cancel()
            except Exception:                        # noqa: BLE001
                pass


def run(store: TaskStore, tid: str, tool: str = "") -> TaskRun:
    """Register a task as running in this process; set it as current with use()."""
    r = TaskRun(store, tid, tool)
    _LIVE[tid] = r
    return r


def done(r: TaskRun) -> None:
    r.flush()
    _LIVE.pop(r.id, None)


def use(r: TaskRun | None) -> contextvars.Token:
    return _CURRENT.set(r)


def current() -> TaskRun | None:
    return _CURRENT.get()


def cancelled() -> bool:
    """Whether the task this code runs for (if any) was asked to stop."""
    r = _CURRENT.get()
    return bool(r and r.cancelled())


def progress(text: str, fraction: float | None = None) -> None:
    r = _CURRENT.get()
    if r is not None:
        r.progress(text, fraction)


def child(kind: str, cid: str, project: str | None, cancel: Callable[[], Any], done: Callable[[], bool],
          text: Callable[[], str] = lambda: "") -> None:
    """A background job the current task started (no-op outside a task)."""
    r = _CURRENT.get()
    if r is not None and cid:
        r.add_child(kind, cid, project, cancel, done, text)


def note_saved(project: str | None, head: int | None) -> None:
    r = _CURRENT.get()
    if r is not None and project and head is not None:
        r.saved[str(project)] = int(head)


def note_draft(draft: str, feature: str, index: int, name: str = "") -> None:
    r = _CURRENT.get()
    if r is not None:
        r.draft = {"draft": draft, "feature": feature, "index": index, "name": name}


# ---- pipeline jobs that survive a restart ---------------------------------------

class JobBook(MutableMapping):
    """Studio.jobs: pipeline (and photo) jobs by id. A job is a plain dict the thread running it changes in place;
    save(job) writes it to <data>/.tasks/jobs/<id>.json. A job this process does not hold is read from disk; one
    that was running in a process that is gone reads failed. Finished jobs past MEMORY are dropped from memory only;
    files older than TTL_MS are purged."""

    MEMORY = 50

    def __init__(self, root: Path | str):
        self.dir = Path(root) / DIR / "jobs"
        self._mem: dict[str, dict] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._purged = 0.0

    def _file(self, jid: str) -> Path:
        return self.dir / f"{_safe(jid, 64)}.json"

    def save(self, job: dict) -> None:
        jid = job.get("id")
        if not jid or jid not in self._mem:
            return
        body = {k: v for k, v in job.items() if not k.startswith("_")}
        body.setdefault("os_pid", os.getpid())
        try:
            with _lock:
                _write_json(self._file(jid), body)
        except (OSError, TypeError, ValueError):
            pass

    def __setitem__(self, jid: str, job: dict) -> None:
        job.setdefault("os_pid", os.getpid())
        self._mem[jid] = job
        self.save(job)
        self._trim()

    def _trim(self) -> None:
        if len(self._mem) <= self.MEMORY:
            return
        for k in list(self._mem)[:-self.MEMORY]:
            if self._mem[k].get("state") != "running":
                self._mem.pop(k, None)
                self._cancel.pop(k, None)
        if time.time() - self._purged > 600:
            self._purged = time.time()
            self.purge()

    def _disk(self, jid: str) -> dict | None:
        rec = _read_json(self._file(jid))
        if not isinstance(rec, dict) or rec.get("id") != jid:
            return None
        if rec.get("state") in ("running", "queued") and not _alive(rec.get("os_pid")):
            rec = {**rec, "state": "failed", "error": {"message": GONE.replace("this task", "this job"),
                                                        "hint": "Run the pipeline again; finished outputs are reused."}}
            for s in rec.get("steps") or []:
                if s.get("state") in ("running", "queued"):
                    s["state"] = "failed" if s.get("state") == "running" else "blocked"
        return rec

    def __getitem__(self, jid: str) -> dict:
        if jid in self._mem:
            return self._mem[jid]
        rec = self._disk(jid) if isinstance(jid, str) else None
        if rec is None:
            raise KeyError(jid)
        return rec

    def __contains__(self, jid) -> bool:
        return isinstance(jid, str) and (jid in self._mem or self._disk(jid) is not None)

    def __delitem__(self, jid: str) -> None:
        self._mem.pop(jid, None)
        self._file(jid).unlink(missing_ok=True)

    def _ids(self) -> list[str]:
        ids = list(self._mem)
        try:
            ids += [f.stem for f in self.dir.glob("*.json") if f.stem not in self._mem]
        except OSError:
            pass
        return ids

    def __iter__(self) -> Iterator[str]:
        return iter(self._ids())

    def __len__(self) -> int:
        return len(self._ids())

    def values(self):                               # noqa: D401 - a list, so a running thread can change the book
        out = []
        for k in self._ids():
            try:
                out.append(self[k])
            except KeyError:
                pass
        return out

    # cancel (cooperative: Studio._run stops before its next step)
    def request_cancel(self, jid: str) -> bool:
        if jid not in self:
            return False
        self._cancel.setdefault(jid, threading.Event()).set()
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{_safe(jid, 64)}.cancel").write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        return True

    def cancel_requested(self, jid: str) -> bool:
        ev = self._cancel.get(jid)
        return bool(ev and ev.is_set()) or (self.dir / f"{_safe(jid, 64)}.cancel").exists()

    def clear_cancel(self, jid: str) -> None:
        self._cancel.pop(jid, None)
        (self.dir / f"{_safe(jid, 64)}.cancel").unlink(missing_ok=True)

    def purge(self) -> int:
        n = 0
        try:
            files = list(self.dir.glob("*.json"))
        except OSError:
            return 0
        cut = time.time() - TTL_MS / 1000
        for f in files:
            try:
                if f.stat().st_mtime < cut and f.stem not in self._mem:
                    f.unlink(missing_ok=True)
                    (self.dir / f"{f.stem}.cancel").unlink(missing_ok=True)
                    n += 1
            except OSError:
                pass
        return n
