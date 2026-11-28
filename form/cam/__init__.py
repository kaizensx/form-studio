"""CAM for a 3-axis mill or router, with a stock simulation that measures what the program would do.

    from form import cam
    plan = cam.plan(st, p, {"tools": ["6mm-flat"], "material": "aluminum"})   # operations, moves, speeds and feeds
    out  = cam.post(st, p, "grbl")              # the G-code, read back, re-simulated from the file, measured
    sim  = cam.simulate(st, p)                  # the same measurement again (cached while nothing changed)

What a plan is. For each setup (a tool direction; the fewest come from Wave E's access analysis, form/dfm): the
stock, the work zero, and the operations in order: facing, drilling and helical boring, adaptive clearing, 2.5D
finishing of floors and walls, 3D finishing (parallel and waterline), chamfering and the outline with tabs. Each
operation names its tool and its speed and feed with where each number came from (form/cam/feeds.py).

What the simulation is. The posted file is parsed back as its controller would read it (form/cam/posts.py), its
motion is run on a height-field stock with the tool's real shape (form/cam/sim.py), and the result is measured
against the design's solid: gouge (exact distance of the part's surface into the cutter), leftover (volume and
places), rapids through stock, shank and holder collisions, and the cycle time under the machine's stated limits.
The simulation is the proof and every result says `simulated`. Nothing here talks to a machine.

Release. A program enters a release only when it was asked to (`include`), its simulation is current (the same
geometry, tools, options and post as the head revision), it shows no gouge and no collision, none of its tools,
speeds or feeds is `assumed`, and a person approves. It is labelled "simulated, not proven on a machine" until a
physical result is recorded for that program (`record_physical_result`, kind "machined").

Files, under the project's artifacts/cam/: plan-<key>.json, <name>-<setup>.<ext> (the program),
sim-<key>.json, view-<key>.json (format "form-cam-view/1", what the viewport draws) and target-<key>.npz.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time

import numpy as np

from . import feeds, motion, posts as post_mod, tools as tools_mod

VERSION = 1
VIEW_FORMAT = "form-cam-view/1"
LABEL = post_mod.LABEL
PROVEN = "proven on a machine: a physical result is recorded"
OP_COLOURS = {"face": "#8fb8de", "adaptive": "#e9b860", "finish": "#7bd389", "contour": "#c792ea", "drill": "#ff8a65",
              "bore": "#ffb74d", "chamfer": "#4dd0e1", "raster": "#81c784", "waterline": "#64b5f6", "rapid": "#8a8f98"}
SETUP_UPS = {"+z": (0, 0, 1), "-z": (0, 0, -1), "+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0)}


def _err(msg, hint="", status=400, **kw):
    from ..studio import StudioError
    return StudioError(msg, hint, status=status, **kw)


def H(*a) -> str:
    return hashlib.sha256(json.dumps(a, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---- frames ------------------------------------------------------------------------------------------------------

def frame_for(up) -> np.ndarray:
    """Rows are the setup's X, Y and Z (the tool axis, pointing out of the part) in the design's frame."""
    u = np.asarray(up, float)
    u = u / (np.linalg.norm(u) or 1.0)
    named = {(0, 0, 1): ((1, 0, 0), (0, 1, 0)), (0, 0, -1): ((1, 0, 0), (0, -1, 0)), (1, 0, 0): ((0, 1, 0), (0, 0, 1)),
             (-1, 0, 0): ((0, -1, 0), (0, 0, 1)), (0, 1, 0): ((-1, 0, 0), (0, 0, 1)), (0, -1, 0): ((1, 0, 0), (0, 0, 1))}
    k = tuple(int(round(v)) for v in u)
    if k in named and np.allclose(u, k, atol=1e-9):
        x, y = named[k]
        return np.array([x, y, k], float)
    from ..dfm import geom
    x, y = geom.basis(u)
    if np.dot(np.cross(x, y), u) < 0:
        y = -y
    return np.array([x, y, u], float)


def _up(v):
    if isinstance(v, str):
        k = v.strip().lower().replace("−", "-").replace("setup", "").replace(" ", "")
        if k in SETUP_UPS:
            return SETUP_UPS[k]
        try:
            return tuple(float(x) for x in k.replace("[", "").replace("]", "").split(","))
        except ValueError:
            raise _err(f"Unknown setup “{v}”.", "A setup is +Z, −Z, +X, −X, +Y, −Y or a direction x,y,z.")
    return tuple(float(x) for x in v)


def _setup_name(up) -> str:
    for k, v in SETUP_UPS.items():
        if np.allclose(up, v, atol=1e-9):
            return k.upper().replace("-", "−")
    return "dir " + ",".join(f"{x:g}" for x in np.round(up, 4))


# ---- options -----------------------------------------------------------------------------------------------------

def clean(options: dict | None) -> dict:
    """The options a plan is keyed by: what was given, in a fixed form."""
    o = {k: v for k, v in (options or {}).items() if v not in (None, "", [], {})}
    out: dict = {}
    if "tools" in o:
        t = o["tools"]
        out["tools"] = [t] if isinstance(t, (str, dict)) else list(t)
    for k in ("material", "origin", "zero"):
        if k in o:
            out[k] = str(o[k]).strip().lower()
    for k in ("cell", "sim_cell", "tolerance", "leftover_tolerance", "clearance", "through", "scallop", "chamfer"):
        if k in o:
            out[k] = float(o[k])
    if "machine" in o:
        out["machine"] = dict(o["machine"])
    if "stock" in o:
        s = dict(o["stock"])
        out["stock"] = {k: ([float(x) for x in v] if isinstance(v, (list, tuple)) else float(v)) for k, v in s.items()}
    if "setups" in o:
        s = o["setups"]
        out["setups"] = "auto" if s == "auto" else [list(_up(x)) for x in ([s] if isinstance(s, str) else s)]
    if "ops" in o and o["ops"] != "auto":
        out["ops"] = [({"op": x} if isinstance(x, str) else dict(x)) for x in o["ops"]]
    if "feeds" in o:
        out["feeds"] = {str(k): dict(v) for k, v in dict(o["feeds"]).items()}
    for k in ("cutout", "tabs"):
        if k in o:
            out[k] = o[k]
    return out


# ---- the plan (plain numpy: no kernel, no Studio) ------------------------------------------------------------------

def _stock_box(lo, hi, spec: dict | None) -> tuple[list, list]:
    s = spec or {}
    notes = []
    mxy = float(s.get("margin_xy", 0.0))
    mt = s.get("margin_top")
    if mt is None and "size" not in s:
        mt = 1.0
        notes.append("stock: the part's bounding box with 1 mm on top (assumed; state the blank with stock={...})")
    mt = float(mt or 0.0)
    if "size" in s:
        sx, sy, sz = (float(v) for v in s["size"])
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        if sx < hi[0] - lo[0] - 1e-6 or sy < hi[1] - lo[1] - 1e-6 or sz < hi[2] - lo[2] - 1e-6:
            raise _err("The stock is smaller than the part in this setup.",
                       f"The part needs {hi[0] - lo[0]:.2f} × {hi[1] - lo[1]:.2f} × {hi[2] - lo[2]:.2f} mm.")
        return [cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, lo[2], lo[2] + sz], notes
    return [lo[0] - mxy, hi[0] + mxy, lo[1] - mxy, hi[1] + mxy, lo[2], hi[2] + mt], notes


def auto_ops(job, tools: list, opts: dict) -> list:
    """The operations for a part nobody planned by hand: what the part's shape calls for, with the tools given."""
    from . import paths
    flats = sorted([t for t in tools if t.kind in ("flat", "bull")], key=lambda t: -t.d)
    balls = sorted([t for t in tools if t.kind == "ball"], key=lambda t: -t.d)
    drills = [t for t in tools if t.kind == "drill"]
    chamf = [t for t in tools if t.kind == "chamfer"]
    ops = []
    if not flats:
        raise _err("A plan needs a flat or bull-nose end mill.", "Give tools, for example [\"6mm-flat\"].")
    rough = flats[0]
    if job.zt > job.part_top + 1e-6:
        ops.append({"op": "face", "tool": rough.id})
    holes = paths.vertical_holes(job)
    drilled = set()
    for t in drills:
        mine = [h for h in holes if abs(h["d"] - t.d) <= 0.011]
        if mine:
            ops.append({"op": "drill", "tool": t.id})
            drilled |= {(h["x"], h["y"]) for h in mine}
    for t in flats:
        mine = [h for h in holes if (h["x"], h["y"]) not in drilled and t.d * 1.05 <= h["d"] <= t.d * 1.9]
        if mine:
            ops.append({"op": "bore", "tool": t.id, "holes": mine})
            drilled |= {(h["x"], h["y"]) for h in mine}
    small = [h for h in holes if (h["x"], h["y"]) not in drilled and h["d"] < flats[-1].d * 1.05]
    for h in small:
        job.notes.append(f"hole Ø{h['d']:g} mm at ({h['x']:.2f}, {h['y']:.2f}): no drill of that size and no cutter "
                         "small enough among the tools; it is left, and the simulation reports it as leftover")
    ops.append({"op": "adaptive", "tool": rough.id})
    for t in flats:
        ops.append({"op": "finish", "tool": t.id})
    mask, slope = paths.freeform(job)
    if float(mask.sum()) * job.c ** 2 >= 1.0:
        if balls:
            ops.append({"op": "raster", "tool": balls[0].id, **({"scallop": opts["scallop"]} if "scallop" in opts else {})})
            if float((mask & (slope >= 1.5)).sum()) * job.c ** 2 >= 4.0:
                ops.append({"op": "waterline", "tool": balls[0].id, "min_slope": 1.5})
        else:
            job.notes.append("the part has sloped or curved faces and no ball end mill was given: they are left "
                             "in steps, which the simulation reports as leftover")
    if chamf and opts.get("chamfer"):
        ops.append({"op": "chamfer", "tool": chamf[0].id, "width": float(opts["chamfer"])})
    if job.cutout:
        ops.append({"op": "contour", "tool": flats[0].id, **({"tabs": int(opts["tabs"])} if "tabs" in opts else {})})
    return ops


def make_plan(tri, holes: list | None = None, options: dict | None = None, name: str = "part") -> dict:
    """Plan the machining of a part given as triangles ((n, 3, 3), the design's frame) and its bores.
    Returns the plan: setups, each with its frame, stock, tools, operations and events. JSON-safe."""
    from . import paths
    t0 = time.perf_counter()
    o = clean(options)
    tri = np.asarray(tri, float).reshape(-1, 3, 3)
    if not len(tri):
        raise _err("There is no solid to machine.")
    tools = tools_mod.library(o.get("tools"))
    by_id = {t.id: t for t in tools}
    mach = motion.machine(o.get("machine"))
    ups = o.get("setups") or [[0, 0, 1]]
    if ups == "auto":
        ups = [[0, 0, 1]]
    tol = float(o.get("tolerance", 0.05))
    plan = {"version": VERSION, "name": name, "label": LABEL, "evidence": "planned; nothing here is simulated yet",
            "options": o, "tolerance_mm": tol, "material": o.get("material"), "machine": mach,
            "tools": [t.public() for t in tools], "setups": [], "notes": [], "assumed": []}
    if o.get("material") and not feeds.material(o["material"]):
        plan["notes"].append(f"material “{o['material']}” has no row in the speeds and feeds table: every speed and "
                             "feed is assumed until given (feeds={tool_id: {rpm, feed, plunge}})")
    for t in tools:
        if t.provenance == "assumed":
            plan["assumed"].append(f"tool {t.id}: its flute length, stick-out or holder was not stated")
    smallest = min((t.r for t in tools if t.kind in ("flat", "bull", "ball")), default=min(t.r for t in tools))
    through_done: list = []                            # holes an earlier setup took through (design frame)
    for si, up in enumerate(ups):
        Rm = frame_for(up)
        ts = tri @ Rm.T
        lo, hi = ts.reshape(-1, 3).min(axis=0), ts.reshape(-1, 3).max(axis=0)
        spec = o.get("stock")
        if si > 0 and "size" not in (spec or {}):      # the extra on top is faced off in the first setup only
            spec = {**(spec or {}), "margin_top": 0.0}
        box, snotes = _stock_box(lo, hi, spec)
        origin_kind = o.get("origin", "corner")
        zero = o.get("zero", "top")
        if origin_kind not in ("corner", "center", "centre"):
            raise _err("origin is corner (the stock's front-left corner) or center.")
        ox, oy = (box[0], box[2]) if origin_kind == "corner" else ((box[0] + box[1]) / 2, (box[2] + box[3]) / 2)
        oz = box[5] if zero == "top" else box[4]
        org = np.array([ox, oy, oz])
        tw = ts - org
        boxw = [box[0] - ox, box[1] - ox, box[2] - oy, box[3] - oy, box[4] - oz, box[5] - oz]
        hw = []
        precut = []
        for h in holes or []:
            ax = Rm @ np.asarray(h["axis"], float)
            at = Rm @ np.asarray(h["at"], float) - org
            if abs(abs(ax[2]) - 1) < 1e-6 and any(abs(d["d"] - h["d"]) < 1e-6 and np.linalg.norm(np.asarray(d["at"]) - np.asarray(h["at"])) < 1e-4
                                                 for d in through_done):
                precut.append({"at": [float(at[0]), float(at[1])], "d": float(h["d"])})
                continue
            hw.append({"d": h["d"], "depth": h["depth"], "axis": ax.tolist(), "at": at.tolist(), "design_at": list(h["at"])})
        if precut:
            snotes.append(f"{len(precut)} hole(s) an earlier setup drilled through are taken as open here")
        ext = max(boxw[1] - boxw[0], boxw[3] - boxw[2])
        pad = max(t.d for t in tools) + 2.0
        cell = float(o.get("cell") or min(0.4, max(0.1, smallest / 10)))
        cell = max(cell, (ext + 2 * pad) / 900.0)
        cutout = bool(o["cutout"]) if "cutout" in o else float((o.get("stock") or {}).get("margin_xy", 0)) > 1e-9 or \
            ("size" in (o.get("stock") or {}) and (box[1] - box[0] > hi[0] - lo[0] + 1e-6 or box[3] - box[2] > hi[1] - lo[1] + 1e-6))
        thr = float(o.get("through", 0.3))
        job = paths.Job((tw[:, 0], tw[:, 1], tw[:, 2]), boxw, cell, pad, hw, clearance=float(o.get("clearance", 5.0)),
                        cutout=cutout, through=thr, precut=precut)
        ops_in = o.get("ops") or auto_ops(job, tools, o)
        events: list = []
        ops_out = []
        cur_tool, cur_rpm = None, None
        max_drill = 0.0
        for n, spec in enumerate(ops_in, 1):
            kind = spec.get("op")
            if kind not in paths.OPS:
                raise _err(f"Unknown operation “{kind}”.", "Operations: " + ", ".join(paths.OPS) + ".")
            tid = spec.get("tool")
            if tid is None:
                tool = next((t for t in tools if t.kind in paths.KINDS[kind]), None)
            else:
                tool = by_id.get(str(tid))
                if tool is None and isinstance(tid, str):
                    try:
                        tool = by_id.get(tools_mod.make(tid).id)
                    except Exception:                  # noqa: BLE001 - not a tool name: reported just below
                        tool = None
            if tool is None:
                raise _err(f"Operation {n} ({kind}) has no tool.", f"It takes a {' or '.join(paths.KINDS[kind])} tool; "
                           "tools: " + ", ".join(by_id) + ".")
            if tool.kind not in paths.KINDS[kind]:
                raise _err(f"A {tool.kind} tool cannot do “{kind}”.", f"It takes a {' or '.join(paths.KINDS[kind])} tool.")
            given = {**(o.get("feeds", {}).get(tool.id) or {}), **(o.get("feeds", {}).get(kind) or {}), **(spec.get("feeds") or {})}
            ae = float(spec.get("stepover") or 0.2 * tool.d) if kind == "adaptive" else None
            fs = feeds.for_op(tool, o.get("material"), mach, given, ae=ae, thin=kind == "adaptive")
            prm = {k: v for k, v in spec.items() if k not in ("op", "tool", "feeds")}
            res = paths.OPS[kind](job, tool, prm, fs)
            ev = res["events"]
            info = dict(res["info"])
            rec = {"n": n, "op": kind, "label": paths.LABELS[kind], "tool": tool.id, "T": tool.number,
                   "feeds": fs, "info": info, "moves": len(ev)}
            if not ev:
                rec["skipped"] = info.get("skipped", "nothing to cut")
                ops_out.append(rec)
                continue
            if not info.pop("applied", False):
                job.apply([("tool", tool.number)] + ev, {tool.number: tool})
            if kind == "drill":
                max_drill = max(max_drill, tool.cone_h)
            if kind in ("drill", "bore"):
                for hd in info.get("holes", []):
                    src = next((h for h in hw if abs(h["at"][0] - hd["at"][0]) < 2e-3 and abs(h["at"][1] - hd["at"][1]) < 2e-3), None)
                    if hd.get("through") and src is not None:
                        through_done.append({"d": src["d"], "at": src["design_at"]})
            events.append(("op", n, f"{paths.LABELS[kind]}, {tool.id}"))
            if cur_tool != tool.number:
                if cur_tool is not None:
                    events.append(("stop",))
                events.append(("tool", tool.number))
                events.append(("spindle", fs["rpm"]))
                cur_tool, cur_rpm = tool.number, fs["rpm"]
            elif cur_rpm != fs["rpm"]:
                events.append(("spindle", fs["rpm"]))
                cur_rpm = fs["rpm"]
            events += ev
            for a in fs["assumed"]:
                plan["assumed"].append(f"operation {n} ({kind}, {tool.id}): {a}")
            ops_out.append(rec)
        if events:
            events += [("stop",), ("home",), ("end",)]
        plan["setups"].append({
            "n": si + 1, "name": _setup_name(up), "up": [float(v) for v in up],
            "frame": {"R": Rm.tolist(), "origin": org.tolist(),
                      "text": f"X0 Y0 at the stock's {'front-left corner' if origin_kind == 'corner' else 'centre'}, "
                              f"Z0 at the stock's {'top' if zero == 'top' else 'underside'}; tool axis {_setup_name(up)} of the design"},
            "stock": {"box": [round(v, 6) for v in boxw], "size": [round(boxw[1] - boxw[0], 4), round(boxw[3] - boxw[2], 4), round(boxw[5] - boxw[4], 4)],
                      "cutout": cutout},
            "cell_mm": cell, "clearance_z": job.zc, "through_mm": round(thr + max_drill, 4),
            "ops": ops_out, "events": [list(e) for e in events], "intended": job.intended, "precut": precut,
            "notes": snotes + job.notes})
    if len(plan["setups"]) > 1 and not any("earlier setup removed" in n for n in plan["notes"]):
        plan["notes"].append("each setup is planned and simulated from the blank as that side sees it: of what an "
                             "earlier setup removed, only holes drilled or bored through are carried into a later one")
    plan["assumed"] = sorted(set(plan["assumed"]))
    plan["choices"] = ["stepovers, stepdowns, allowances, the 3° helix and the peck rule are rules of thumb where not "
                       "given per operation; they shape the path, and the simulation measures the result"]
    if mach.get("assumed"):
        plan["machine_assumed"] = "machine limits not stated (" + ", ".join(mach["assumed"]) + "): the cycle time uses the defaults"
    plan["seconds"] = round(time.perf_counter() - t0, 2)
    return plan


def plan_summary(pl: dict) -> dict:
    """The plan without its moves, for MCP and the CLI."""
    out = {k: v for k, v in pl.items() if k != "setups"}
    out["setups"] = []
    for s in pl["setups"]:
        t = {k: v for k, v in s.items() if k not in ("events", "intended")}
        t["moves"] = len(s["events"])
        t["edge_breaks"] = len(s.get("intended") or [])
        ops = []
        for o in s["ops"]:
            info = dict(o["info"])
            for k in ("levels", "holes"):
                if isinstance(info.get(k), list) and len(info[k]) > 8:
                    info[k + "_more"] = len(info[k]) - 8
                    info[k] = info[k][:8]
            ops.append({**o, "info": info})
        t["ops"] = ops
        out["setups"].append(t)
    out["release_blockers"] = pl.get("assumed", [])
    return out


def options_from_cli(tools: list, material: str, sets: list, options_json: str = "") -> dict:
    """Plan options from the command line: --tool (repeatable), --material, --set key=value and --options JSON."""
    o: dict = json.loads(options_json) if options_json else {}
    if tools:
        o["tools"] = [json.loads(t) if t.strip().startswith("{") else t for t in tools]
    if material:
        o["material"] = material
    for kv in sets or []:
        k, _, v = kv.partition("=")
        k, v = k.strip(), v.strip()
        try:
            val = json.loads(v)
        except ValueError:
            val = v
        if "." in k:                                   # machine.rapid=5000, stock.margin_xy=6
            a, b = k.split(".", 1)
            o.setdefault(a, {})[b] = val
        elif k == "setups" and isinstance(val, str) and val != "auto":
            o[k] = [x for x in val.split(";") if x]
        else:
            o[k] = val
    return o


def events_of(setup: dict) -> list:
    return [tuple(e) for e in setup["events"]]


def tools_of(plan: dict) -> dict:
    out = {}
    for t in plan["tools"]:
        tt = tools_mod.make({k: v for k, v in t.items() if k != "label"})
        out[tt.number] = tt
    return out


def post_setup(plan: dict, setup: dict, dialect: str = "grbl", units: str = "mm", wcs: str = "G54",
               line_numbers: bool = False, label: str = LABEL) -> str:
    tools = {n: t.label + (f", flute {t.flute_l:g}, stick-out {t.length:g}" if t.length else "") for n, t in tools_of(plan).items()}
    used = {e[1] for e in setup["events"] if e[0] == "tool"}
    sz = setup["stock"]["size"]
    header = [f"setup {setup['n']} ({setup['name']}): {setup['frame']['text']}",
              f"stock {sz[0]:g} x {sz[1]:g} x {sz[2]:g} mm" + (f", material {plan['material']}" if plan.get("material") else "")]
    return post_mod.post(events_of(setup), dialect, name=plan.get("name", "program"), units=units, wcs=wcs,
                         tools={n: t for n, t in tools.items() if n in used}, mach=plan["machine"], header=header,
                         line_numbers=line_numbers, label=label)


def simulate_setup(plan: dict, setup: dict, tri, gcode: str | None = None, dialect: str = "grbl",
                   cell: float | None = None, units: str = "mm", keep_arrays: bool = False) -> dict:
    """Simulate one setup and measure it against the part. With gcode, the motion is what the file says, read back
    as its controller reads it; without, the plan's own events (then `source` says so: not a check of a file)."""
    from . import sim
    t0 = time.perf_counter()
    tools = tools_of(plan)
    Rm, org = np.asarray(setup["frame"]["R"], float), np.asarray(setup["frame"]["origin"], float)
    tw = np.asarray(tri, float).reshape(-1, 3, 3) @ Rm.T - org
    tris = (tw[:, 0], tw[:, 1], tw[:, 2])
    out: dict = {"setup": setup["n"], "name": setup["name"]}
    if gcode is not None:
        parsed = post_mod.parse(gcode, dialect)
        events = parsed["events"]
        same, why = post_mod.same_motion(events_of(setup), events, parsed["units"],
                                         post_mod.DIALECTS[post_mod.dialect_id(dialect)]["canned"])
        out["source"] = f"the posted {post_mod.DIALECTS[post_mod.dialect_id(dialect)]['label']} file, read back"
        out["gcode"] = {"lines": parsed["lines"], "units": parsed["units"], "wcs": parsed["wcs"], "codes": parsed["codes"],
                        "problems": parsed["problems"], "sha256": hashlib.sha256(gcode.encode()).hexdigest(),
                        "same_motion_as_plan": same, **({"difference": why} if not same else {})}
    else:
        events = events_of(setup)
        out["source"] = "the plan's own moves (no file was checked)"
    segs = motion.flatten(events)
    box = setup["stock"]["box"]
    rcut = max((t.r for t in tools.values()), default=3.0)
    pad = rcut + 2.0
    c = float(cell or min(0.25, max(0.05, min(t.r for t in tools.values()) / 4)))
    ext = max(box[1] - box[0], box[3] - box[2]) + 2 * pad
    c = max(c, ext / 1500.0)
    lo = np.array([box[0] - pad, box[2] - pad])
    nx, ny = int(math.ceil((box[1] - box[0] + 2 * pad) / c)), int(math.ceil((box[3] - box[2] + 2 * pad) / c))
    xc = lo[0] + (np.arange(nx) + 0.5) * c
    yc = lo[1] + (np.arange(ny) + 0.5) * c
    foot = ((xc >= box[0] - 1e-9) & (xc <= box[1] + 1e-9))[:, None] & ((yc >= box[2] - 1e-9) & (yc <= box[3] + 1e-9))[None, :]
    stock = sim.Stock(lo, c, (nx, ny), np.where(foot, box[5], box[4]), box[4])
    sim.open_holes(stock, setup.get("precut"))
    target = sim.target_heights(tris, lo, c, (nx, ny))
    diag = float(np.linalg.norm(tw.reshape(-1, 3).max(axis=0) - tw.reshape(-1, 3).min(axis=0)))
    samples = sim.surface_samples(tris, max(0.3, diag / 250.0))
    tol = float(plan.get("tolerance_mm", 0.05))
    res = sim.simulate(segs, tools, stock, target, samples, tol=tol,
                       leftover_tol=float(plan["options"].get("leftover_tolerance", tol)),
                       intended=setup.get("intended"), through=float(setup.get("through_mm", 1.0)))
    res["sample_spacing_mm"] = round(samples[3], 4)
    ct = motion.cycle_time(segs, plan["machine"])
    tcum = ct.pop("t")
    ct["seconds"], ct["feed_s"], ct["rapid_s"] = (round(ct[k], 3) for k in ("seconds", "feed_s", "rapid_s"))
    res["cycle_time"] = {**ct, "evidence": "simulated", "text": _hms(ct["seconds"]),
                         "tool_changes": max(0, len(segs["tools"]) - 1)}
    names = {op["n"]: op for op in setup["ops"]}
    per = []
    for n, v in sorted(res.pop("per_op").items()):
        op = names.get(n, {})
        per.append({"n": n, "op": op.get("op"), "label": op.get("label"), "tool": op.get("tool"),
                    "seconds": round(ct["per_op"].get(n, 0.0), 3), **v})
    res["ops"] = per
    del res["cycle_time"]["per_op"]
    if gcode is not None:
        if out["gcode"]["problems"]:
            res["fails"].append(f"{len(out['gcode']['problems'])} thing(s) the controller would not accept: " + out["gcode"]["problems"][0])
        if not out["gcode"]["same_motion_as_plan"]:
            res["fails"].append("the file's motion is not the plan's: " + out["gcode"].get("difference", ""))
        res["verdict"] = "fail" if res["fails"] else "pass"
    arrays = {k: res.pop(k) for k in ("_left", "_over", "_domain", "_pen") if k in res}
    out.update(res)
    out["label"] = LABEL
    out["seconds"] = round(time.perf_counter() - t0, 2)
    if keep_arrays:
        out["_arrays"] = {**arrays, "Z": stock.Z, "lo": lo, "cell": c, "segs": segs, "t": tcum, "samples": samples[0]}
    return out


def _hms(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


# ---- the viewport's data -------------------------------------------------------------------------------------------

def _b64(a, dtype) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode()


def view(plan: dict, sims: list) -> dict:
    """What the viewport draws, in the design's frame.

    {"format": "form-cam-view/1", "label", "setups": [{"n", "name", "frame",
       "toolpaths": [{"op", "label", "tool", "kind": "feed" | "rapid", "color", "count", "positions": base64 float32
                      (count, 2, 3) segment ends, "t": base64 float32 (count) seconds at each segment's end}],
       "stock": {"positions", "indices", "colors", "status" (base64 float32 xyz, uint32, uint8 RGBA, uint8 per
                 vertex: 0 cut to size, 1 leftover, 2 gouge), "cell_mm", "grid"},
       "marks": [{"at", "kind": "gouge" | "leftover" | "collision", "label"}]}], "legend"}"""
    out = {"format": VIEW_FORMAT, "label": LABEL, "evidence": "simulated", "name": plan.get("name"), "setups": [],
           "legend": {"title": "CNC, 3-axis", "ops": [{"op": k, "color": v} for k, v in OP_COLOURS.items()],
                      "stock": [{"status": 0, "color": "#d8d3c8", "label": "cut to size"},
                                {"status": 1, "color": "#e9b860", "label": "leftover"},
                                {"status": 2, "color": "#ff6f51", "label": "gouge"}]}}
    cols = np.array([[216, 211, 200, 255], [233, 184, 96, 255], [255, 111, 81, 255]], np.uint8)
    for setup, s in zip(plan["setups"], sims):
        ar = s.get("_arrays")
        Rm, org = np.asarray(setup["frame"]["R"], float), np.asarray(setup["frame"]["origin"], float)

        def back(p):
            return (np.asarray(p, float) + org) @ Rm
        entry = {"n": setup["n"], "name": setup["name"], "frame": setup["frame"], "toolpaths": [], "marks": []}
        if ar is not None:
            segs = ar["segs"]
            kinds = {op["n"]: op for op in setup["ops"]}
            for o in np.unique(segs["op"]):
                for kd, nm in ((motion.FEED, "feed"), (motion.RAPID, "rapid")):
                    m = (segs["op"] == o) & (segs["kind"] == kd)
                    if not m.any():
                        continue
                    P = np.stack([back(segs["a"][m]), back(segs["b"][m])], axis=1)
                    op = kinds.get(int(o), {})
                    entry["toolpaths"].append({"op": int(o), "kind": nm, "label": op.get("label"), "tool": op.get("tool"),
                                               "operation": op.get("op"),
                                               "color": OP_COLOURS["rapid"] if nm == "rapid" else OP_COLOURS.get(op.get("op"), "#cccccc"),
                                               "count": int(m.sum()), "positions": _b64(P, np.float32), "t": _b64(ar["t"][m], np.float32)})
            Z, c, lo = ar["Z"], ar["cell"], ar["lo"]
            k = max(1, int(math.ceil(max(Z.shape) / 256)))
            Zs = Z[::k, ::k]
            st = np.zeros(Z.shape, np.uint8)
            st[ar["_left"] > s["leftover_tolerance_mm"]] = 1
            st[ar["_over"] > s["tolerance_mm"]] = 2
            if k > 1:                                   # a coarse vertex takes the worst status of its block
                nxk, nyk = Zs.shape
                padded = np.zeros((nxk * k, nyk * k), np.uint8)
                padded[:Z.shape[0], :Z.shape[1]] = st
                st = padded.reshape(nxk, k, nyk, k).max(axis=(1, 3))
            nxs, nys = Zs.shape
            gx, gy = np.meshgrid(lo[0] + (np.arange(nxs) * k + 0.5) * c, lo[1] + (np.arange(nys) * k + 0.5) * c, indexing="ij")
            V = back(np.stack([gx.ravel(), gy.ravel(), Zs.ravel()], axis=1))
            idx = np.arange(nxs * nys).reshape(nxs, nys)
            a, b, cc, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
            I = np.concatenate([np.stack([a, b, cc], 1), np.stack([a, cc, d], 1)])
            entry["stock"] = {"positions": _b64(V, np.float32), "indices": _b64(I, np.uint32),
                              "colors": _b64(cols[st.ravel()], np.uint8), "status": _b64(st.ravel(), np.uint8),
                              "cell_mm": c * k, "grid": [int(nxs), int(nys)], "vertices": int(nxs * nys),
                              "what": "the top of the remaining stock over a grid, along the tool axis"}
        for g in (s.get("gouge") or {}).get("marks", []):
            entry["marks"].append({"at": back(g["at"]).round(3).tolist(), "kind": "gouge",
                                   "label": f"gouge {g['depth_mm']:g} mm (operation {g['op']})"})
        for r in (s.get("leftover") or {}).get("regions", [])[:12]:
            entry["marks"].append({"at": back(r["at"]).round(3).tolist(), "kind": "leftover",
                                   "label": f"leftover up to {r['max_mm']:g} mm, {r['volume_mm3']:g} mm³"})
        for cl in s.get("collisions", [])[:12]:
            entry["marks"].append({"at": back(cl["at"]).round(3).tolist(), "kind": "collision",
                                   "label": f"{cl['kind']} collision, {cl['depth_mm']:g} mm into stock (operation {cl['op']})"})
        out["setups"].append(entry)
    return out


def summary_sim(sims: list) -> dict:
    """The measurements of every setup in one place."""
    fails = [f"setup {s['setup']}: {f}" for s in sims for f in s.get("fails", [])]
    g = [s["gouge"]["max_mm"] for s in sims if s.get("gouge", {}).get("max_mm") is not None]
    return {"verdict": "fail" if fails else "pass", "fails": fails, "evidence": "simulated", "label": LABEL,
            "gouge_max_mm": max(g) if g else None,
            "leftover_mm3": round(sum(s["leftover"]["above_tolerance_mm3"] for s in sims), 3),
            "leftover_max_mm": max((s["leftover"]["max_mm"] for s in sims), default=0.0),
            "left": any(s.get("left") for s in sims),
            "rapid_collisions": sum(s["rapid_collisions"] for s in sims),
            "holder_collisions": sum(s["holder_collisions"] for s in sims),
            "removed_mm3": round(sum(s["removed_mm3"] for s in sims), 2),
            "cycle_time_s": round(sum(s["cycle_time"]["seconds"] for s in sims), 1),
            "cycle_time": _hms(sum(s["cycle_time"]["seconds"] for s in sims))}


from . import project as _project  # noqa: E402  (the Studio side: artifacts, keys, the release gate, the Bench)

bench_status, gate, plan, post, record = _project.bench_status, _project.gate, _project.plan, _project.post, _project.record
register_studies, simulate, status = _project.register_studies, _project.simulate, _project.status
