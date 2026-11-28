"""Strength studies of a design: defined once, run in the background, stored beside the revision.

A study is a definition kept in the project file (project.json → "strength"): its kind (static, modal, buckling), the
material, the supports and the loads, each on faces picked as points on the part (the same points analyze_selection
takes: design millimetres, each part as printed).

    d = define(st, p, {"kind": "static", "material": "AL-6061",
                       "fixtures": [{"type": "fixed", "faces": [[0, 10, 5]]}],
                       "loads": [{"type": "force", "faces": [[80, 10, 5]], "vector": [0, 0, -200]}]})
    job = start(st, p["id"], d["id"])            # a job in Studio.jobs: progress, cancel (get_job, cancel_job)
    r = result(st, p, d["id"])                   # the stored result, its state and how every number is known

**A result is an artifact with a key.** The key is made of the geometry key of the revision (the design's code, the
kernel, the values), the definition, the numbers of every material used and the engine with its library versions.
A result is current only when it exists under the key of the head revision; after any change to the geometry, the
material's sourced values, the loads or the engine, the stored result is stale and says which revision it describes.
Nothing here marks a result current by hand.

**Nothing is made up.** The solver runs in the FEA engine's own Python (form/fea/run.py). Without it a study cannot
run and says how to get it. A study that does not converge is stored as not converged, with why, and gives no safety
factor.

Supports: "fixed" (no movement), "roller" (free to slide in the face, no movement across it; a symmetry plane),
"pin" (a cylindrical face: free to turn about its axis, held across and along it), "hold" (no movement along the
directions given, free in the others). Loads: "force" (newtons, spread
evenly over the faces), "pressure" (MPa, pushing on the face), "preload" (a bolt's clamping force between two face
sets, a modelled connector), "gravity" (in g, with a direction). A modal study ignores loads; with no supports it is
a free body.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import ENGINE, HOW_TO_GET, KIND_LABEL, KINDS, python
from . import material as material_mod

KEY_VERSION = 1                 # bump when the engine's method changes a result (form/fea/core.py ENGINE_VERSION too)
FIXTURES = ("fixed", "roller", "pin", "hold")
LOADS = ("force", "pressure", "preload", "gravity")
MESH_OPTIONS = {"h0": (0.01, 1e4), "levels_max": (3, 10), "dof_max": (2e4, 4e6), "budget_s": (5, 3600),
                "tol_disp": (1e-4, 0.2), "tol_stress": (1e-3, 0.3), "tol_freq": (1e-4, 0.2), "tol_buckling": (1e-4, 0.2),
                "singular_radius": (0.01, 100.0)}
G0 = 9806.65                    # mm/s2
MAX_STUDIES = 40
TIMEOUT_S = 3600


def _err(msg: str, hint: str = "", status: int = 400, **kw):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status, **kw)


def H(*a) -> str:
    from ..studio import H as _h
    return _h(*a)


# ---- definition ------------------------------------------------------------------------------------------------

def _vec(v, what: str) -> list:
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        raise _err(f"{what} is three numbers: x, y, z.") from None
    if len(out) != 3 or not all(math.isfinite(x) for x in out):
        raise _err(f"{what} is three numbers: x, y, z.")
    return out


def _faces(v, what: str) -> list:
    """Face references: a point [x, y, z], {"at": [x, y, z]}, or a list of them."""
    if isinstance(v, dict):
        v = [v]
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
        v = [v]
    if not isinstance(v, (list, tuple)) or not v:
        raise _err(f"{what} needs at least one face: a point on it, [x, y, z] in design millimetres.",
                   "analyze_selection with {\"kind\": \"face\", \"at\": [x, y, z]} shows the face a point lands on.")
    if len(v) > 60:
        raise _err(f"{what} names more than 60 faces.")
    return [{"at": _vec(f["at"] if isinstance(f, dict) else f, f"A face of {what}")} for f in v]


def clean(body: dict) -> dict:
    """Check and normalise a study definition. Raises StudioError with a sentence that says what is wrong."""
    if not isinstance(body, dict):
        raise _err("A study is an object: kind, material, fixtures, loads.")
    kind = str(body.get("kind") or "static").lower()
    if kind not in KINDS:
        raise _err(f"Unknown study kind “{kind}”.", "Kinds: static, modal, buckling.")
    out = {"kind": kind, "name": " ".join(str(body.get("name") or "").split())[:80]}
    fixtures = []
    for i, f in enumerate(body.get("fixtures") or []):
        t = str((f or {}).get("type") or "fixed").lower()
        if t not in FIXTURES:
            raise _err(f"Support {i + 1}: unknown type “{t}”.", "Types: fixed, roller, pin, hold.")
        item = {"type": t, "faces": _faces(f.get("faces") or f.get("at"), f"support {i + 1}")}
        if t == "hold":
            dirs = f.get("directions") or ([f["direction"]] if f.get("direction") else [])
            if dirs and isinstance(dirs[0], (int, float)):
                dirs = [dirs]
            if not 1 <= len(dirs) <= 3:
                raise _err(f"Support {i + 1} (hold) needs directions: one to three vectors the face may not move along, "
                           "e.g. [[0, 0, 1]].")
            item["directions"] = []
            for d in dirs:
                v = _vec(d, f"A direction of support {i + 1}")
                if not any(v):
                    raise _err(f"A direction of support {i + 1} is zero.")
                item["directions"].append(v)
        fixtures.append(item)
    loads = []
    for i, ld in enumerate(body.get("loads") or []):
        t = str((ld or {}).get("type") or "").lower()
        what = f"load {i + 1}"
        if t not in LOADS:
            raise _err(f"{what.capitalize()}: unknown type “{t}”.", "Types: force, pressure, preload, gravity.")
        if t == "force":
            if ld.get("vector") is not None:
                vec = _vec(ld["vector"], f"The vector of {what}")
            elif ld.get("magnitude") is not None and ld.get("direction") is not None:
                d = _vec(ld["direction"], f"The direction of {what}")
                n = math.sqrt(sum(x * x for x in d))
                if n == 0:
                    raise _err(f"The direction of {what} is zero.")
                vec = [float(ld["magnitude"]) * x / n for x in d]
            else:
                raise _err(f"{what.capitalize()} (a force) needs vector=[Fx, Fy, Fz] in newtons, or magnitude and direction.")
            loads.append({"type": t, "faces": _faces(ld.get("faces") or ld.get("at"), what), "vector": vec})
        elif t == "pressure":
            try:
                val = float(ld.get("value_MPa", ld.get("value")))
            except (TypeError, ValueError):
                raise _err(f"{what.capitalize()} (a pressure) needs value_MPa (1 MPa = 10 bar = 1 N/mm2).") from None
            loads.append({"type": t, "faces": _faces(ld.get("faces") or ld.get("at"), what), "value": val})
        elif t == "preload":
            try:
                force = float(ld.get("force_N", ld.get("force")))
            except (TypeError, ValueError):
                raise _err(f"{what.capitalize()} (a preload) needs force_N, the bolt's clamping force.") from None
            item = {"type": t, "faces": _faces(ld.get("faces"), f"{what} (under the head)"),
                    "faces_b": _faces(ld.get("faces_b"), f"{what} (under the nut, or the thread)"), "force": force}
            if ld.get("axis") is not None:
                item["axis"] = _vec(ld["axis"], f"The axis of {what}")
            loads.append(item)
        else:
            d = _vec(ld.get("direction") or [0, 0, -1], f"The direction of {what}")
            n = math.sqrt(sum(x * x for x in d))
            if n == 0:
                raise _err(f"The direction of {what} is zero.")
            g = float(ld.get("g", 1.0))
            loads.append({"type": t, "vector": [g * G0 * x / n for x in d], "g": g})
    if kind in ("static", "buckling"):
        if not fixtures:
            raise _err(f"A {KIND_LABEL[kind]} study needs at least one support.",
                       "fixtures=[{\"type\": \"fixed\", \"faces\": [[x, y, z]]}]: a point on the face that is held.")
        if not loads:
            raise _err(f"A {KIND_LABEL[kind]} study needs at least one load.",
                       "loads=[{\"type\": \"force\", \"faces\": [[x, y, z]], \"vector\": [0, 0, -100]}] (newtons).")
    out["fixtures"], out["loads"] = fixtures, ([] if kind == "modal" else loads)
    if kind == "modal" and loads:
        out["ignored"] = "Loads are ignored in a modal study (no prestress)."
    mat = body.get("material")
    out["material"] = mat if isinstance(mat, (str, dict)) and mat else None
    mats = body.get("materials") or {}
    if not isinstance(mats, dict):
        raise _err("materials is {part id: material} for a design of several parts.")
    out["materials"] = {str(k): v for k, v in mats.items() if v}
    if kind in ("modal", "buckling"):
        try:
            out["modes"] = max(1, min(int(body.get("modes") or (6 if kind == "modal" else 3)), 20))
        except (TypeError, ValueError):
            raise _err("modes is a whole number (1 to 20).") from None
    mesh = {}
    for k, v in (body.get("mesh") or {}).items():
        if k not in MESH_OPTIONS:
            raise _err(f"Unknown mesh option “{k}”.", "Options: " + ", ".join(MESH_OPTIONS) + ".")
        lo, hi = MESH_OPTIONS[k]
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise _err(f"mesh.{k} is a number.") from None
        if not lo <= x <= hi:
            raise _err(f"mesh.{k} = {x:g} is outside {lo:g} to {hi:g}.")
        mesh[k] = int(x) if k in ("levels_max", "dof_max") else x
    out["mesh"] = mesh
    return out


def _store(p: dict) -> dict:
    return p.setdefault("strength", {})


def definitions(p: dict) -> list:
    return list((p.get("strength") or {}).values())


def get(p: dict, sid: str) -> dict:
    d = (p.get("strength") or {}).get(sid)
    if d is None:
        raise _err(f"Unknown study “{sid}”.", "strength_study lists a design's studies when called without a definition.",
                   status=404)
    return d


def define(st, p: dict, body: dict, by: str = "agent", sid: str | None = None) -> dict:
    """Add a study to the project, or replace the definition of study `sid`. Saves the project (under its lock)."""
    d = clean(body)
    with st.lock(p["id"]):
        cur = st.load(p["id"])
        store = _store(cur)
        if sid is None:
            if len(store) >= MAX_STUDIES:
                raise _err(f"A design holds at most {MAX_STUDIES} studies.", "Remove one first.")
            sid = "s" + uuid.uuid4().hex[:7]
        elif sid not in store:
            raise _err(f"Unknown study “{sid}”.", status=404)
        n = len(store) + (0 if sid in store else 1)
        d.update({"id": sid, "name": d["name"] or (store.get(sid) or {}).get("name") or f"{KIND_LABEL[d['kind']].capitalize()} {n}",
                  "rev": cur["head"], "ts": time.time(), "by": by})
        store[sid] = d
        st.save(cur)
    p["strength"] = cur["strength"]
    return d


def remove(st, p: dict, sid: str) -> dict:
    with st.lock(p["id"]):
        cur = st.load(p["id"])
        if sid not in (cur.get("strength") or {}):
            raise _err(f"Unknown study “{sid}”.", status=404)
        cur["strength"].pop(sid)
        st.save(cur)
    shutil.rmtree(_dir(st, p, sid), ignore_errors=True)
    p["strength"] = cur.get("strength") or {}
    return {"removed": sid}


# ---- materials of a study --------------------------------------------------------------------------------------

def _part_ids(st, p: dict, rev: int | None = None) -> list:
    """Part ids of a design that declares an assembly (no kernel call), else []."""
    try:
        recipe = st.recipe(p, rev)
        if st._declares_assembly(recipe):
            spec = recipe.assembly(st.rev(p, rev)["values"])
            if spec is not None and len(spec.parts) >= 2:
                return [(q.id, q.material or "") for q in spec.parts]
    except Exception:                                    # noqa: BLE001 - a design that does not load has no parts here
        pass
    return []


def materials_for(st, p: dict, d: dict, rev: int | None = None) -> dict:
    """{part id ("" for a design of one solid): resolved material}. A part's material is, in order: the study's own
    for that part, the study's material, the part's material in the design (set_appearance, or Part(material=)), the
    design's material."""
    from .. import materials as app
    parts = _part_ids(st, p, rev)
    out = {}
    for pid_, declared in (parts or [("", "")]):
        choice = (d.get("materials") or {}).get(pid_) or d.get("material") \
            or app.resolved(p, pid_).get("material") or (app._key(declared) if declared else None)
        if not choice:
            who = f"part “{pid_}”" if pid_ else "the design"
            raise _err(f"No material is set for {who}, and a strength study needs one.",
                       "Give material=\"AL-6061\" (or the values with their source) with the study, or set the "
                       "design's material with set_appearance.")
        out[pid_] = material_mod.resolve(choice)
    return out


# ---- keys, the store and state ---------------------------------------------------------------------------------

def _dir(st, p: dict, sid: str) -> Path:
    return st.dir(p["id"]) / "artifacts" / "studies" / f"strength.{sid}"


def _engine_tag(cfg) -> list:
    from .. import engines
    info = engines.info(ENGINE, cfg) or {}
    return [KEY_VERSION, sorted(info.get("pins") or engines.SPECS[ENGINE]["pins"])]


def key(st, p: dict, d: dict, rev: int | None = None) -> str:
    mats = materials_for(st, p, d, rev)
    numbers = {k: [m["E"], m["nu"], m.get("density"), m.get("yield")] for k, m in mats.items()}
    core = {k: d.get(k) for k in ("kind", "fixtures", "loads", "modes", "mesh")}
    return H("fea", st.keys(p, rev)["geometry"], core, numbers, _engine_tag(st.cfg))


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    from .. import fsutil
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, default=float), encoding="utf-8")
    fsutil.replace(tmp, path)


def _log(st, p, sid) -> list:
    return _read(_dir(st, p, sid) / "log.json") or []


def _running_job(st, pid: str, sid: str):
    for j in st.jobs.values():
        if j.get("kind") == "strength" and j.get("project") == pid and j.get("study") == sid and j.get("state") == "running":
            return j
    return None


def state(st, p: dict, sid: str) -> dict:
    """One study's state: never | current | stale | failed | running | unavailable, with its headline when there is a
    result and, when stale, the revision the newest result describes."""
    d = get(p, sid)
    out = {"id": sid, "name": d["name"], "kind": d["kind"], "defined_on_rev": d.get("rev")}
    try:
        k = key(st, p, d)
    except Exception as e:                               # noqa: BLE001 - e.g. no material: the study cannot be keyed
        out.update({"state": "unavailable", "why": str(e), "hint": getattr(e, "hint", "")})
        return out
    out["key"] = k
    job = _running_job(st, p["id"], sid)
    res = _read(_dir(st, p, sid) / f"{k}.json")
    fail = _read(_dir(st, p, sid) / f"{k}.failed.json")
    log = [x for x in _log(st, p, sid) if x.get("ok")]
    if job is not None:
        out.update({"state": "running", "job": job["id"], "progress": (job.get("steps") or [{}])[0].get("progress")})
    elif res is not None:
        out.update({"state": "current", "rev": res.get("rev"), "headline": res.get("headline"), "evidence": res.get("evidence"),
                    "converged": res.get("converged"), "ts": res.get("ts")})
    elif fail is not None:
        out.update({"state": "failed", "error": fail.get("error"), "rev": fail.get("rev")})
    elif log:
        last = log[-1]
        old = _read(_dir(st, p, sid) / f"{last['key']}.json") or {}
        out.update({"state": "stale", "last_rev": last.get("rev"), "last_key": last.get("key"),
                    "headline": old.get("headline"), "evidence": old.get("evidence"),
                    "why": f"The stored result describes revision {last.get('rev')} with the inputs of that run; the "
                           "geometry, the material's values, the loads or the engine changed since. Run it again."})
    else:
        out["state"] = "never"
    if out["state"] in ("never", "stale", "failed") and python(st.cfg) is None:
        out["unavailable"] = HOW_TO_GET
    return out


def listing(st, p: dict) -> list:
    return [state(st, p, d["id"]) for d in definitions(p)]


def result(st, p: dict, sid: str, stale_ok: bool = True) -> dict:
    """The stored result of a study with its state. When the head's result is missing and stale_ok, the newest stored
    one, marked stale with the revision it describes."""
    s = state(st, p, sid)
    out = {"study": get(p, sid), "state": s}
    k = s.get("key") if s["state"] == "current" else (s.get("last_key") if stale_ok and s["state"] == "stale" else None)
    if k:
        out["result"] = _read(_dir(st, p, sid) / f"{k}.json")
        out["result_key"] = k
        if s["state"] == "stale" and out["result"] is not None:
            out["result"]["stale"] = True
            out["result"]["evidence"] = f"{out['result'].get('evidence')}, stale: describes revision {s.get('last_rev')}"
    return out


def field(st, p: dict, sid: str) -> dict:
    """The field data of the head's result (what the viewport colours): see docs/STRENGTH.md, "Field data"."""
    s = state(st, p, sid)
    if s["state"] != "current":
        raise _err(f"The study has no current result (state: {s['state']}).", "Run it first; a stale field is not drawn.",
                   status=409)
    f = _read(_dir(st, p, sid) / f"{s['key']}.field.json")
    if f is None:
        raise _err("The result has no field data.", status=404)
    return f


def field_path(st, p: dict, sid: str) -> Path | None:
    s = state(st, p, sid)
    f = _dir(st, p, sid) / f"{s.get('key')}.field.json"
    return f if s["state"] == "current" and f.is_file() else None


# ---- running ---------------------------------------------------------------------------------------------------

def headline(d: dict, r: dict) -> str:
    if r["kind"] == "static":
        if not r.get("converged"):
            return "not converged: " + (r.get("not_converged_because") or "")
        err = 100 * (r["discretisation_error"]["stress"] or 0)
        sf = r.get("safety_factor")
        head = f"safety factor {sf['value']:.2f} (at least {sf['low']:.2f})" if sf else "no safety factor (no yield strength)"
        return (f"{head}; peak von Mises {r['peak_von_mises_MPa']:.3g} MPa ± {err:.1f} %, "
                f"max displacement {r['max_displacement_mm']:.3g} mm")
    if r["kind"] == "modal":
        f = r["frequencies_Hz"]
        tail = "" if r.get("converged") else " (not converged)"
        return "natural frequencies " + ", ".join(f"{x:.4g}" for x in f[:4]) + (" ..." if len(f) > 4 else "") + " Hz" + tail
    tail = "" if r.get("converged") else " (not converged)"
    return f"buckles at {r['load_factor']:.3g} x the loads{tail}"


def _engine_spec(d: dict, prep: dict, mats: dict) -> dict:
    picks = iter(prep["picks"])

    def refs(faces):
        out = []
        for _ in faces:
            pk = next(picks)
            out.append({"samples": pk["samples"], "area": pk["area"], "_pick": pk})
        return out
    fixtures, loads = [], []
    for f in d["fixtures"]:
        rs = refs(f["faces"])
        item = {"type": f["type"], "faces": rs}
        if f["type"] == "hold":
            item["directions"] = f["directions"]
        if f["type"] == "pin":
            bad = [r["_pick"] for r in rs if r["_pick"]["type"] != "cylinder"]
            if bad:
                raise _err(f"A pin needs a cylindrical face (a hole or a shaft); the face at {bad[0]['at']} is a "
                           f"{bad[0]['type']}.", "Use a roller on a flat face, or pick the wall of the hole.")
            item["axis"] = rs[0]["_pick"]["axis"]
        fixtures.append(item)
    for ld in d["loads"]:
        if ld["type"] == "gravity":
            loads.append({"type": "gravity", "vector": ld["vector"]})
            continue
        item = {k: v for k, v in ld.items() if k not in ("faces", "faces_b")}
        item["faces"] = refs(ld["faces"])
        if ld["type"] == "preload":
            item["faces_b"] = refs(ld["faces_b"])
        loads.append(item)
    for group in fixtures + loads:
        for k in ("faces", "faces_b"):
            for r in group.get(k) or []:
                r.pop("_pick", None)
    materials = []
    for part in prep["parts"]:
        m = material_mod.engine_material(mats[part["id"]])
        materials.append({**m, "centre": part["centre"], "part": part["id"]})
    spec = {"kind": d["kind"], "materials": materials, "fixtures": fixtures, "loads": loads, "mesh": dict(d.get("mesh") or {})}
    if d.get("modes"):
        spec["modes"] = d["modes"]
    return spec


def _picks(d: dict) -> list:
    out = []
    for f in d["fixtures"]:
        out.extend(f["faces"])
    for ld in d["loads"]:
        out.extend(ld.get("faces") or [])
        out.extend(ld.get("faces_b") or [])
    return [{"at": x["at"]} for x in out]


def _spawn(py: Path, work: Path, on_progress, cancelled) -> int:
    from .. import engines
    cmd = [str(py), "-m", "form.fea.run", str(work)]
    env = engines.child_env({"OMP_NUM_THREADS": str(max(1, min(8, (os.cpu_count() or 2) // 2)))})
    if Path(py) == Path(sys.executable):              # a developer's environment: this Python, as it is
        env = {**os.environ, "PYTHONPATH": str(engines.src_root()) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env, **kw)
    err_tail = []

    def drain():
        for line in proc.stderr:
            err_tail.append(line)
            del err_tail[:-40]
    threading.Thread(target=drain, daemon=True).start()

    def pump():
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and "progress" in ev:
                on_progress(ev)
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    t0 = time.time()
    while proc.poll() is None:
        if cancelled():
            (work / "cancel").write_text("1", encoding="utf-8")
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            return -1
        if time.time() - t0 > TIMEOUT_S:
            proc.kill()
            proc.wait(timeout=10)
            return -2
        time.sleep(0.1)
    t.join(timeout=2)
    for pipe in (proc.stdout, proc.stderr):
        try:
            pipe.close()
        except OSError:
            pass
    if proc.returncode not in (0, 1, 2) or not (work / "result.json").is_file():
        (work / "stderr.txt").write_text("".join(err_tail), encoding="utf-8")
    return proc.returncode


def run(st, pid: str, sid: str, force: bool = False, on_progress=None, cancelled=None) -> dict:
    """Run a study now, in this thread, and store its result. Returns result(). A result already stored under the
    head's key is returned as it is unless force."""
    p = st.load(pid)
    d = get(p, sid)
    on_progress = on_progress or (lambda ev: None)
    cancelled = cancelled or (lambda: False)
    rev = st.rev(p)
    mats = materials_for(st, p, d)
    k = key(st, p, d)
    base = _dir(st, p, sid)
    if not force and (base / f"{k}.json").is_file():
        return {**result(st, p, sid), "cached": True}
    py = python(st.cfg)
    if py is None:
        raise _err("The strength solver is not installed, so the study was not run. No result was made up.", HOW_TO_GET,
                   status=409, kind="unavailable")
    work = base / f"{k}.work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def fail(err: dict):
        _write(base / f"{k}.failed.json", {"error": err, "rev": rev["n"], "ts": time.time()})
        _append_log(st, p, sid, k, rev["n"], False)
        shutil.rmtree(work, ignore_errors=True)
    try:
        on_progress({"progress": "Preparing the solid", "fraction": 0.0})
        prep = st._k("fea_prepare", timeout=300, key=st.keys(p)["geometry"], recipe_id=st.rid(p), values=rev["values"],
                     out_step=str(work / "solid.step"), picks=_picks(d), p=p)
        if prep.get("error"):
            raise _err(prep["error"])
        spec = _engine_spec(d, prep, mats)
        _write(work / "job.json", {"step": prep["step"], "spec": spec})
        code = _spawn(py, work, on_progress, cancelled)
        if code == -1:
            shutil.rmtree(work, ignore_errors=True)
            raise _err("Cancelled. No result was stored.", status=409, kind="cancelled")
        if code == -2:
            raise _err(f"The study did not finish in {TIMEOUT_S} s and was stopped.", "Give it a coarser start: mesh.h0.")
        out = _read(work / "result.json")
        if out is None:
            tail = (_read_text(work / "stderr.txt") or "")[-800:]
            raise _err("The solver stopped without a result." + (f" Its last words: {tail}" if tail else ""),
                       "Check the engine in Settings, Engines & software.", status=500, kind="engine")
        if out.get("error"):
            e = out["error"]
            if e.get("kind") == "cancelled":
                shutil.rmtree(work, ignore_errors=True)
                raise _err("Cancelled. No result was stored.", status=409, kind="cancelled")
            raise _err(e.get("message", "The study failed."), e.get("hint", ""), status=422, kind=e.get("kind"))
    except Exception as e:
        if getattr(e, "extra", {}).get("kind") != "cancelled":
            pub = e.public() if hasattr(e, "public") else {"message": f"{type(e).__name__}: {e}"}
            fail(pub if isinstance(pub, dict) else {"message": str(e)})
        raise
    out.update({
        "id": sid, "name": d["name"], "key": k, "rev": rev["n"], "ts": time.time(), "wall_seconds": round(time.time() - t0, 2),
        "definition": {x: d.get(x) for x in ("kind", "fixtures", "loads", "modes", "mesh")},
        "materials": {pid_ or "design": {x: m.get(x) for x in ("name", "key", "kind", "E", "nu", "density", "yield",
                                                                "strength_basis", "sources", "notes", "knockdown")}
                      for pid_, m in mats.items()},
        "units": {"E": "MPa", "yield": "MPa", "density": "kg/m3", "length": "mm", "force": "N", "stress": "MPa"},
        "faces": [{x: pk.get(x) for x in ("at", "part", "feature", "type", "area", "radius")} for pk in prep["picks"]],
        "frame": "assembled" if prep["assembled"] else "as built",
    })
    notes = [n for m in mats.values() for n in m.get("notes") or []]
    if notes:
        out["material_notes"] = sorted(set(notes))
    sf = out.get("safety_factor")
    if sf:
        basis = sorted({m.get("strength_basis") or "yield strength" for m in mats.values()})
        sf["against"] = "; ".join(basis)
        sf["strength_source"] = {pid_ or "design": (m.get("sources") or {}).get("yield") for pid_, m in mats.items()}
    out["headline"] = headline(d, out)
    out["how_known"] = (f"{out['evidence']}: {out['model']}; mesh of {out['mesh']['tets']:,} quadratic tetrahedra "
                        f"({out['mesh']['unknowns']:,} unknowns, mean size {out['mesh']['h_mean_mm']:g} mm); "
                        f"{len(out['convergence']['levels'])} refinements. Not a test of the made part.")
    fld = _read(work / "field.json")
    if fld is not None:
        fld.update({"study": sid, "key": k, "rev": rev["n"], "kind": d["kind"], "frame": out["frame"],
                    "evidence": out["evidence"]})
        _write(base / f"{k}.field.json", fld)
    _write(base / f"{k}.json", out)
    (base / f"{k}.failed.json").unlink(missing_ok=True)
    _append_log(st, p, sid, k, rev["n"], True)
    shutil.rmtree(work, ignore_errors=True)
    _prune(st, p, sid, keep=k)
    try:
        st.activity(pid, "study", f"{d['name']}: {out['headline']} [{out['evidence']}]", by="engine")
    except Exception:                                    # noqa: BLE001 - the feed is not the record
        pass
    return result(st, st.load(pid), sid)


def pick_static(p: dict, sid: str = "") -> str:
    """The static study a search uses as its strength constraint: the one named, else the design's only one."""
    if sid:
        d = get(p, sid)
        if d["kind"] != "static":
            raise _err(f"Study “{sid}” is a {KIND_LABEL[d['kind']]} study; a strength constraint needs a static one.")
        return sid
    statics = [d for d in definitions(p) if d["kind"] == "static"]
    if not statics:
        raise _err("The design has no static strength study, so there is nothing for fea.safety_factor to be read from.",
                   "Define one first with strength_study (the faces that are held, the faces that are loaded, the "
                   "material); the search then solves it on its candidates.")
    if len(statics) > 1:
        raise _err("The design has several static studies; say which one the constraint is read from.",
                   "study=\"<id>\": " + ", ".join(f"{d['id']} ({d['name']})" for d in statics))
    return statics[0]["id"]


def evaluate(st, p: dict, sid: str, values: dict, budget_s: float = 45.0) -> dict:
    """Solve a study on candidate parameter values (not a revision): the engine's result, stored nowhere. The picked
    points are the study's own; a candidate on which a point no longer lands on a face raises StudioError."""
    d = get(p, sid)
    mats = materials_for(st, p, d)
    py = python(st.cfg)
    if py is None:
        raise _err("The strength solver is not installed, so the constraint cannot be checked. Nothing was made up.",
                   HOW_TO_GET, status=409, kind="unavailable")
    rid = st.rid(p)
    vals = {**st.rev(p)["values"], **{k: float(v) for k, v in (values or {}).items()}}
    work = _dir(st, p, sid) / f"candidate-{uuid.uuid4().hex[:8]}.work"
    work.mkdir(parents=True, exist_ok=True)
    try:
        prep = st._k("fea_prepare", timeout=300, key="pv-" + H(rid, vals), recipe_id=rid, values=vals,
                     out_step=str(work / "solid.step"), picks=_picks(d), p=p)
        if prep.get("error"):
            raise _err(prep["error"])
        spec = _engine_spec(d, prep, mats)
        spec["mesh"] = {**spec.get("mesh", {}), "budget_s": min(float(spec.get("mesh", {}).get("budget_s", budget_s)), budget_s)}
        _write(work / "job.json", {"step": prep["step"], "spec": spec})
        from .. import taskstore
        code = _spawn(py, work, lambda ev: None, taskstore.cancelled)
        if code == -1:
            raise _err("Cancelled.", status=409, kind="cancelled")
        out = _read(work / "result.json")
        if out is None:
            raise _err("The solver stopped without a result.", status=500, kind="engine")
        if out.get("error"):
            raise _err(out["error"].get("message", "The study failed."), out["error"].get("hint", ""), status=422,
                       kind=out["error"].get("kind"))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _append_log(st, p, sid, k, rev, ok) -> None:
    with st.lock(p["id"]):
        entries = _log(st, p, sid)
        entries.append({"key": k, "rev": rev, "ts": time.time(), "ok": bool(ok)})
        _write(_dir(st, p, sid) / "log.json", entries[-60:])


def _prune(st, p, sid, keep: str, n: int = 6) -> None:
    """Keep the newest few results of a study (each a few hundred kB with its field)."""
    base = _dir(st, p, sid)
    files = sorted((f for f in base.glob("*.json") if f.name not in ("log.json",) and not f.name.endswith((".field.json", ".failed.json"))),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[n:]:
        if f.stem != keep:
            f.unlink(missing_ok=True)
            (base / f"{f.stem}.field.json").unlink(missing_ok=True)


def start(st, pid: str, sid: str, force: bool = False) -> dict:
    """Run a study in the background. Returns the job ({"id", "state", ...} in Studio.jobs: get_job waits for it,
    cancel_job stops it). A study that is already running returns its job."""
    from .. import taskstore
    p = st.load(pid)
    d = get(p, sid)
    running = _running_job(st, pid, sid)
    if running is not None:
        return running
    materials_for(st, p, d)                              # refuse now what cannot run: no material, no engine
    if python(st.cfg) is None:
        raise _err("The strength solver is not installed, so the study was not run. No result was made up.", HOW_TO_GET,
                   status=409, kind="unavailable")
    step = {"node": "strength", "label": f"{KIND_LABEL[d['kind']].capitalize()} study: {d['name']}", "state": "running",
            "progress": {"label": "Queued", "value": 0.0}}
    job = {"id": uuid.uuid4().hex[:10], "project": pid, "kind": "strength", "study": sid, "state": "running",
           "started": time.time(), "steps": [step]}
    st.jobs[job["id"]] = job
    jid = job["id"]

    def on_progress(ev):
        step["progress"] = {"label": ev.get("progress"), "value": ev.get("fraction"), "seconds": ev.get("seconds")}
        st.jobs.save(job)

    def work():
        try:
            r = run(st, pid, sid, force=force, on_progress=on_progress, cancelled=lambda: st.jobs.cancel_requested(jid))
            step["state"] = "cached" if r.get("cached") else "done"
            job["state"] = "done"
            r = result(st, st.load(pid), sid)            # read again now that the job no longer counts as running
            job["result"] = {"study": sid, "state": r["state"]["state"], "headline": (r.get("result") or {}).get("headline"),
                             "evidence": (r.get("result") or {}).get("evidence"),
                             "converged": (r.get("result") or {}).get("converged")}
        except Exception as e:                           # noqa: BLE001 - the job carries the failure
            cancelled = getattr(e, "extra", {}).get("kind") == "cancelled"
            step["state"] = "cancelled" if cancelled else "failed"
            job["state"] = "cancelled" if cancelled else "failed"
            job["error"] = e.public() if hasattr(e, "public") else {"message": f"{type(e).__name__}: {e}"}
        step.pop("progress", None)
        job["finished"] = time.time()
        st.jobs.save(job)
        st.jobs.clear_cancel(jid)
    taskstore.child("strength", jid, pid, lambda: st.jobs.request_cancel(jid), lambda: job["state"] != "running",
                    lambda: (step.get("progress") or {}).get("label") or step["label"])
    threading.Thread(target=work, daemon=True, name=f"strength-{jid}").start()
    return job
