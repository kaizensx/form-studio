"""Refinement after every build: one background job per project, its progress on disk, cancelled by the next edit.

    jobs.after_design(st, pid, origin="agent")   # what create_design, update_design and add_feature call
    jobs.status(st, pid)                         # {"state": "running" | "done" | ..., "stage", "events", "applied"}
    jobs.wait(st, pid, 60)                       # until the job has finished (benches, refine_design(wait=))
    jobs.cancel(pid)

The design that was just built is already a revision, on screen, when refinement starts: the job measures it, runs
the search (form/refine/engine.py) and lands what it keeps as one new revision, "Refined: N changes". A new edit of
the same project cancels the job that is running (its result would be for a design that is gone; the commit also
passes expect_head, so a late result never overwrites a newer revision) and starts a new one after the edit.

Progress is written to <project>/refine.json (any process can read it: the app shows it while the MCP server that
made the design runs the job) and to the activity log (kind "refine"), stage by stage. When the app's engine for the
same data folder is running in another process, the job runs there instead (POST /api/projects/<id>/refine), so it
does not end with an agent's MCP server. Off: refine="off" on the call, `refine = False` on the design class,
[refine] enabled = false (Settings), or FORM_REFINE=off. A game asset is refined only when asked: refine="on",
the design turned on (set_project "on"), or [refine] game = true (Settings › Refine game assets).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

FILE = "refine.json"
EVENTS_KEPT = 40
SKIP_ORIGINS = ("refine",)              # a refinement's own revision (and its undo) does not start another one
_RUN: dict = {}                         # pid -> {"id", "cancel": Event, "thread"}
_lock = threading.Lock()


def _path(st, pid: str):
    return st.dir(pid) / FILE


def _write(st, pid: str, rec: dict) -> None:
    from .. import fsutil
    try:
        f = _path(st, pid)
        tmp = f.with_name(f".{FILE}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
        fsutil.replace(tmp, f)
    except OSError:
        pass


def _read(st, pid: str) -> dict | None:
    try:
        return json.loads(_path(st, pid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(os_pid) -> bool:
    from ..procs import pid_alive
    return pid_alive(os_pid)


def status(st, pid: str) -> dict:
    """The project's refinement record. A job that was running in a process that is gone reads "interrupted"."""
    rec = _read(st, pid) or {"state": "none"}
    if rec.get("state") in ("running", "queued") and pid not in _RUN and not _alive(rec.get("os_pid")):
        rec = {**rec, "state": "interrupted", "stage": "The process that was refining this design stopped."}
    try:
        from . import engine
        rec["changes"] = engine.changes(st, st.load(pid))
    except Exception:                                    # noqa: BLE001 - a status read never fails over this
        rec.setdefault("changes", [])
    rec["enabled"] = enabled_text(st, pid)
    return rec


def enabled_text(st, pid: str) -> dict:
    from . import engine
    try:
        p = st.load(pid)
        src = st.source_text(p) or ""
        on, why = engine.enabled(getattr(st, "cfg", {}), src, engine.asked(p, None), engine.is_game(p, src))
    except Exception as e:                               # noqa: BLE001
        on, why = False, str(e)
    return {"on": on, "why": why}


def by_id(jid: str, st=None) -> dict | None:
    """A refinement job by id: running in this process, or (with st) the last job a project's refine.json records,
    so a job is found after the process that ran it has stopped."""
    for pid, j in list(_RUN.items()):
        if j["id"] == jid:
            return {"id": jid, "project": pid, "state": "running"}
    if st is not None:
        try:
            for f in st.root.glob(f"*/{FILE}"):
                rec = _read(st, f.parent.name)
                if rec and rec.get("job") == jid:
                    s = status(st, f.parent.name)
                    return {"id": jid, "project": f.parent.name, "state": s.get("state"), "stage": s.get("stage")}
        except OSError:
            pass
    return None


def cancel(pid: str) -> bool:
    j = _RUN.get(pid)
    if j is None:
        return False
    j["cancel"].set()
    return True


def wait(st, pid: str, timeout: float = 60.0, poll: float = 0.25) -> dict:
    """The status once the job has finished (or after timeout seconds, still running)."""
    t0 = time.monotonic()
    while True:
        rec = status(st, pid)
        if rec.get("state") not in ("running", "queued") or time.monotonic() - t0 >= timeout:
            return rec
        time.sleep(poll)


def _delegate(st, pid: str, refine, kw: dict) -> str | None:
    """Run the job in the app's engine when one serves this data folder from another process. The job id, or None."""
    if os.environ.get("FORM_REFINE_LOCAL") or kw:
        return None
    import urllib.request
    cfg = getattr(st, "cfg", {}) or {}
    host, port = (cfg.get("server") or {}).get("host", "127.0.0.1"), int((cfg.get("server") or {}).get("port", 4173))
    url = os.environ.get("FORM_ENGINE_URL") or f"http://{host}:{port}"      # the app sets it for what it starts
    if not url.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
        return None
    try:
        with urllib.request.urlopen(url + "/api/refine/host", timeout=0.4) as r:
            info = json.loads(r.read())
        if info.get("data_dir") != str(st.root) or int(info.get("pid") or 0) == os.getpid():
            return None
        req = urllib.request.Request(url + f"/api/projects/{pid}/refine", method="POST",
                                     data=json.dumps({"action": "start", "refine": refine}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as r:
            return (json.loads(r.read()) or {}).get("job") or "delegated"
    except Exception:                                    # noqa: BLE001 - no app engine: run it here
        return None


def after_design(st, pid: str, origin: str = "agent", refine=None) -> str | None:
    """Start refining a design that was just built (create_design, update_design, add_feature, a kept candidate,
    a game asset's design). None when it is off or the revision is refinement's own."""
    if origin in SKIP_ORIGINS:
        return None
    try:
        return start(st, pid, refine)
    except Exception:                                    # noqa: BLE001 - refinement never breaks the build it follows
        return None


def start(st, pid: str, refine=None, **kw) -> str | None:
    """A background refinement of the project's head. Cancels the one running for it. The job id, or None when off
    (the reason goes to refine.json as state "off")."""
    from . import engine
    p = st.load(pid)
    src = st.source_text(p) or ""
    on, why = engine.enabled(getattr(st, "cfg", {}), src, engine.asked(p, refine), engine.is_game(p, src))
    if not on and p.get("refine") == "off" and refine in (None, "auto", ""):
        why = "refinement is off for this design (refine_design action=\"off\", or create_design refine=\"off\")"
    cancel(pid)
    if not on:
        _write(st, pid, {"state": "off", "why": why, "rev": p["head"], "finished": time.time()})
        return None
    remote = _delegate(st, pid, refine, kw)
    if remote:
        return remote
    jid = uuid.uuid4().hex[:10]
    ev = threading.Event()
    rec = {"job": jid, "state": "running", "from_rev": p["head"], "started": time.time(), "os_pid": os.getpid(),
           "stage": "Measuring the design", "events": [], "applied": []}
    _write(st, pid, rec)
    st.activity(pid, "refine", f"Refining r{p['head']:02d}: measuring the design", by="engine", stage="start", job=jid)

    def progress(e: dict):
        if ev.is_set():                                  # cancelled: a newer job owns the record
            return
        k = e.get("kind")
        if k == "refine_try":
            text = "Trying " + ", ".join(dict.fromkeys(x.lower() for x in e.get("labels") or []))
        elif k == "refine_round":
            kept = [c for c in e.get("candidates") or [] if c.get("kept")]
            text = (f"Round {e.get('round')}: " + (", ".join(c["operator"].replace("_", " ") for c in kept) + " helped"
                                                    if kept else "nothing helped enough"))
        else:
            text = e.get("text") or k or ""
        rec["stage"] = text
        rec["events"] = (rec["events"] + [{"ts": time.time(), "kind": k, "text": text}])[-EVENTS_KEPT:]
        _write(st, pid, rec)
        st.activity(pid, "refine", f"Refining: {text}", by="engine", stage=k, job=jid)

    def run():
        try:
            r = engine.refine(st, pid, refine, progress=progress, cancel=ev.is_set, **kw)
            rec.update(finished=time.time(), seconds=r.get("wall_s"), budget_s=r.get("budget_s"),
                       stopped=r.get("stopped"), skipped=r.get("skipped"), style=r.get("style"),
                       base=(r.get("base") or {}).get("total"), final=(r.get("final") or {}).get("total"),
                       head=r.get("head"), measure=r.get("measure"),
                       rejected=[{"operator": x["operator"], "why": (x.get("why") or [""])[0]}
                                 for x in r.get("rejected") or []][:12],
                       applied=[{k: a.get(k) for k in ("id", "label", "reason", "kind", "operator", "deltas")}
                                for a in r.get("applied") or []])
            if ev.is_set():
                rec.update(state="cancelled", stage="Cancelled: the design changed")
            elif r.get("commit_error"):
                rec.update(state="done", stage="Not kept: " + str((r["commit_error"] or {}).get("message", ""))[:200],
                           commit_error=r["commit_error"])
            elif r.get("skipped"):
                rec.update(state="skipped", stage=r["skipped"])
            elif r.get("head"):
                n = len(r["applied"])
                rec.update(state="done", stage=f"Refined: {n} change{'s' if n != 1 else ''}")
            else:
                rec.update(state="done", stage="Nothing to add: " + str(r.get("stopped") or ""))
        except Exception as e:                           # noqa: BLE001 - reported on the record
            rec.update(state="failed", finished=time.time(), error=f"{type(e).__name__}: {e}"[:400],
                       stage="Refinement failed")
        finally:
            with _lock:
                if (_RUN.get(pid) or {}).get("id") == jid:
                    _RUN.pop(pid, None)
            if (_read(st, pid) or {}).get("job") in (jid, None):     # a newer job owns the record: leave it
                _write(st, pid, rec)
            st.activity(pid, "refine", rec.get("stage") or "", by="engine", stage=rec["state"], job=jid,
                        **({"head": rec["head"]} if rec.get("head") else {}))
    th = threading.Thread(target=run, daemon=True, name=f"refine-{pid}")
    with _lock:
        _RUN[pid] = {"id": jid, "cancel": ev, "thread": th}
    th.start()
    from .. import taskstore                             # a task that started it can follow and cancel it
    taskstore.child("refine", jid, pid, ev.set, lambda: (_RUN.get(pid) or {}).get("id") != jid,
                    lambda: "Refining: " + str(rec.get("stage") or ""))
    return jid


def task_id(pid: str, jid: str) -> str:
    """The task id a refinement job has in the task list (form/taskstore.py: <kind>.<project>.<job>)."""
    return f"refine.{pid}.{jid}"


def set_project(st, pid: str, value: str | None) -> dict:
    """Turn automatic refinement off ("off"), on ("on": also for a game asset, which is not refined unless asked) or
    back to the default (None) for one design (the project's "refine" field)."""
    with st.lock(pid):
        p = st.load(pid)
        if value is None:
            p.pop("refine", None)
        else:
            p["refine"] = value
        st.save(p)
    if value == "off":
        cancel(pid)
        _write(st, pid, {**(_read(st, pid) or {}), "state": "off",
                         "why": "refinement is off for this design", "finished": time.time()})
    return {"project": pid, "refine": value or "auto"}


def reset_ledger() -> dict:
    """Empty what refinement learned on this machine (the Settings' reset control)."""
    from . import ledger
    led = ledger.Ledger.open()
    n = len(led.rows)
    led.reset()
    return {"ok": True, "rows": n, "file": str(led.path)}
