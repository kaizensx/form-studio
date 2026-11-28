"""The Bench: every study, route and document that can be asked of a design, as a record.

One registry lists them. Each entry has an id, a group (a study for Review, a route or a document for Make), what it
needs, the inputs it is keyed by, its evidence class and a runner wired to the code that does the work. Its state is
never set by hand: an entry is current only when a result exists under the key computed from the head revision's
inputs (Studio.keys and the entry's own inputs), so a commit that changes an input makes it stale by construction.

    never run   no result, ever
    current     a result under the head's key (it says which revision it was computed from)
    stale       results exist, none under the head's key: it says the revision the newest one describes
    failed      the last run under the head's key failed, with why
    running     a run is under way
    unavailable it applies, but something it needs is missing here (Blender, a slicer, a current slice), with why
    n/a         it does not apply to this design (a print study on a 3D model, an assembly study on one part)

Results the Bench runs are stored beside the revision under <project>/artifacts/studies/<id>/<key>.json, with a log
of every run; entries backed by the pipeline (solid, exports, checks, slice) read the pipeline's own record, and
entries whose code keeps its own cache (analysis maps, documents, renders) are found there without computing.

Later waves register here and only add entries: register(Study(...)), or a module named in PROVIDERS with a
register_studies(register) function.

Headless: `form study list|run|show <project> [id]` (JSON) and the MCP tools list_studies, run_study, get_study."""
from __future__ import annotations

import importlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VERSION = 1
GROUPS = {"study": "Studies", "route": "Routes", "document": "Documents"}
STAGE = {"study": "prove", "route": "release", "document": "release"}     # the stage whose pane lists the group
STATES = ("never", "current", "stale", "failed", "running", "unavailable", "n/a")
BY = ("engine", "agent", "person")       # who runs it: Form Studio here, the agent (it must look), or a person
PROVIDERS: tuple = ("form.fea.bench",)   # modules of later waves: each has register_studies(register)
RUNNING_TTL = 6 * 3600                   # a run marker older than this is a process that died, not a run


def _err(msg: str, hint: str = "", status: int = 409):
    from .studio import StudioError
    return StudioError(msg, hint, status=status)


@dataclass(frozen=True)
class Study:
    id: str
    group: str                                   # study | route | document
    label: str
    doc: str                                     # one sentence: what it establishes or makes
    evidence: str                                # the evidence class of its headline (principle 2 of the plan)
    run: Callable | None = None                  # run(ctx) -> {"headline", "evidence"?, "detail"?, "files"?, "data"?}
    key: Callable | None = None                  # key(ctx) -> str; default: the geometry key and VERSION
    needs: tuple = ()                            # applies-when and can-run-when conditions (NEEDS)
    inputs: tuple = ("geometry",)                # what its key is made of, in words, for agents
    node: str | None = None                      # backed by this pipeline node (state from Studio.status)
    probe: Callable | None = None                # probe(ctx) -> a result already made for the head's key, or None
    headline: Callable | None = None             # headline(ctx, data) for node-backed entries
    state_fn: Callable | None = None             # state_fn(ctx) -> full state, for entries with their own record
    by: str = "engine"
    app: str = ""                                # what the window opens for it (QML Bench.qml maps it)
    tool: str = ""                               # the MCP tool that does the same work with more options
    heavy: bool = False                          # minutes, not seconds
    live: bool = False                           # cheap and computed when listed: always current
    order: int = 100
    extra: dict = field(default_factory=dict)


# ---- the registry ---------------------------------------------------------------------------------------------
_REG: dict[str, Study] = {}
_LOADED = [False]
_LOCK = threading.RLock()


def register(s: Study) -> Study:
    """Add or replace one entry (by id). Later waves call this; nothing else needs to change for them to appear in
    the Bench, the palette, `form study` and list_studies."""
    if s.group not in GROUPS:
        raise ValueError(f"group is one of {', '.join(GROUPS)}")
    if s.by not in BY:
        raise ValueError(f"by is one of {', '.join(BY)}")
    if s.by == "engine" and s.run is None and s.node is None and not s.live:
        raise ValueError(f"{s.id}: an engine study needs a runner or a pipeline node")
    with _LOCK:
        _REG[s.id] = s
    return s


def registry() -> list[Study]:
    with _LOCK:
        if not _LOADED[0]:
            _LOADED[0] = True
            _builtin()
            for mod in PROVIDERS:
                importlib.import_module(mod).register_studies(register)
        return sorted(_REG.values(), key=lambda s: (list(GROUPS).index(s.group), s.order, s.id))


def get(sid: str) -> Study:
    for s in registry():
        if s.id == sid:
            return s
    raise _err(f"Unknown study “{sid}”.", "list_studies (or `form study list <project>`) names every entry.", 404)


# ---- context: one snapshot of the design, its keys and status, shared by every entry of one listing -----------
class Ctx:
    def __init__(self, st, p: dict):
        self.st, self.p = st, p
        self._keys = self._status = self._gate = None

    @property
    def keys(self) -> dict:
        if self._keys is None:
            self._keys = self.st.keys(self.p)
        return self._keys

    @property
    def status(self) -> dict:
        if self._status is None:
            self._status = self.st.status(self.p)
        return self._status

    @property
    def rev(self) -> dict:
        return self.st.rev(self.p)

    @property
    def recipe(self):
        return self.st.recipe(self.p)

    def current(self, node: str):
        return self.st.read(self.p, node, self.keys[node]) if self.status[node]["state"] == "current" else None


def H(*a) -> str:
    from .studio import H as _h
    return _h(*a)


# ---- needs: does it apply, and can it run here -----------------------------------------------------------------
def _printing(ctx) -> bool:
    from . import purpose
    return purpose.printing(ctx.st.cfg) and not purpose.is_model(ctx.p)


def _assembly(ctx) -> bool:
    try:
        return ctx.st._declares_assembly(ctx.recipe) and ctx.recipe.assembly(ctx.rev["values"]) is not None
    except Exception:
        return False


def _joints(ctx) -> bool:
    try:
        spec = ctx.recipe.assembly(ctx.rev["values"]) if ctx.st._declares_assembly(ctx.recipe) else None
        return bool(spec is not None and spec.joints)
    except Exception:
        return False


def _contract(ctx) -> bool:
    from . import contract
    try:
        return bool(contract.of(ctx.p)) or any(f["expects"] for f in contract._features(ctx.st, ctx.p))
    except Exception:
        return bool(contract.of(ctx.p))


def _step(ctx) -> bool:
    return not getattr(ctx.recipe, "mesh", False)


# applies-when: a False is "n/a" with the reason
APPLIES = {
    "print": (_printing, "Only for a design made for 3D printing (3D printing is off, or this is a 3D model)."),
    "assembly": (_assembly, "Only for a design of several parts with an assembly() declaration."),
    "joints": (_joints, "Only for an assembly with joints."),
    "fit": (lambda c: bool(c.recipe.fit) and _printing(c), "Only for a printed design with a declared fit."),
    "contract": (_contract, "Only for a design with a brief's requirements (design_brief) or expects=."),
    "step": (_step, "A mesh design (OpenSCAD) has no STEP file."),
    "game": (lambda c: __import__("form.purpose", fromlist=["is_game"]).is_game(c.p), "Only for a game asset design."),
}


def _need_slice(ctx):
    s = ctx.status["slice"]
    if s["state"] == "current":
        return None
    if s.get("unavailable"):
        return "No slicer: " + s["unavailable"]
    return "Needs a current slice (run the Slice entry first)."


def _need_exports(ctx):
    return None if ctx.status["exports"]["state"] == "current" else "Needs current STEP and STL (run the Exports entry first)."


def _need_slicer(ctx):
    s = ctx.st.slicer_info(p=ctx.p)
    return None if s.get("available") else "The slicer cannot run here: " + str(s.get("reason") or "none is set up (Settings, Software).")


def _need_blender(ctx):
    from . import photo
    b = photo.blender(ctx.st.cfg)
    return None if b.get("available") else "Blender is not installed (Settings, Engines & software)."


def _need_freecad(ctx):
    return None if ctx.st._freecad() else "FreeCAD is not installed (Settings, Engines & software)."


def _need_review(ctx):
    return None


# can-run-when: a reason is "unavailable" (it applies, something is missing here)
READY = {"slice": _need_slice, "exports": _need_exports, "slicer": _need_slicer, "blender": _need_blender,
         "freecad": _need_freecad}


def _applies(ctx, s: Study) -> tuple[bool, str]:
    for n in s.needs:
        if n in APPLIES:
            ok, why = APPLIES[n]
            try:
                if not ok(ctx):
                    return False, why
            except Exception as e:                       # noqa: BLE001 - a broken design: say so, never crash the list
                return False, f"Could not tell: {e}"
    return True, ""


def _ready(ctx, s: Study) -> str:
    for n in s.needs:
        if n in READY:
            why = READY[n](ctx)
            if why:
                return why
    return ""


# ---- the store: results beside the revision -------------------------------------------------------------------
def _dir(st, p, sid: str) -> Path:
    return st.dir(p["id"]) / "artifacts" / "studies" / sid


def _key(ctx, s: Study) -> str:
    if s.node:
        return ctx.keys[s.node]
    base = s.key(ctx) if s.key else ctx.keys["geometry"]
    return H("study", s.id, VERSION, base)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    from . import fsutil
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    fsutil.replace(tmp, path)


def log(st, p, sid: str) -> list:
    return _read(_dir(st, p, sid) / "log.json") or []


def _record(st, p, sid: str, key: str, rev: int, ok: bool, result: dict | None = None, error: dict | None = None,
            seconds: float | None = None) -> None:
    d = _dir(st, p, sid)
    if ok:
        _write(d / f"{key}.json", {**(result or {}), "id": sid, "key": key, "rev": rev, "ts": time.time(), "seconds": seconds,
                                   "version": VERSION})
        (d / f"{key}.failed.json").unlink(missing_ok=True)
    else:
        _write(d / f"{key}.failed.json", {"error": error or {}, "rev": rev, "ts": time.time()})
    with st.lock(p["id"]):                            # the log is shared by every process that runs studies
        entries = log(st, p, sid)
        entries.append({"key": key, "rev": rev, "ts": time.time(), "ok": bool(ok)})
        _write(d / "log.json", entries[-60:])


def _marker(st, p, sid: str, key: str) -> Path:
    return _dir(st, p, sid) / f"{key}.running"


def _running(st, p, sid: str, key: str) -> dict | None:
    m = _read(_marker(st, p, sid, key))
    if not m:
        return None
    if time.time() - m.get("ts", 0) > RUNNING_TTL or not _alive(m.get("pid")):
        _marker(st, p, sid, key).unlink(missing_ok=True)
        return None
    return m


def _alive(pid) -> bool:
    if not pid:
        return False
    if pid == os.getpid():
        return True
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, AttributeError):
        return False


# ---- one entry's state ----------------------------------------------------------------------------------------
def _base(ctx, s: Study) -> dict:
    return {"id": s.id, "group": s.group, "group_label": GROUPS[s.group], "stage": STAGE[s.group], "label": s.label,
            "doc": s.doc, "evidence": s.evidence, "by": s.by, "app": s.app, "tool": s.tool, "heavy": s.heavy,
            "needs": list(s.needs), "inputs": list(s.inputs), "head": ctx.p["head"], "headline": "", "rev": None}


def _from_result(e: dict, res: dict, head: int) -> dict:
    e.update({"headline": res.get("headline") or "", "evidence": res.get("evidence") or e["evidence"],
              "detail": res.get("detail") or "", "files": res.get("files") or [], "rev": res.get("rev"),
              "ran": res.get("ts"), "seconds": res.get("seconds")})
    if res.get("rev") is not None and res["rev"] != head:
        e["note"] = (f"Computed for r{res['rev']:02d}, whose inputs are the same as r{head:02d}'s.")
    return e


def entry(ctx, s: Study, full: bool = False) -> dict:
    e = _base(ctx, s)
    ok, why = _applies(ctx, s)
    if not ok:
        return {**e, "state": "n/a", "why": why}
    try:
        if s.state_fn:
            e.update(s.state_fn(ctx))
        elif s.node:
            e.update(_node_state(ctx, s))
        elif s.live:
            e.update(_live_state(ctx, s))
        else:
            e.update(_store_state(ctx, s, full))
    except Exception as ex:                              # noqa: BLE001 - one entry that cannot be read is said, not hidden
        from .studio import StudioError
        msg = ex.public() if isinstance(ex, StudioError) else {"message": f"{type(ex).__name__}: {ex}"}
        e.update({"state": "failed", "error": msg})
    if e.get("state") in ("never", "stale") or (e.get("state") == "failed" and s.by == "engine"):
        need = _ready(ctx, s)
        if need:
            e["state_before"], e["state"], e["why"] = e["state"], "unavailable", need
    if not full:
        e.pop("data", None)
    return e


def _node_state(ctx, s: Study) -> dict:
    n = ctx.status[s.node]
    out = {"key": n["key"]}
    st = n["state"]
    if st == "off":
        return {**out, "state": "n/a", "why": "Not sliced: this design is set to Design only."}
    if st == "current":
        data = ctx.current(s.node)
        out.update({"state": "current", "rev": (data or {}).get("rev", ctx.p["head"]), "ran": n.get("made")})
        if s.headline and data is not None:
            h = s.headline(ctx, data)
            out.update(h if isinstance(h, dict) else {"headline": h})
        if out.get("rev") is not None and out["rev"] != ctx.p["head"]:
            out["note"] = f"Computed for r{out['rev']:02d}, whose inputs are the same as r{ctx.p['head']:02d}'s."
        return out
    if st == "failed":
        return {**out, "state": "failed", "error": n.get("error")}
    if st == "stale":
        return {**out, "state": "stale", "rev": n.get("last_rev")}
    if n.get("unavailable"):
        return {**out, "state": "unavailable", "why": n["unavailable"]}
    return {**out, "state": "never"}


def _live_state(ctx, s: Study) -> dict:
    res = s.run(ctx)
    return {"state": "current", "key": _key(ctx, s), "rev": ctx.p["head"], **res, "live": True}


def _store_state(ctx, s: Study, full: bool) -> dict:
    key = _key(ctx, s)
    d = _dir(ctx.st, ctx.p, s.id)
    out = {"key": key}
    run = _running(ctx.st, ctx.p, s.id, key)
    if run:
        return {**out, "state": "running", "job": run.get("job"), "since": run.get("ts")}
    res = _read(d / f"{key}.json")
    if res is None and s.probe:
        try:
            made = s.probe(ctx)
        except Exception:                                # noqa: BLE001
            made = None
        if made:
            res = {"rev": ctx.p["head"], "found": "cache", **made}
    if res is not None:
        out = _from_result({**out, "state": "current"}, res, ctx.p["head"])
        if full:
            out["data"] = res.get("data")
        return out
    fail = _read(d / f"{key}.failed.json")
    if fail:
        return {**out, "state": "failed", "error": fail.get("error"), "rev": fail.get("rev")}
    ok = [x for x in log(ctx.st, ctx.p, s.id) if x.get("ok")]
    if ok:
        last = ok[-1]
        prev = _read(d / f"{last['key']}.json") or {}
        return {**out, "state": "stale", "rev": last["rev"], "headline": prev.get("headline") or "",
                "stale_key": last["key"]}
    return {**out, "state": "never"}


# ---- listings -------------------------------------------------------------------------------------------------
def listing(st, p: dict, group: str | None = None, include_na: bool = True) -> dict:
    ctx = Ctx(st, p)
    rows = [entry(ctx, s) for s in registry() if group in (None, s.group)]
    if not include_na:
        rows = [r for r in rows if r["state"] != "n/a"]
    counts = {k: sum(1 for r in rows if r["state"] == k) for k in STATES}
    return {"project": p["id"], "head": p["head"], "groups": [{"id": g, "label": GROUPS[g], "stage": STAGE[g]} for g in GROUPS],
            "entries": rows, "counts": counts,
            "rule": "An entry is current only when a result exists under the key of the head revision's inputs; "
                    "a stale entry names the revision it describes. Nothing here is marked current by hand."}


def show(st, p: dict, sid: str) -> dict:
    s = get(sid)
    ctx = Ctx(st, p)
    e = entry(ctx, s, full=True)
    if not s.node and not s.state_fn and not s.live:
        e["log"] = log(st, p, sid)[-12:]
    return e


# ---- running --------------------------------------------------------------------------------------------------
def start(st, pid: str, sid: str, force: bool = False, wait: bool = False, **opts) -> dict:
    """Run one entry for the head revision. Returns {"job": id} (the app tracks it on the activity bar) or, with
    wait, the entry after the run. An agent-run entry returns the tool to call; a person's entry never runs here."""
    s = get(sid)
    p = st.load(pid)
    ctx = Ctx(st, p)
    ok, why = _applies(ctx, s)
    if not ok:
        raise _err(f"{s.label} does not apply to this design.", why)
    if s.by == "agent":
        return {"id": s.id, "by": "agent", "state": entry(ctx, s)["state"], "tool": s.tool,
                "next": f"{s.tool}(project='{pid}')" if s.tool else "",
                "why": "This one needs the agent to look at the design and say what it sees; Form Studio does not "
                       "record it on its own."}
    if s.by == "person":
        return {"id": s.id, "by": "person", "state": entry(ctx, s)["state"], "tool": s.tool,
                "why": "Only a person does this, in Form Studio's Make stage. Nothing was approved."}
    need = _ready(ctx, s)
    if need:
        raise _err(f"{s.label} cannot run yet.", need)
    if s.node:
        from .studio import NODES
        nodes = NODES[:NODES.index(s.node) + 1]
        if wait:
            job = st.run_sync(pid, nodes, force)
            return {"job": job, "entry": entry(Ctx(st, st.load(pid)), s)}
        return {"job": st.run(pid, nodes, force)}
    if s.live:
        return {"entry": entry(ctx, s, full=True)}
    key = _key(ctx, s)
    if not force:
        e = entry(ctx, s)
        if e["state"] == "current":
            return {"entry": e, "cached": True}
        if e["state"] == "running":
            return {"job": e.get("job"), "running": True}
    job = {"id": uuid.uuid4().hex[:10], "project": pid, "state": "running", "started": time.time(), "kind": "study",
           "study": s.id, "steps": [{"node": "study:" + s.id, "label": s.label, "state": "running"}]}
    st.jobs[job["id"]] = job
    _write(_marker(st, p, s.id, key), {"job": job["id"], "pid": os.getpid(), "ts": time.time()})
    if wait:
        _execute(st, p, s, key, job, opts)
        return {"job": job, "entry": entry(Ctx(st, st.load(pid)), s, full=True)}
    threading.Thread(target=_execute, args=(st, p, s, key, job, opts), daemon=True).start()
    return {"job": job["id"]}


def _execute(st, p, s: Study, key: str, job: dict, opts: dict) -> None:
    from .studio import StudioError
    step = job["steps"][0]
    t0 = time.perf_counter()
    rev = p["head"]
    try:
        ctx = Ctx(st, p)
        ctx.opts = opts
        res = s.run(ctx) or {}
        res.setdefault("evidence", s.evidence)
        _record(st, p, s.id, key, rev, True, res, seconds=round(time.perf_counter() - t0, 2))
        step["state"], job["state"] = "done", "done"
    except StudioError as e:
        step["state"], step["error"] = "failed", e.public()
        job["state"], job["error"] = "failed", e.public()
        _record(st, p, s.id, key, rev, False, error=e.public())
    except Exception as e:                               # noqa: BLE001 - recorded, never lost
        err = {"message": f"Unexpected {type(e).__name__}: {e}", "hint": "The project is unchanged. Run it again; "
               "if it repeats, export the project and report it."}
        step["state"], step["error"] = "failed", err
        job["state"], job["error"] = "failed", err
        _record(st, p, s.id, key, rev, False, error=err)
    finally:
        step["seconds"] = round(time.perf_counter() - t0, 3)
        job["finished"] = time.time()
        _marker(st, p, s.id, key).unlink(missing_ok=True)
        try:
            st.jobs.save(job)
        except Exception:                                # noqa: BLE001
            pass


# ---- headlines ------------------------------------------------------------------------------------------------
def _dur(s) -> str:
    if s is None:
        return ""
    s = int(round(float(s)))
    h, m = divmod(s // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min" if m else f"{s} s"


def _rollup(rows: list) -> str:
    n = {k: sum(1 for c in rows if c["status"] == k) for k in ("PASS", "WARN", "FAIL")}
    bits = [f"{n['PASS']} pass"] + ([f"{n['WARN']} warn"] if n["WARN"] else []) + ([f"{n['FAIL']} fail"] if n["FAIL"] else [])
    return " · ".join(bits)


def _classes(rows: list) -> str:
    seen = []
    for c in rows:
        ev = c.get("evidence")
        if ev and ev not in seen:
            seen.append(ev)
    return ", ".join(seen)


def _checks_head(ctx, d):
    rows = d.get("checks") or []
    return {"headline": _rollup(rows), "evidence": _classes(rows) or "computed"}


def _asm_head(ctx, d):
    rows = [c for c in d.get("checks") or [] if str(c.get("id", "")).startswith("asm_")]
    if not rows:
        return {"headline": "no assembly rows in these checks"}
    first = next((c for c in rows if c["status"] != "PASS"), None)
    return {"headline": _rollup(rows), "evidence": _classes(rows) or "computed",
            "detail": f"{first['label']}: {first['value']}" if first else ""}


def _slice_head(ctx, d):
    t, g = d.get("time_s"), d.get("filament_g")
    bits = [x for x in (_dur(t), f"{g:.1f} g" if g is not None else "") if x]
    plates = d.get("plate_count") or 1
    return {"headline": " · ".join(bits) + (f" · {plates} plates" if plates > 1 else ""), "evidence": "simulated",
            "detail": f"{d.get('slicer_name', 'Slicer')} {d.get('slicer_version', '')}".strip()}


def _exports_head(ctx, d):
    files = d.get("files") or {}
    kb = sum(f.get("bytes", 0) for f in files.values()) / 1024
    return {"headline": f"{len(files)} files · " + (f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} kB"),
            "evidence": "computed", "files": [f["name"] for f in files.values()]}


# ---- runners (each one the code that does the work elsewhere in the app, MCP and CLI) -------------------------
def _map_study(name: str):
    from . import analysis

    def run(ctx):
        r = analysis.run_map(ctx.st, ctx.p, name)
        return _map_result(name, r)

    def probe(ctx):
        r = analysis.cached_map(ctx.st, ctx.p, name)
        return _map_result(name, r) if r else None

    def key(ctx):
        return analysis.map_key(ctx.st, ctx.p, name)
    return run, probe, key


def _map_result(name: str, r: dict) -> dict:
    s = r.get("stats") or {}
    if name == "thickness":
        head = f"{s['min_mm']:.2f} mm thinnest" if s.get("min_mm") is not None else "no opposing walls found"
        if s.get("under_two_perimeters_pct"):
            head += f" · {s['under_two_perimeters_pct']:g} % under two perimeters"
    elif name == "overhang":
        head = f"{s.get('overhang_mm2', 0):.0f} mm² overhang · {s.get('support_mm3', 0):.0f} mm³ support"
    elif name == "section":
        nk = s.get("neck") or {}
        head = f"neck {nk['area_mm2']:.0f} mm² at {nk['z_mm']:.1f} mm" if nk.get("area_mm2") is not None else f"{s.get('levels', 0)} levels"
    else:
        head = f"{s.get('thin_markers', 0)} thin · {s.get('gap_markers', 0)} gaps · {s.get('small_holes', 0)} small holes"
    return {"headline": head, "evidence": "computed", "detail": (r.get("legend") or {}).get("not", ""),
            "data": {"stats": s, "rev": r.get("rev")}}


def _orient_run(ctx):
    from . import analysis
    r = analysis.orientations(ctx.st, ctx.p)
    return _orient_result(r)


def _orient_result(r):
    c = (r.get("candidates") or [None])[0]
    if not c:
        return {"headline": "no candidates", "evidence": "computed"}
    cur = next((x for x in r["candidates"] if x.get("current")), None)
    head = f"best: {c['label']}" + ("" if c.get("current") else f" · now: {cur['label']}" if cur else "")
    return {"headline": head, "evidence": "computed", "detail": r.get("formula", ""),
            "data": {"best": c.get("id"), "candidates": len(r["candidates"])}}


def _orient_probe(ctx):
    from . import analysis
    path = ctx.st.dir(ctx.p["id"]) / "artifacts" / "analysis" / f"orient-{analysis.orient_key(ctx.st, ctx.p)}.json"
    r = _read(path)
    return _orient_result(r) if r else None


def _orient_key(ctx):
    from . import analysis
    return analysis.orient_key(ctx.st, ctx.p)


def _proof_state(ctx) -> dict:
    from . import contract
    sheet = contract.prove(ctx.st, ctx.p, compute=False)
    key = ctx.keys["geometry"]
    if not sheet:
        return {"state": "never", "key": key}
    return {"state": "current", "key": key, "rev": ctx.p["head"], "headline": contract.summary(sheet),
            "evidence": "computed (B-rep)"}


def _proof_run(ctx):
    from . import contract
    sheet = contract.prove(ctx.st, ctx.p, compute=True)
    if not sheet:
        raise _err("This design has no requirements to prove.", "design_brief states them.")
    return {"headline": contract.summary(sheet), "evidence": "computed (B-rep)",
            "data": {"green": sheet.get("green"), "rows": contract.table(sheet)}}


def _fit_live(ctx):
    f = ctx.st.fit(ctx.p)
    if not f:
        return {"headline": "no fit declared", "evidence": "modelled"}
    return {"headline": f"{round(f['yield'] * 100)} % within the window", "evidence": "modelled",
            "detail": "A statistical model of the printer's bias and spread, not a measurement.",
            "data": {"yield": f["yield"], "window": f.get("window")}}


def _sim_run(ctx):
    from . import toolpath
    tp = toolpath.for_project(ctx.st, ctx.p)
    s = tp.summary()
    return {"headline": f"{s['layers']} layers · {len(s['bridge_layers'])} with bridges · {len(s['overhang_layers'])} with overhang walls",
            "evidence": "simulated", "detail": s["note"],
            "data": {"layers": s["layers"], "bridge_layers": len(s["bridge_layers"]), "overhang_layers": len(s["overhang_layers"]),
                     "total_time_s": s["total_time_s"], "time_source": s["time_source"]}}


def _sim_key(ctx):
    return H(ctx.keys["slice"])


def _cmp_result(r):
    rows = r.get("rows") or []
    ok = [x for x in rows if x.get("status") == "ok"]
    fast = next((x for x in rows if x.get("id") == (r.get("best") or {}).get("fastest")), None)
    head = f"{len(ok)} of {len(rows)} sliced" + (f" · fastest {fast.get('label') or fast.get('printer') or fast['id']} {_dur(fast['time_s'])}" if fast else "")
    return {"headline": head, "evidence": "simulated", "detail": r.get("note", ""), "data": {"best": r.get("best"), "rows": len(rows)}}


def _cmp_run(ctx):
    from . import slicecompare
    return _cmp_result(slicecompare.compare(ctx.st, ctx.p))


def _cmp_probe(ctx):
    from . import slicecompare
    r = slicecompare.cached(ctx.st, ctx.p)
    return _cmp_result(r) if r else None


def _cmp_key(ctx):
    return ctx.keys["exports"]


def _cost_live(ctx):
    from . import cost
    out = cost.project(ctx.st, ctx.p, 1)
    part = out.get("per_plate_as_sliced") or {}
    cur = out.get("currency") or ""
    if part.get("cost") is None:
        return {"headline": "needs your prices", "evidence": "simulated × specified",
                "detail": (out.get("filament") or {}).get("needs") or "Set a filament price in Cost."}
    return {"headline": f"{part['cost']:.2f} {cur}".strip() + " per print" + (f" · not counted: {', '.join(part['not_counted'])}" if part.get("not_counted") else ""),
            "evidence": "simulated × specified", "detail": out.get("note", "")}


def _lighter_result(r):
    c = (r.get("candidates") or [None])[0]
    if not c:
        return {"headline": "no lighter candidate keeps every check", "evidence": "computed, simulated"}
    g = c.get("saves_slice_g") if c.get("saves_slice_g") is not None else c.get("saves_mass_g")
    return {"headline": (f"saves {g:.1f} g" if g is not None else "a candidate") + f" · {len(r['candidates'])} candidates",
            "evidence": "computed, simulated", "detail": r.get("note", "")}


def _lighter_run(ctx):
    from . import lighten
    return _lighter_result(lighten.search(ctx.st, ctx.p))


def _lighter_probe(ctx):
    from . import lighten
    r = lighten.cached(ctx.st, ctx.p)
    return _lighter_result(r) if r else None


def _lighter_key(ctx):
    return H(ctx.keys["checks"], ctx.keys["slice"])


def _critique_state(ctx) -> dict:
    d = (ctx.p.get("design") or {}).get("critiques") or []
    key = ctx.keys["geometry"]
    mine = [c for c in d if c.get("rev") == ctx.p["head"]]
    if mine:
        return {"state": "current", "key": key, "rev": ctx.p["head"], "headline": f"{len(mine)} pass{'es' if len(mine) > 1 else ''} recorded",
                "evidence": "heuristic", "ran": mine[-1].get("ts")}
    if d:
        return {"state": "stale", "key": key, "rev": max(int(c.get("rev") or 0) for c in d)}
    return {"state": "never", "key": key}


def _release_state(ctx) -> dict:
    a = ctx.st.approval_state(ctx.p, ctx.status)
    g = ctx.st.gate(ctx.p, ctx.status)
    key = H({n: ctx.status[n]["key"] for n in ctx.status})
    gate = ("ready to approve" if g["ready"] else f"{len(g['reasons'])} reason{'s' if len(g['reasons']) != 1 else ''} it cannot be released") \
        + (f" · {len(g['warnings'])} warnings to acknowledge" if g.get("warnings") else "")
    if a["state"] == "approved":
        return {"state": "current", "key": key, "rev": a["rev"], "headline": f"approved · {a['release']}",
                "evidence": "a person's approval", "detail": g["evidence_level"]}
    if a["state"] == "superseded":
        return {"state": "stale", "key": key, "rev": a["rev"], "headline": gate, "evidence": "",
                "detail": "Changed since the release: " + ", ".join(a.get("changed") or []) + ". " + g["evidence_level"]}
    return {"state": "never", "key": key, "headline": gate, "evidence": "",
            "detail": "; ".join(g["reasons"][:3]) or g["evidence_level"]}


def _docs(name: str):
    def run(ctx):
        from . import maker_docs
        f = maker_docs.working(ctx.st, ctx.p, name)
        return {"headline": f"{name} · {f.stat().st_size / 1024:.1f} kB", "evidence": "computed", "files": [str(f)]}

    def probe(ctx):
        from . import maker_docs
        files = maker_docs.cached(ctx.st, ctx.p, ctx.keys, ctx.status)
        if not files or name not in files:
            return None
        from .maker_docs import docs_key
        f = ctx.st.dir(ctx.p["id"]) / "artifacts" / "docs" / docs_key(ctx.keys, ctx.status) / name
        return {"headline": f"{name} · {f.stat().st_size / 1024:.1f} kB", "evidence": "computed", "files": [str(f)]} if f.is_file() else None

    def key(ctx):
        from .maker_docs import docs_key
        return docs_key(ctx.keys, ctx.status)
    return run, probe, key


def _instr_run(ctx):
    from . import instructions
    out = instructions.build(ctx.st, ctx.p)
    return _instr_result(out)


def _instr_result(out):
    return {"headline": f"{len(out.get('pages') or [])} pages · {len(out.get('steps') or [])} steps", "evidence": "computed",
            "files": [out["pdf_path"]] if out.get("pdf_path") else []}


def _instr_probe(ctx):
    from . import instructions
    out = instructions.cached(ctx.st, ctx.p)
    return _instr_result(out) if out else None


def _sheet_file(ctx) -> Path:
    from . import render as rendering
    return ctx.st.dir(ctx.p["id"]) / "artifacts" / "renders" / f"{ctx.keys['geometry']}-sheet-all-v{rendering.VERSION}.png"


def _sheet_run(ctx):
    """The four-view sheet, the same file MCP render(view="sheet") writes and reuses."""
    from . import render as rendering
    f = _sheet_file(ctx)
    if not f.exists():
        p = ctx.p
        feats = [{"id": x.id, "label": x.label} for x in ctx.recipe.features]
        v = ctx.st.view(p)
        title = f"{p['name']} - r{p['head']:02d}"
        pngs = [rendering.render_png(v, feats, vw, None, size=(640, 460), title=title) for vw in ("iso", "front", "top", "right")]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(rendering.contact_sheet(pngs))
    return {"headline": "four views · iso, front, top, right", "evidence": "computed", "files": [str(f)]}


def _sheet_probe(ctx):
    f = _sheet_file(ctx)
    return {"headline": "four views · iso, front, top, right", "evidence": "computed", "files": [str(f)]} if f.is_file() else None


def _photo_state(ctx) -> dict:
    from . import photo
    rs = photo.renders(ctx.st, ctx.p)
    key = ctx.keys["exports"]
    cur = [m for m in rs if m.get("current")]
    if cur:
        m = cur[0]
        return {"state": "current", "key": key, "rev": m.get("rev", ctx.p["head"]), "headline": f"{len(cur)} render{'s' if len(cur) > 1 else ''} · {m.get('preset', '')}".strip(" ·"),
                "evidence": "illustration (Blender)", "ran": m.get("ts")}
    if rs:
        return {"state": "stale", "key": key, "rev": rs[0].get("rev"), "evidence": "illustration (Blender)"}
    return {"state": "never", "key": key}


def _photo_run(ctx):
    from . import photo
    m = photo.render(ctx.st, ctx.p)
    return {"headline": f"render · {m.get('preset', 'studio')}", "evidence": "illustration (Blender)",
            "files": [str(photo.file(ctx.st, ctx.p, m["key"]))] if m.get("key") else []}


def _turntable_run(ctx):
    from . import animate
    info = animate.export(ctx.st, ctx.p, "webp")
    return {"headline": f"{info['frames']} frames · {info['seconds']} s · {info['bytes'] // 1024} kB", "evidence": "computed",
            "files": [info["file"]]}


def _share_run(ctx):
    from . import share
    r = share.card(ctx.st, ctx.p)
    return {"headline": f"{r['size'][0]} × {r['size'][1]} · {r['bytes'] // 1024} kB", "evidence": "computed", "files": [r["file"]]}


def _freecad_run(ctx):
    name, text = ctx.st.freecad_macro(ctx.p)
    f = _dir(ctx.st, ctx.p, "freecad") / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return {"headline": f"{name}", "evidence": "computed", "files": [str(f)],
            "detail": "A macro that rebuilds this revision in FreeCAD from its STEP file."}


def _threemf_run(ctx):
    from . import materials
    data = materials.threemf(ctx.st, ctx.p)
    f = _dir(ctx.st, ctx.p, "threemf") / f"{ctx.p['id']}_r{ctx.p['head']:02d}_colour.3mf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return {"headline": f"3MF with colours · {len(data) // 1024} kB", "evidence": "computed", "files": [str(f)]}


def _threemf_key(ctx):
    from . import materials
    return H(ctx.keys["exports"], materials.appearance(ctx.p))


def _slicer_open_run(ctx):
    from . import slicer_open
    out = slicer_open.run(ctx.st, ctx.p, None, open_app=bool(getattr(ctx, "opts", {}).get("open")))
    files = [str(x) for x in (out.get("project_file"), out.get("file"), out.get("path")) if x]
    return {"headline": f"{out.get('slicer', 'slicer')} project" + (f" · {out['printer']}" if isinstance(out.get("printer"), str) else ""),
            "evidence": "simulated", "files": files[:1]}


def _slicer_open_key(ctx):
    from . import slicer_open
    return H(ctx.keys["exports"], ctx.keys["slice"], slicer_open.VERSION)


def _bundle_run(ctx):
    from . import bundle
    out = bundle.export_project(ctx.st, ctx.p["id"])
    return {"headline": f"{out.name} · {out.stat().st_size / 1048576:.1f} MB", "evidence": "computed", "files": [str(out)]}


def _bundle_key(ctx):
    return H(ctx.p["head"], ctx.p.get("updated"))


def _game_run(ctx):
    from .game import game_asset
    r = game_asset(ctx.st, ctx.p["id"], "build")
    return {"headline": "built" + (f" · {r['lods']} LODs" if isinstance(r.get("lods"), int) else ""), "evidence": "computed",
            "files": [str(r["dir"])] if r.get("dir") else []}


def _builtin() -> None:
    reg = register
    # Studies (Review)
    reg(Study("checks", "study", "Checks", "Validity, size, thickness, print and fit checks of the head revision.",
              "computed, heuristic", node="checks", headline=_checks_head, inputs=("geometry", "exports", "printer", "material"),
              app="checks", tool="run_pipeline", order=10))
    reg(Study("assembly", "study", "Assembly and joints", "Overlaps, gaps, declared fits, tool reach and every joint "
              "swept through its range.", "computed", node="checks", headline=_asm_head, needs=("assembly",),
              inputs=("geometry", "assembly budget"), app="checks", tool="run_pipeline", order=12))
    reg(Study("proof", "study", "Requirements", "The brief's requirements measured on the solid: the proof sheet.",
              "computed (B-rep)", run=_proof_run, state_fn=_proof_state, needs=("contract",), inputs=("geometry", "contract"),
              app="proof", tool="get_project", order=14))
    for i, (m, label, doc, needs) in enumerate((
            ("thickness", "Wall thickness", "Opposing-wall distance by ray, coloured on the part.", ()),
            ("overhang", "Overhangs", "Angle past vertical in the print orientation; contact and bridges apart.", ("print",)),
            ("section", "Layer cross-section", "Area of each layer's slice by height and the weakest neck (not a strength study).", ("print",)),
            ("features", "Small features", "Walls, gaps and holes too small for the nozzle.", ("print",)))):
        run, probe, key = _map_study(m)
        reg(Study("map." + m, "study", label, doc, "computed", run=run, probe=probe, key=key, needs=needs,
                  inputs=("geometry", "nozzle") + (("orientation",) if m in ("overhang", "section") else ()),
                  app="map." + m, tool="analyze", order=20 + i))
    reg(Study("fit", "study", "Fit under uncertainty", "The share of prints whose fit lands in the window, from the "
              "printer's bias and spread.", "modelled", run=_fit_live, live=True, needs=("fit",),
              inputs=("values", "provenance", "calibration"), app="fit", order=30))
    reg(Study("critique", "study", "Design critique", "Close-ups, metrics and a checklist the agent answers by looking.",
              "heuristic", state_fn=_critique_state, by="agent", tool="critique", app="review", order=32))
    reg(Study("slice", "study", "Slice", "The slicer's own slice: time, filament, plates.", "simulated", node="slice",
              headline=_slice_head, needs=("print",), inputs=("exports", "slicer presets", "slicer version"),
              app="slice", tool="run_pipeline", order=40))
    reg(Study("simulation", "study", "Print simulation", "The sliced toolpaths layer by layer, with bridges and overhang walls.",
              "simulated", run=_sim_run, key=_sim_key, needs=("print", "slice"), inputs=("slice",),
              app="simulate", tool="print_simulation", order=42))
    reg(Study("orientation", "study", "Print orientations", "Every way the part can lie on the plate, ranked by a stated score.",
              "computed", run=_orient_run, probe=_orient_probe, key=_orient_key, needs=("print",),
              inputs=("geometry", "printer bed"), app="orient", tool="suggest_orientation", order=44))
    reg(Study("printers", "study", "Every printer", "The model sliced for real on every printer set up in every slicer.",
              "simulated", run=_cmp_run, probe=_cmp_probe, key=_cmp_key, needs=("print", "exports", "slicer"),
              inputs=("exports", "printers"), app="printers", tool="compare_printers", heavy=True, order=46))
    reg(Study("cost", "study", "Cost", "Filament, electricity and machine time of the current slice, at your prices.",
              "simulated × specified", run=_cost_live, live=True, needs=("print", "slice"), inputs=("slice", "your prices"),
              app="cost", tool="estimate_cost", order=48))
    reg(Study("lighter", "study", "Make it lighter", "Thinner walls, pockets and less infill that keep every passing check.",
              "computed, simulated", run=_lighter_run, probe=_lighter_probe, key=_lighter_key, needs=("print",),
              inputs=("checks", "slice"), app="lighter", tool="make_lighter", heavy=True, order=50))
    # Routes (Make)
    reg(Study("exports", "route", "STEP, STL, OBJ, GLB", "The solid exported for other CAD programs, renderers and slicers.",
              "computed", node="exports", headline=_exports_head, inputs=("geometry", "orientation"), app="files",
              tool="run_pipeline", order=10))
    reg(Study("threemf", "route", "3MF with colours", "One object per body with its colour and material name.",
              "computed", run=_threemf_run, key=_threemf_key, needs=("exports",), inputs=("exports", "appearance"),
              tool="set_appearance", order=12))
    reg(Study("slicer_project", "route", "Slicer project", "Sliced with settings chosen for this part; opens in your slicer "
              "from the window.", "simulated", run=_slicer_open_run, key=_slicer_open_key, needs=("print", "exports", "slicer"),
              inputs=("exports", "slice", "printer"), app="slicerOpen", tool="open_in_slicer", order=14))
    reg(Study("freecad", "route", "FreeCAD macro", "A macro that rebuilds this revision in FreeCAD from its STEP.",
              "computed", run=_freecad_run, key=lambda c: c.keys["exports"], needs=("step", "exports"),
              inputs=("exports", "values"), tool="freecad_macro", order=16))
    reg(Study("project_file", "route", "Project archive", "The whole design, its revisions and conversations in one .formstudio file.",
              "computed", run=_bundle_run, key=_bundle_key, inputs=("every revision", "conversations"),
              app="exportProject", tool="export_project", order=18))
    reg(Study("game", "route", "Game asset", "LODs, UVs, baked maps and collision for Godot, Unity or Unreal.",
              "computed", run=_game_run, needs=("game",), app="game", tool="game_asset", heavy=True, order=20))
    reg(Study("release", "route", "Release", "The gate, then a person's approval: the files frozen with SHA-256 hashes.",
              "computed", state_fn=_release_state, by="person", app="release", tool="request_release", order=30))
    # Documents (Make)
    for i, (name, label, doc, needs) in enumerate((
            ("BOM.csv", "Parts list", "Printed parts and bought hardware, each with its evidence.", ()),
            ("ASSEMBLY.md", "Assembly notes", "How the parts go together, in order, with pictures.", ("assembly",)),
            ("MOTION_CHECKS.csv", "Motion checks", "Every joint's range and first contact, as computed.", ("joints",)),
            ("PRINT_REPORT.md", "Print report", "What was checked and sliced, and what was not.", ("print",)),
            ("MEASUREMENT_PLAN.md", "Measurement plan", "What to measure on the made part, and how.", ()))):
        run, probe, key = _docs(name)
        reg(Study("doc." + name.split(".")[0].lower(), "document", label, doc, "computed", run=run, probe=probe, key=key,
                  needs=needs, inputs=("every key of the revision",), app="docs", order=10 + i))
    reg(Study("instructions", "document", "Assembly instructions", "A PDF: a parts page, then one page per part going on.",
              "computed", run=_instr_run, probe=_instr_probe, needs=("assembly",), app="instructions",
              tool="assembly_instructions", order=20))
    reg(Study("views", "document", "Four-view sheet", "Iso, front, top and right, rendered from the kernel's geometry.",
              "computed", run=_sheet_run, probe=_sheet_probe, tool="render", order=22))
    reg(Study("photo", "document", "Photoreal render", "An illustration in Blender with the design's materials.",
              "illustration (Blender)", run=_photo_run, state_fn=_photo_state, needs=("blender",), inputs=("exports", "appearance"),
              app="render", tool="render_photo", heavy=True, order=24))
    reg(Study("turntable", "document", "Turntable", "The part turning, rendered from the real mesh.", "computed",
              run=_turntable_run, app="turntable", tool="turntable", order=26))
    reg(Study("share", "document", "Share card", "A 1600 × 900 picture of this design with its evidence labels.",
              "computed", run=_share_run, app="share", tool="share_card", order=28))


# ---- command line: form study list|run|show <project> [id] ----------------------------------------------------
def main_cli(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="form study", description="The Bench: every study, route and document of a design, "
                                 "with its state. Prints JSON.")
    ap.add_argument("action", choices=("list", "run", "show"))
    ap.add_argument("project")
    ap.add_argument("id", nargs="?")
    ap.add_argument("--group", choices=tuple(GROUPS))
    ap.add_argument("--force", action="store_true", help="run again even when current")
    ap.add_argument("--open", action="store_true", help="slicer_project: open the result in the slicer app")
    a = ap.parse_args(argv)
    from . import config
    from .studio import Studio, StudioError
    st = Studio(config.load())
    try:
        p = st.load(a.project)
        if a.action == "list":
            out = listing(st, p, a.group)
        elif not a.id:
            raise StudioError("Name the entry: form study %s <project> <id>." % a.action, "form study list <project> names them.")
        elif a.action == "show":
            out = show(st, p, a.id)
        else:
            r = start(st, a.project, a.id, force=a.force, wait=True, open=a.open)
            job = r.get("job")
            out = {**(r.get("entry") or {}), **({k: v for k, v in r.items() if k not in ("entry", "job")})}
            if isinstance(job, dict):
                from .digest import job_digest
                out["job"] = job_digest(job)
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
        return 1 if out.get("state") == "failed" else 0
    except StudioError as e:
        print(json.dumps({"error": e.public()}, indent=1, ensure_ascii=False))
        return 2
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                                # noqa: BLE001
            pass


# ---- MCP: list_studies, run_study, get_study ------------------------------------------------------------------
def register_mcp(mcp, get_studio, run) -> None:
    """Add the Bench's three tools to an MCP server (form/mcp_server.py calls this, as it does game.register)."""
    import anyio
    from mcp.types import ToolAnnotations
    ro = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    rw = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    async def list_studies(project: str, group: str | None = None) -> dict:
        """List every study, route and document of a design with its state: the Bench. group: study (Review), route
        or document (Make). Each entry: id, label, state (never, current, stale, failed, running, unavailable, n/a),
        rev (the revision its result describes; a stale entry names the revision its newest result was computed for),
        headline with evidence, needs, inputs, and by whom it runs (engine; agent: call `tool` yourself; person: only
        they do it, in Form Studio). Reads only; nothing is run."""
        st = get_studio()
        if group is not None and group not in GROUPS:
            raise _err(f"group is one of {', '.join(GROUPS)}.")
        return await run(lambda: listing(st, st.load(project), group))

    async def run_study(project: str, id: str, force: bool = False, wait_s: float = 60) -> dict:
        """Run one Bench entry for the head revision (ids from list_studies). A current entry comes back as it is
        unless force=True. Waits up to wait_s, then returns a job to poll with get_job. An entry the agent must do
        (critique) returns the tool to call; one only a person does (release) is never done here."""
        st = get_studio()
        r = await run(lambda: start(st, project, id, force=force))
        jid = r.get("job")
        if isinstance(jid, str) and jid in st.jobs:
            t0 = time.time()
            while time.time() - t0 < max(0.0, min(float(wait_s), 300)) and st.jobs[jid]["state"] == "running":
                await anyio.sleep(0.25)
            from .digest import job_digest
            job = st.jobs[jid]
            out = {"job": job_digest(job)}
            if job["state"] == "running":
                return out | {"next": f"get_job(project='{project}', job='{jid}'), then get_study"}
            return out | {"entry": await run(lambda: show(st, st.load(project), id))}
        return r

    async def get_study(project: str, id: str) -> dict:
        """Read one Bench entry: its state, the revision it describes, its headline with evidence, its files and
        stored numbers, and the log of its runs. Reads only."""
        st = get_studio()
        return await run(lambda: show(st, st.load(project), id))

    for fn, ann in ((list_studies, ro), (run_study, rw), (get_study, ro)):
        mcp.tool(name=fn.__name__, annotations=ann)(fn)
