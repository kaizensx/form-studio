"""CAM for a design in a Studio: plans, posted programs and simulations as artifacts keyed by their inputs, the
project's pointer to the current one, the release gate and the Bench entry.

A program is *current* when its key is the one computed from the head revision's geometry, the plan's options
(tools, material, machine, stock, setups, operations, speeds and feeds), the speeds-and-feeds table and the post
(dialect, units, work offset), and the files on disk still have the hashes that were simulated. Anything else is
stale: there is no flag to set by hand.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from . import feeds, posts as post_mod

RESULTS = ("good", "gouged", "collision", "left_material", "scrapped")


def _cam():
    from .. import cam
    return cam


def _dir(st, p) -> Path:
    return st.dir(p["id"]) / "artifacts" / "cam"


def _write(path: Path, data) -> None:
    from .. import fsutil
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, (bytes, str)):
        tmp.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    else:
        tmp.write_text(json.dumps(data), encoding="utf-8")
    fsutil.replace(tmp, path)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def target(st, p: dict, rev: int | None = None) -> tuple[np.ndarray, list, str]:
    """The revision's triangles and bores from the kernel (kept beside the plan), and its geometry key."""
    from . import target as tg
    r = st.rev(p, rev)
    gk = st.keys(p, r["n"])["geometry"]
    path = _dir(st, p) / f"target-{gk}-{tg.VERSION}.npz"
    if path.is_file():
        try:
            z = np.load(path, allow_pickle=False)
            return z["tri"], json.loads(str(z["holes"])), gk
        except (OSError, ValueError, KeyError):
            pass
    if getattr(st.recipe(p, r["n"]), "mesh", False):
        raise _cam()._err("A mesh design has no exact solid to machine from.",
                          "Make it a CAD design first (reconstruct), then plan the machining.")
    out = st._k("cam_target", timeout=600, key=gk, recipe_id=st.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"])
    tri = np.frombuffer(base64.b64decode(out["positions"]), dtype=np.float64).reshape(-1, 3, 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(tmp, tri=tri, holes=np.array(json.dumps(out["holes"])))
    from .. import fsutil
    fsutil.replace(tmp, path)
    return tri, out["holes"], gk


def plan_key(gk: str, options: dict) -> str:
    cam = _cam()
    from . import paths, sim
    return cam.H("cam-plan", cam.VERSION, sim.VERSION, feeds.VERSION, getattr(paths, "VERSION", 1), gk,
                 cam.clean(options), feeds.digest())


def _wave_e_setups(st, p, options: dict) -> tuple[list | None, str]:
    """The setups Wave E's access analysis chose for the largest flat tool: (directions, what was done)."""
    cam = _cam()
    from . import tools as tools_mod
    try:
        from .. import dfm
        tl = tools_mod.library(options.get("tools"))
        flat = max((t for t in tl if t.kind in ("flat", "bull")), key=lambda t: t.d, default=None)
        if flat is None:
            return None, "no flat tool to ask the access analysis with"
        res = dfm.check(st, p, "cnc", {"tool_d": flat.d, "flute_l": flat.flute_l or None,
                                       "holder_d": flat.holder_d or None}, overlay_file=False)
        chosen = (res.get("data") or {}).get("setups") or []
        ups = []
        for s in chosen:
            try:
                ups.append(list(cam._up(str(s["setup"]))))
            except Exception:                       # noqa: BLE001 - a 4- or 5-axis name: not a 3-axis setup
                continue
        if not ups:
            return None, "the access analysis proposed no 3-axis setup"
        return ups, f"setups from the access analysis (form/dfm, Ø{flat.d:g} mm flat): " + ", ".join(s["setup"] for s in chosen)
    except Exception as e:                          # noqa: BLE001 - the analysis is advice; +Z is the stated fallback
        return None, f"the access analysis could not run ({type(e).__name__}); planned from +Z only"


def plan(st, p: dict, options: dict | None = None, rev: int | None = None, force: bool = False) -> dict:
    """Plan the machining of a revision (head by default) and remember it as the project's current CAM plan."""
    cam = _cam()
    o = cam.clean(options)
    tri, holes, gk = target(st, p, rev)
    r = st.rev(p, rev)
    pk = plan_key(gk, o)
    path = _dir(st, p) / f"plan-{pk}.json"
    got = None if force else _read(path)
    if got is None:
        eff = dict(o)
        note = None
        if o.get("setups") == "auto":
            ups, note = _wave_e_setups(st, p, o)
            eff["setups"] = ups or [[0, 0, 1]]
        got = cam.make_plan(tri, holes, eff, name=p.get("name") or p["id"])
        if o.get("setups") == "auto":
            kept = [s for s in got["setups"] if s["events"]]
            dropped = [s["name"] for s in got["setups"] if not s["events"]]
            if kept:
                got["setups"] = kept
                for i, s in enumerate(kept, 1):
                    s["n"] = i
            got["notes"].append(note + (f"; nothing to cut from {', '.join(dropped)}" if dropped else ""))
            if len(got["setups"]) < 2:
                got["notes"] = [n for n in got["notes"] if "earlier setup removed" not in n]
        got["options"] = o
        got.update({"project": p["id"], "rev": r["n"], "geometry_key": gk, "key": pk, "planned_at": time.time()})
        _write(path, got)
    with st.lock(p["id"]):
        q = st.load(p["id"])
        c = dict(q.get("cam") or {})
        if c.get("plan_key") != pk:
            c = {"include": bool(c.get("include")), "dialect": c.get("dialect"), "units": c.get("units", "mm"),
                 "wcs": c.get("wcs", "G54")}
        c.update({"options": o, "plan_key": pk, "rev": r["n"]})
        q["cam"] = c
        st.save(q)
        p["cam"] = c
    return got


def _current_plan(st, p: dict, options: dict | None = None) -> dict:
    c = p.get("cam") or {}
    if options is None and c.get("options") is None:
        raise _cam()._err("This design has no CAM plan yet.", "Plan it first: cam_plan, or `form cam plan <project>`.")
    return plan(st, p, options if options is not None else c["options"])


def post(st, p: dict, dialect: str | None = None, options: dict | None = None, units: str | None = None,
         wcs: str | None = None, include: bool | None = None, line_numbers: bool = False, sim_cell: float | None = None,
         force: bool = False) -> dict:
    """Post the current plan (or plan with `options` first), write the program(s), read each back, simulate it
    from the file and store the result. include=True asks for the program to go into the next release."""
    cam = _cam()
    pl = _current_plan(st, p, options)
    c = dict(p.get("cam") or {})
    did = post_mod.dialect_id(dialect or c.get("dialect") or "grbl")
    units = units or c.get("units") or "mm"
    wcs = (wcs or c.get("wcs") or "G54").upper()
    d = _dir(st, p)
    tri, _holes, gk = target(st, p)
    if pl.get("geometry_key") != gk:
        pl = plan(st, p, pl["options"])
    pok = cam.H("cam-post", pl["key"], did, units, wcs, bool(line_numbers), post_mod.DIALECTS[did]["label"])
    ext = post_mod.DIALECTS[did]["ext"]
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (p["id"]))[:40]
    programs = []
    for s in pl["setups"]:
        if not s["events"]:
            continue
        text = cam.post_setup(pl, s, did, units, wcs, line_numbers)
        name = f"{stem}_r{pl['rev']:02d}_setup{s['n']}_{did}{ext}"
        f = d / pok / name
        _write(f, text)
        programs.append({"setup": s["n"], "name": s["name"], "file": str(f), "filename": name,
                         "sha256": hashlib.sha256(text.encode()).hexdigest(), "lines": text.count("\n")})
    if not programs:
        raise cam._err("The plan has nothing to cut.", "Check the stock: with a blank the size of the part and no "
                       "pockets there is nothing to machine.")
    with st.lock(p["id"]):
        q = st.load(p["id"])
        cc = dict(q.get("cam") or {})
        cc.update({"options": pl["options"], "plan_key": pl["key"], "rev": pl["rev"], "dialect": did, "units": units,
                   "wcs": wcs, "post_key": pok, "programs": programs, "line_numbers": bool(line_numbers),
                   "posted_at": time.time()})
        if include is not None:
            cc["include"] = bool(include)
        cc.pop("sim_key", None)
        q["cam"] = cc
        st.save(q)
        p["cam"] = cc
    res = simulate(st, p, sim_cell=sim_cell, force=force)
    return {"project": p["id"], "rev": pl["rev"], "dialect": did, "post": post_mod.DIALECTS[did]["label"], "units": units,
            "wcs": wcs, "programs": programs, "label": cam.LABEL, "include_in_release": bool(p["cam"].get("include")),
            "simulation": res, "preview": _head(programs[0]["file"]), "status": status(st, p)}


def _head(path, n: int = 40) -> str:
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8").splitlines()[:n])
    except OSError:
        return ""


def sim_key(c: dict, sim_cell) -> str:
    cam = _cam()
    from . import sim
    return cam.H("cam-sim", sim.VERSION, c.get("post_key"), [x["sha256"] for x in c.get("programs", [])], sim_cell)


def simulate(st, p: dict, sim_cell: float | None = None, force: bool = False, full: bool = False) -> dict:
    """Simulate the posted program(s) from their files and measure them against the head revision's solid."""
    cam = _cam()
    c = p.get("cam") or {}
    if not c.get("programs"):
        raise cam._err("Nothing has been posted yet.", "Post the plan first: cam_post, or `form cam post <project> --machine grbl`.")
    stt = status(st, p)
    if stt["state"] == "stale":                       # another solid, other tools or options, or a file changed by hand
        raise cam._err("The posted program is stale: " + "; ".join(stt["why"]) + ".", "Post again: cam_post.", status=409)
    d = _dir(st, p)
    sk = sim_key(c, sim_cell)
    path = d / f"sim-{sk}.json"
    got = None if force else _read(path)
    if got is None:
        pl = _read(d / f"plan-{c['plan_key']}.json")
        if pl is None:
            raise cam._err("The plan this program was posted from is gone.", "Plan and post again.")
        tri, _holes, gk = target(st, p)
        sims = []
        for prog in c["programs"]:
            try:
                text = Path(prog["file"]).read_text(encoding="utf-8")
            except OSError:
                raise cam._err("A posted program file is missing.", "Post again: cam_post.")
            s = next(x for x in pl["setups"] if x["n"] == prog["setup"])
            sims.append(cam.simulate_setup(pl, s, tri, text, c["dialect"], cell=sim_cell, units=c.get("units", "mm"),
                                           keep_arrays=True))
        v = cam.view(pl, sims)
        vpath = d / f"view-{sk}.json"
        _write(vpath, v)
        for s in sims:
            s.pop("_arrays", None)
        got = {"project": p["id"], "rev": pl["rev"], "key": sk, "plan_key": c["plan_key"], "post_key": c.get("post_key"),
               "geometry_key": gk, "dialect": c["dialect"], "evidence": "simulated", "label": cam.LABEL,
               "summary": cam.summary_sim(sims), "setups": sims, "assumed": pl.get("assumed", []),
               "notes": pl.get("notes", []) + [n for s in pl["setups"] for n in s.get("notes", [])],
               "view_file": str(vpath), "programs": c["programs"], "simulated_at": time.time()}
        _write(path, got)
    else:
        got["cached"] = True
    if c.get("sim_key") != sk:
        with st.lock(p["id"]):
            q = st.load(p["id"])
            cc = dict(q.get("cam") or {})
            cc["sim_key"] = sk
            q["cam"] = cc
            st.save(q)
            p["cam"] = cc
    return got if full else compact(got)


def compact(res: dict) -> dict:
    """The simulation without the long lists, for MCP and the CLI."""
    out = {k: v for k, v in res.items() if k != "setups"}
    out["setups"] = []
    for s in res["setups"]:
        t = {k: v for k, v in s.items() if k not in ("collisions",)}
        t["collisions"] = s.get("collisions", [])[:10]
        out["setups"].append(t)
    return out


def status(st, p: dict) -> dict:
    """Where the project's CAM stands: none, planned, posted (not simulated), current or stale, and why."""
    cam = _cam()
    c = p.get("cam") or {}
    if not c.get("plan_key"):
        return {"state": "none", "label": None}
    why, plan_stale = [], False
    try:
        gk = st.keys(p)["geometry"]
        pk = plan_key(gk, c.get("options") or {})
    except Exception as e:                          # noqa: BLE001 - a head that does not build has no current program
        return {"state": "stale", "why": [f"the head revision could not be keyed ({type(e).__name__})"], "plan_stale": True,
                "label": cam.LABEL}
    if pk != c["plan_key"]:
        plan_stale = True
        why.append(f"the design, the tools, the options or the speeds table changed since r{c.get('rev')} was planned")
    out = {"state": "planned", "why": why, "rev": c.get("rev"), "dialect": c.get("dialect"), "label": cam.LABEL,
           "include_in_release": bool(c.get("include")), "plan_stale": plan_stale}
    if not c.get("programs"):
        out["state"] = "stale" if plan_stale else "planned"
        return out
    for prog in c["programs"]:
        f = Path(prog["file"])
        if not f.is_file():
            why.append(f"{prog['filename']} is missing")
        elif hashlib.sha256(f.read_bytes()).hexdigest() != prog["sha256"]:
            why.append(f"{prog['filename']} was changed after it was posted")
    pok = cam.H("cam-post", c["plan_key"], c.get("dialect"), c.get("units", "mm"), c.get("wcs", "G54"),
                bool(c.get("line_numbers")), post_mod.DIALECTS.get(c.get("dialect"), {}).get("label"))
    if pok != c.get("post_key"):
        why.append("the post changed since the program was written")
    sres = _read(_dir(st, p) / f"sim-{c.get('sim_key')}.json") if c.get("sim_key") else None
    if why:
        out["state"] = "stale"
    elif sres is None or sres.get("post_key") != c.get("post_key"):
        out["state"] = "posted"
        why.append("the program has not been simulated")
    else:
        out["state"] = "current"
    if sres is not None and out["state"] == "current":
        out["simulation"] = sres["summary"]
        out["assumed"] = sres.get("assumed", [])
        out["programs"] = [{k: x[k] for k in ("setup", "filename", "sha256")} for x in c["programs"]]
        phys = _physical(p, c)
        out["physical"] = phys
        if phys:
            out["label"] = f"machined: {phys[-1]['result'].replace('_', ' ')} (a physical result recorded for this program)"
    return out


def _physical(p: dict, c: dict) -> list:
    shas = sorted(x["sha256"] for x in c.get("programs", []))
    return [e for e in p.get("evidence", []) if e.get("kind") == "machined" and sorted(e.get("programs", [])) == shas]


def record(st, p: dict, result: str, note: str = "") -> dict:
    """The evidence record for what the person saw when the current program ran on a machine."""
    cam = _cam()
    if result not in RESULTS:
        raise cam._err("Say how the machining went.", "result is one of: " + ", ".join(RESULTS) + ".")
    c = p.get("cam") or {}
    stt = status(st, p)
    if stt["state"] != "current":
        raise cam._err("There is no current simulated program to record a result for.",
                       "A physical result belongs to one posted program: post and simulate it first.", status=409)
    return {"kind": "machined", "result": result, "programs": [x["sha256"] for x in c["programs"]],
            "files": [x["filename"] for x in c["programs"]], "dialect": c.get("dialect"), "plan_key": c.get("plan_key"),
            "simulation": stt.get("simulation")}


def gate(st, p: dict) -> dict:
    """What CAM adds to the release gate. Nothing unless a program was asked into the release (`include`).
    {"include", "reasons" (each blocks), "warnings" [{"id", "label", "value"}], "label"}."""
    cam = _cam()
    c = p.get("cam") or {}
    if not c.get("include"):
        return {"include": False, "reasons": [], "warnings": []}
    stt = status(st, p)
    reasons, warns = [], []
    if stt["state"] != "current":
        reasons.append("CNC program: no current simulation (" + ("; ".join(stt.get("why") or []) or stt["state"]) + "). "
                       "Post and simulate again, or leave the program out of the release.")
        return {"include": True, "reasons": reasons, "warnings": warns, "label": cam.LABEL, "state": stt["state"]}
    s = stt["simulation"]
    if s["verdict"] != "pass":
        reasons.append("CNC program: the simulation fails: " + "; ".join(s["fails"][:4]) + ".")
    if stt.get("assumed"):
        reasons.append("CNC program: " + str(len(stt["assumed"])) + " value(s) nobody confirmed (" + "; ".join(stt["assumed"][:3])
                       + ("; ..." if len(stt["assumed"]) > 3 else "") + "). Give the tools and the speeds and feeds you will run.")
    if s.get("left"):
        warns.append({"id": "cam_leftover", "label": "CNC program leaves material",
                      "value": f"{s['leftover_mm3']:g} mm³ above tolerance, up to {s['leftover_max_mm']:g} mm (simulated)"})
    warns.append({"id": "cam_not_proven", "label": "CNC program",
                  "value": stt["label"] if stt.get("physical") else cam.LABEL})
    return {"include": True, "reasons": reasons, "warnings": warns, "label": stt["label"], "state": "current",
            "simulation": s, "programs": stt.get("programs")}


def release_files(st, p: dict, rel: Path) -> tuple[dict, dict]:
    """Copy the current program(s) and their simulation into a release folder: ({file: sha256}, manifest entry)."""
    import shutil
    cam = _cam()
    c = p.get("cam") or {}
    g = gate(st, p)
    if not g.get("include") or g["reasons"]:
        return {}, {}
    files = {}
    for prog in c["programs"]:
        shutil.copyfile(prog["file"], rel / prog["filename"])
        files[prog["filename"]] = prog["sha256"]
    sres = _read(_dir(st, p) / f"sim-{c['sim_key']}.json") or {}
    rep = report(p, c, sres, g["label"])
    (rel / "CAM_REPORT.md").write_text(rep, encoding="utf-8")
    files["CAM_REPORT.md"] = hashlib.sha256(rep.encode("utf-8")).hexdigest()
    entry = {"label": g["label"], "evidence": "simulated", "dialect": c.get("dialect"), "units": c.get("units"),
             "wcs": c.get("wcs"), "programs": [{k: x[k] for k in ("setup", "filename", "sha256")} for x in c["programs"]],
             "simulation": sres.get("summary"), "simulation_key": c.get("sim_key"), "plan_key": c.get("plan_key"),
             "physical_evidence": _physical(p, c),
             "text": "The G-code was simulated on a stock model and measured against the design. " + cam.LABEL.capitalize()
                     + ": prove it on the machine, starting above the work at reduced feed."}
    return files, entry


def report(p: dict, c: dict, sres: dict, label: str) -> str:
    s = sres.get("summary") or {}
    lines = [f"# {p.get('name', p['id'])}: CNC program", "", f"**{label.capitalize()}.**", "",
             f"Post: {post_mod.DIALECTS[c['dialect']]['label']}, units {c.get('units', 'mm')}, work offset {c.get('wcs', 'G54')}.", "",
             "## Files", ""] + [f"- `{x['filename']}` (setup {x['setup']}), sha256 `{x['sha256'][:16]}…`" for x in c.get("programs", [])]
    lines += ["", "## Simulation (stock height field, from the posted files)", "",
              f"- Verdict: {s.get('verdict')}" + (": " + "; ".join(s.get("fails", [])) if s.get("fails") else ""),
              f"- Gouge: {s.get('gouge_max_mm')} mm at most",
              f"- Leftover above tolerance: {s.get('leftover_mm3')} mm³, up to {s.get('leftover_max_mm')} mm",
              f"- Rapids through stock: {s.get('rapid_collisions')}; shank or holder into stock: {s.get('holder_collisions')}",
              f"- Removed: {s.get('removed_mm3')} mm³; cycle time {s.get('cycle_time')} (simulated)"]
    for st_ in sres.get("setups", []):
        lim = (st_.get("cycle_time") or {}).get("limits") or {}
        lines += ["", f"### Setup {st_['setup']} ({st_['name']})", "",
                  f"- Cell {st_.get('cell_mm')} mm, tolerance {st_.get('tolerance_mm')} mm, {st_.get('gouge', {}).get('samples')} surface samples",
                  f"- Machine limits: rapid {lim.get('rapid_mm_min')} mm/min, acceleration {lim.get('accel_mm_s2')} mm/s², "
                  f"junction deviation {lim.get('junction_deviation_mm')} mm"
                  + (f" (assumed: {', '.join(lim.get('assumed', []))})" if lim.get("assumed") else "")]
        for o in st_.get("ops", []):
            lines.append(f"- {o['n']}. {o.get('label')}, {o.get('tool')}: {o.get('removed_mm3')} mm³, {o.get('seconds')} s")
    lines += ["", "## Limits", "", "- A simulation of the motion on a model of the stock. Not judged: workholding, "
              "deflection, chatter, chip evacuation, surface finish, tool wear, the machine's travel and its own look-ahead.",
              "- Prove the program on the machine before trusting it.", ""]
    return "\n".join(lines)


def bench_status(st, p: dict) -> dict:
    return status(st, p)


# ---- the Bench (form/studies.py registers a provider's register_studies) ------------------------------------------

def register_studies(register) -> None:
    """One Bench entry: CNC, 3-axis."""
    from ..studies import Study

    def run(ctx):
        cam = _cam()
        opts = getattr(ctx, "opts", None) or {}
        o = opts.get("options") or (ctx.p.get("cam") or {}).get("options") or {}
        plan(ctx.st, ctx.p, o)
        out = post(ctx.st, ctx.p, opts.get("machine") or opts.get("dialect"))
        s = out["simulation"]["summary"]
        head = (f"CNC, 3-axis: {s['verdict']} · gouge {s['gouge_max_mm']} mm · leftover {s['leftover_mm3']} mm³ · "
                f"{s['cycle_time']} · {cam.LABEL}")
        return {"headline": head, "evidence": "simulated",
                "detail": "; ".join(s["fails"]) or f"{len(out['programs'])} program(s), {out['post']}",
                "data": {"summary": s, "status": out["status"], "programs": out["programs"]},
                "files": [x["file"] for x in out["programs"]] + [out["simulation"]["view_file"]]}

    def key(ctx):
        c = ctx.p.get("cam") or {}
        return _cam().H("cam-bench", plan_key(ctx.keys["geometry"], c.get("options") or {}), c.get("dialect") or "grbl",
                        c.get("units") or "mm", c.get("wcs") or "G54")
    register(Study("cam_3axis", "study", "CNC, 3-axis",
                   "Toolpaths for a 3-axis mill or router, posted for your controller, read back and run on a stock "
                   "model: gouge, leftover material, collisions and cycle time, measured against the design.",
                   "simulated (stock height field), not proven on a machine", run=run, key=key,
                   inputs=("geometry", "tools", "options", "post"), app="cam", tool="cam_simulate", heavy=True, order=60))
