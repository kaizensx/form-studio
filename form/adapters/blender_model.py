"""Blender as a modelling editor: an agent's declarative op list, run by Form's fixed runner, back as cage data.

The agent never sends Blender code. It sends a list of ops (OP_SCHEMA below); validate_ops() checks every op, field,
type and range here, before Blender starts, and refuses anything unknown or malformed. The checked list goes to
blender_ops.py, a fixed script that maps each op name to its own function. Nothing the agent wrote is executed or
evaluated, by this module or by the runner.

Each op streams a preview: the runner writes the cage at subdivision level 2 to a stage file and prints
`FORM_STAGE <path.bin>`; run_ops() turns it into the build stream's stage event (meshsource.stage_event) and hands it
to on_stage. Integration hook: pass on_stage=Studio._draft_sink(draft, name) and the preview lands in
.cache/drafts/<draft>.json, which /api/drafts serves and Store.showStage draws, exactly like a kernel build's stages.

The result is cage data (meshsource.CageData: V, F, creases, regions). Blender is an editor, never the geometry
authority: the cage goes into a design's source (CageData.literal()) and a FeatureDesign feature builds it with
form/craft/subd.py. An op list is stored under a key (op_key: the canonical ops, the runner version and Blender's
major.minor), and replaying it gives the same cage (CageData.hash(): rounded points and faces).

How Blender is run:
  * `blender -b --factory-startup -noaudio -Y` (-Y: never auto-run scripts inside .blend files), plus
    `--offline-mode` on Blender 4.2 or newer (it keeps Blender's own online features, such as extension listings, off).
  * A scrubbed environment (PATH, a temporary HOME and TMPDIR, locale; no PYTHONPATH, no user Blender config).
  * A new temporary working directory per run, removed afterwards.
  * A watchdog kills the whole process group after the timeout. Nothing is written to a project before Blender has
    finished, so a killed or failed run leaves the project exactly as it was.

Not enforced: OS-level network isolation. Blender runs with the user's network access; --offline-mode is Blender's
own switch, not a sandbox, and the runner's lack of network imports is checked by a test, not by the OS.
"""
from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .. import compat, meshsource
from .blender import DOWNLOAD_URL, BlenderFailed, BlenderMissing, resolve, tail, version  # noqa: F401

RUNNER = Path(__file__).with_name("blender_ops.py")
RUNNER_VERSION = 1                    # blender_ops.RUNNER_VERSION; part of every op key
PREVIEW_LEVELS = 2
TIMEOUT_S = 120.0
MAX_OPS = 200
MAX_POINTS = 50_000
MAX_JSON = 4_000_000                  # bytes of the op list as JSON
COORD = 1e5                           # mm: no coordinate, offset or size beyond 100 m
BRUSHES = ("draw", "inflate", "smooth", "flatten", "pinch", "grab")
PRIMITIVES = ("cube", "quad_sphere", "plane", "cylinder")


class OpError(ValueError):
    """An op list that is refused before Blender starts. .index is the op at fault (None: the list itself)."""

    def __init__(self, message, hint="", index=None):
        super().__init__(message)
        self.hint, self.index = hint, index

    def public(self) -> dict:
        return {"message": str(self), "hint": self.hint, "op": self.index}


# ---- the op schema -----------------------------------------------------------------------------------------------

OP_SCHEMA = {
    "cage_new": "First op, exactly once. {primitive: cube|quad_sphere|plane|cylinder, size [x,y,z] (cube, plane), "
                "radius, height, segments 1..64, center [x,y,z]} or {quads: {V: [[x,y,z]...], F: [[i,j,k,l]...]}} "
                "(polygons of 3..64 points; quads give the cleanest surface).",
    "extrude_region": "{faces: <faces>, offset: mm along the region's normal} or {faces, vector: [x,y,z]}.",
    "loop_cut": "{edge: [a, b] (two joined points), cuts: 1..32}: cuts the ring of quads across that edge.",
    "move": "{verts: <points>, by: [dx,dy,dz]} and/or {scale: [sx,sy,sz]} about the selection's centre.",
    "crease": "{edges: [[a,b], ...]} or {region_boundary: name}, value 0..1 (1 = sharp).",
    "name_region": "{name: [a-z][a-z0-9_]*, faces: <faces>}: a named face set that later ops, creases and CAD "
                   "features (split, cut) can target.",
    "mirror": "{axis: x|y|z, clip: true (cut away the negative half first), merge: mm weld distance}.",
    "geonodes_array": "{count: 2..256, offset: [x,y,z]}: copies of the whole cage (Geometry Nodes).",
    "geonodes_scatter": f"{{count: 1..{2000}, seed: int, item_size: mm, scale: [min, max]}}: small cubes scattered "
                        "on the faces (Geometry Nodes, random by seed; the count is an expectation).",
    "sculpt_ops": f"{{strokes: [{{brush: {'|'.join(BRUSHES)}, center: [x,y,z], radius: mm, strength: -1..1, "
                  "direction: [x,y,z] (grab), iterations: 1..20 (smooth)}, ...]}} up to 64 strokes: Form's own "
                  "deterministic brushes on the cage points.",
    "remesh": "{mode: voxel, voxel_size: mm} or {mode: quad, target_faces: 6..200000, seed: int} (QuadriFlow). "
              "Automatic retopology: regions and creases do not survive it.",
    "bevel": "{edges: <edges>, width: mm, segments: 1..8, profile: 0.05..1 (0.5 round), crease: 0..1 (on the bevel's "
             "borders), name: region for the bevel faces}: chamfers or rounds edges in the cage.",
    "support_loops": "{edges: <edges>, distance: mm}: a holding loop on each side of the edges, the corner kept, so "
                     "they stay tight after subdivision.",
    "inset": "{faces: <faces>, thickness: mm, depth: mm (negative = recess), individual: false, crease: 0..1, "
             "name: region for the inner faces}: a border inside the faces, then in or out.",
    "panel_line": "{edges: <edges>, width: mm, depth: mm into the surface, crease: 0..1 (the lips), name}: a V groove "
                  "along an edge path, sharp at the bottom.",
    "trim_strip": "{edges: <edges>, width: mm, height: mm out of the surface, crease: 0..1, name}: a raised band "
                  "along an edge path (edge guards, metal trim).",
    "solidify": "{thickness: mm, offset: -1..1 (-1 inward), rim_crease: 0..1}: gives a skin thickness; an open "
                "skin gets a closed rim.",
    "bridge": "{faces_a: <faces>, faces_b: <faces>, cuts: 0..32, twist: int, name}: removes two disc-shaped face "
              "sets and joins their borders with a tube (a handle or a tunnel).",
    "kit_place": "{part: a kit part, params: {..}, faces: <faces> with mode each|center, or at: [[x,y,z], ...] with "
                 "normal: [x,y,z] or snap: true; scale: number or [sx,sy,sz], rotation: degrees about the normal, "
                 "offset: mm along it, name}: copies of an original parametric detail part (form.game.kit), +Z on "
                 "the surface normal; each copy is its own closed shell.",
}
SELECTORS = ("<faces>: {all: true} | {region: name} | {indices: [face, ...]} | {normal: [x,y,z], within_deg: 0..180}. "
             "<points>: any <faces> (its points) | {indices: [point, ...]} | {box: [[x0,y0,z0], [x1,y1,z1]]}. "
             "<edges>: [[a, b], ...] | {pairs: [[a, b], ...]} | {path: [p0, p1, ...], closed: false} | "
             "{region_boundary: name} | {box: [[x0,y0,z0], [x1,y1,z1]]} (edges with both ends inside) | "
             "{angle_deg: 1..179} (edges sharper than that) | {creased: true}. "
             "Any op but cage_new takes high_only: true: it changes only the bake source (the high-poly cage), "
             "never the low-poly LODs; once one op is high_only, every later op must be too.")
HIGH_ONLY_RULE = "Put the high_only ops last: detail for the bake goes on top of the finished low-poly cage."
MAX_PLACE = 512                       # kit copies per kit_place op


def _num(v, where, lo=-COORD, hi=COORD, integer=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise OpError(f"{where} must be a number, not {type(v).__name__}.")
    if integer and (not float(v).is_integer()):
        raise OpError(f"{where} must be a whole number.")
    if not math.isfinite(v) or not lo <= v <= hi:
        raise OpError(f"{where} = {v} is outside {lo:g}..{hi:g}.")
    return int(v) if integer else float(v)


def _vec(v, where, lo=-COORD, hi=COORD):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise OpError(f"{where} must be [x, y, z].")
    return [_num(x, f"{where}[{i}]", lo, hi) for i, x in enumerate(v)]


def _ints(v, where, cap=MAX_POINTS * 4):
    if not isinstance(v, (list, tuple)) or not v or len(v) > cap:
        raise OpError(f"{where} must be a non-empty list of at most {cap} indices.")
    return [_num(x, f"{where}[]", 0, 10_000_000, integer=True) for x in v]


def _name(v, where):
    if not isinstance(v, str) or not meshsource.REGION_NAME.fullmatch(v):
        raise OpError(f"{where} must be a name like “lid_rim” (lower case letters, digits, _; up to 32).")
    return v


def _keys(o, allowed, where):
    extra = set(o) - set(allowed) - {"op"}
    if extra:
        raise OpError(f"{where} does not take {', '.join(sorted(extra))}. It takes: {', '.join(allowed)}.")


def _faces(s, where):
    if not isinstance(s, dict) or len(s) == 0:
        raise OpError(f"{where} must be a face selection. {SELECTORS}")
    if s.get("all") is True and len(s) == 1:
        return {"all": True}
    if "region" in s and len(s) == 1:
        return {"region": _name(s["region"], f"{where}.region")}
    if "indices" in s and len(s) == 1:
        return {"indices": _ints(s["indices"], f"{where}.indices")}
    if "normal" in s and set(s) <= {"normal", "within_deg"}:
        n = _vec(s["normal"], f"{where}.normal")
        if math.hypot(*n) < 1e-9:
            raise OpError(f"{where}.normal must not be zero.")
        return {"normal": n, "within_deg": _num(s.get("within_deg", 1.0), f"{where}.within_deg", 0, 180)}
    raise OpError(f"{where} is not a face selection. {SELECTORS}")


def _points(s, where):
    if isinstance(s, dict) and "indices" in s and len(s) == 1:
        return {"indices": _ints(s["indices"], f"{where}.indices")}
    if isinstance(s, dict) and "box" in s and len(s) == 1:
        b = s["box"]
        if not isinstance(b, (list, tuple)) or len(b) != 2:
            raise OpError(f"{where}.box must be [[x0,y0,z0], [x1,y1,z1]].")
        return {"box": [_vec(b[0], f"{where}.box[0]"), _vec(b[1], f"{where}.box[1]")]}
    return _faces(s, where)


def _edge(e, where):
    if not isinstance(e, (list, tuple)) or len(e) != 2:
        raise OpError(f"{where} must be [a, b], two point indices.")
    a, b = (_num(x, where, 0, 10_000_000, integer=True) for x in e)
    if a == b:
        raise OpError(f"{where} joins a point to itself.")
    return [a, b]


def _check_one(i, o) -> dict:
    w = f"op {i} ({o.get('op')})"
    k = o["op"]
    if k == "cage_new":
        if "quads" in o:
            _keys(o, ("quads", "center"), w)
            q = o["quads"]
            if not isinstance(q, dict) or set(q) != {"V", "F"}:
                raise OpError(f"{w}: quads must be {{V: [[x,y,z]...], F: [[i,j,k,l]...]}}.")
            if not isinstance(q["V"], list) or not 3 <= len(q["V"]) <= MAX_POINTS:
                raise OpError(f"{w}: quads.V must hold 3..{MAX_POINTS} points.")
            V = [_vec(p, f"{w}: quads.V[{j}]") for j, p in enumerate(q["V"])]
            if not isinstance(q["F"], list) or not q["F"] or len(q["F"]) > MAX_POINTS:
                raise OpError(f"{w}: quads.F must hold 1..{MAX_POINTS} faces.")
            F = []
            for j, f in enumerate(q["F"]):
                if not isinstance(f, list) or not 3 <= len(f) <= 64:
                    raise OpError(f"{w}: quads.F[{j}] must list 3..64 point indices.")
                f = [_num(x, f"{w}: quads.F[{j}]", 0, len(V) - 1, integer=True) for x in f]
                if len(set(f)) != len(f):
                    raise OpError(f"{w}: quads.F[{j}] repeats a point.")
                F.append(f)
            out = {"op": k, "quads": {"V": V, "F": F}}
        else:
            _keys(o, ("primitive", "size", "radius", "height", "segments", "center"), w)
            if o.get("primitive") not in PRIMITIVES:
                raise OpError(f"{w}: primitive must be one of {', '.join(PRIMITIVES)} (or give quads).")
            out = {"op": k, "primitive": o["primitive"]}
            if "size" in o:
                out["size"] = _vec(o["size"], f"{w}.size", 1e-4, COORD)
            for f in ("radius", "height"):
                if f in o:
                    out[f] = _num(o[f], f"{w}.{f}", 1e-4, COORD)
            if "segments" in o:
                out["segments"] = _num(o["segments"], f"{w}.segments", 1, 64, integer=True)
        if "center" in o:
            out["center"] = _vec(o["center"], f"{w}.center")
        return out
    if k == "extrude_region":
        _keys(o, ("faces", "offset", "vector"), w)
        out = {"op": k, "faces": _faces(o.get("faces"), f"{w}.faces")}
        if ("offset" in o) == ("vector" in o):
            raise OpError(f"{w} needs offset (mm along the normal) or vector, not both.")
        if "offset" in o:
            out["offset"] = _num(o["offset"], f"{w}.offset")
        else:
            out["vector"] = _vec(o["vector"], f"{w}.vector")
        return out
    if k == "loop_cut":
        _keys(o, ("edge", "cuts"), w)
        return {"op": k, "edge": _edge(o.get("edge"), f"{w}.edge"),
                "cuts": _num(o.get("cuts", 1), f"{w}.cuts", 1, 32, integer=True)}
    if k == "move":
        _keys(o, ("verts", "by", "scale"), w)
        if "by" not in o and "scale" not in o:
            raise OpError(f"{w} needs by and/or scale.")
        out = {"op": k, "verts": _points(o.get("verts"), f"{w}.verts")}
        if "by" in o:
            out["by"] = _vec(o["by"], f"{w}.by")
        if "scale" in o:
            out["scale"] = _vec(o["scale"], f"{w}.scale", -1e3, 1e3)
        return out
    if k == "crease":
        _keys(o, ("edges", "region_boundary", "value"), w)
        out = {"op": k, "value": _num(o.get("value", 1.0), f"{w}.value", 0, 1)}
        if ("edges" in o) == ("region_boundary" in o):
            raise OpError(f"{w} needs edges or region_boundary.")
        if "edges" in o:
            if not isinstance(o["edges"], list) or not 1 <= len(o["edges"]) <= MAX_POINTS:
                raise OpError(f"{w}.edges must list 1..{MAX_POINTS} edges.")
            out["edges"] = [_edge(e, f"{w}.edges[{j}]") for j, e in enumerate(o["edges"])]
        else:
            out["region_boundary"] = _name(o["region_boundary"], f"{w}.region_boundary")
        return out
    if k == "name_region":
        _keys(o, ("name", "faces"), w)
        return {"op": k, "name": _name(o.get("name"), f"{w}.name"), "faces": _faces(o.get("faces"), f"{w}.faces")}
    if k == "mirror":
        _keys(o, ("axis", "clip", "merge"), w)
        if o.get("axis") not in ("x", "y", "z"):
            raise OpError(f"{w}.axis must be x, y or z.")
        if not isinstance(o.get("clip", True), bool):
            raise OpError(f"{w}.clip must be true or false.")
        return {"op": k, "axis": o["axis"], "clip": o.get("clip", True),
                "merge": _num(o.get("merge", 1e-4), f"{w}.merge", 0, 10)}
    if k == "geonodes_array":
        _keys(o, ("count", "offset"), w)
        return {"op": k, "count": _num(o.get("count"), f"{w}.count", 2, 256, integer=True),
                "offset": _vec(o.get("offset"), f"{w}.offset")}
    if k == "geonodes_scatter":
        _keys(o, ("count", "seed", "item_size", "scale"), w)
        sc = o.get("scale", [1.0, 1.0])
        if not isinstance(sc, list) or len(sc) != 2:
            raise OpError(f"{w}.scale must be [min, max].")
        lo, hi = (_num(x, f"{w}.scale", 1e-3, 1e3) for x in sc)
        if lo > hi:
            raise OpError(f"{w}.scale: min is above max.")
        return {"op": k, "count": _num(o.get("count"), f"{w}.count", 1, 2000, integer=True),
                "seed": _num(o.get("seed", 0), f"{w}.seed", 0, 2**31 - 1, integer=True),
                "item_size": _num(o.get("item_size", 1.0), f"{w}.item_size", 1e-3, 1e4), "scale": [lo, hi]}
    if k == "sculpt_ops":
        _keys(o, ("strokes",), w)
        st = o.get("strokes")
        if not isinstance(st, list) or not 1 <= len(st) <= 64:
            raise OpError(f"{w}.strokes must list 1..64 strokes.")
        out = []
        for j, s in enumerate(st):
            ws = f"{w}.strokes[{j}]"
            if not isinstance(s, dict):
                raise OpError(f"{ws} must be an object.")
            _keys(s, ("brush", "center", "radius", "strength", "direction", "iterations"), ws)
            if s.get("brush") not in BRUSHES:
                raise OpError(f"{ws}.brush must be one of {', '.join(BRUSHES)}.")
            r = {"brush": s["brush"], "center": _vec(s.get("center"), f"{ws}.center"),
                 "radius": _num(s.get("radius"), f"{ws}.radius", 1e-3, COORD),
                 "strength": _num(s.get("strength", 0.5), f"{ws}.strength", -1, 1)}
            if s["brush"] == "grab":
                r["direction"] = _vec(s.get("direction"), f"{ws}.direction")
            elif "direction" in s:
                raise OpError(f"{ws}.direction is only for the grab brush.")
            if s["brush"] == "smooth":
                r["iterations"] = _num(s.get("iterations", 1), f"{ws}.iterations", 1, 20, integer=True)
            elif "iterations" in s:
                raise OpError(f"{ws}.iterations is only for the smooth brush.")
            out.append(r)
        return {"op": k, "strokes": out}
    if k == "remesh":
        if o.get("mode") == "voxel":
            _keys(o, ("mode", "voxel_size"), w)
            return {"op": k, "mode": "voxel", "voxel_size": _num(o.get("voxel_size"), f"{w}.voxel_size", 1e-3, 1e4)}
        if o.get("mode") == "quad":
            _keys(o, ("mode", "target_faces", "seed"), w)
            return {"op": k, "mode": "quad", "target_faces": _num(o.get("target_faces"), f"{w}.target_faces", 6,
                                                                  200_000, integer=True),
                    "seed": _num(o.get("seed", 0), f"{w}.seed", 0, 2**31 - 1, integer=True)}
        raise OpError(f"{w}.mode must be voxel or quad.")
    out = _check_detail(k, o, w)
    if out is None:
        raise AssertionError(k)
    return out


def _edges(s, where):
    """An edge selection, normalised (see SELECTORS)."""
    if isinstance(s, list):
        s = {"pairs": s}
    if not isinstance(s, dict) or len(s) == 0:
        raise OpError(f"{where} must be an edge selection. {SELECTORS}")
    if "pairs" in s and len(s) == 1:
        if not isinstance(s["pairs"], list) or not 1 <= len(s["pairs"]) <= MAX_POINTS:
            raise OpError(f"{where}.pairs must list 1..{MAX_POINTS} edges.")
        return {"pairs": [_edge(e, f"{where}.pairs[{j}]") for j, e in enumerate(s["pairs"])]}
    if "path" in s and set(s) <= {"path", "closed"}:
        pts = _ints(s["path"], f"{where}.path")
        if len(pts) < 2:
            raise OpError(f"{where}.path needs at least two points.")
        if not isinstance(s.get("closed", False), bool):
            raise OpError(f"{where}.closed must be true or false.")
        return {"path": pts, "closed": s.get("closed", False)}
    if "region_boundary" in s and len(s) == 1:
        return {"region_boundary": _name(s["region_boundary"], f"{where}.region_boundary")}
    if "box" in s and len(s) == 1:
        return {"box": _points(s, where)["box"]}
    if "angle_deg" in s and len(s) == 1:
        return {"angle_deg": _num(s["angle_deg"], f"{where}.angle_deg", 1, 179)}
    if s.get("creased") is True and len(s) == 1:
        return {"creased": True}
    raise OpError(f"{where} is not an edge selection. {SELECTORS}")


def _opt_name(o, out, w):
    if "name" in o:
        out["name"] = _name(o["name"], f"{w}.name")
    return out


def _check_detail(k, o, w):
    """The cage vocabulary: bevel, support loops, inset, panel lines, trim, solidify, bridge, kit parts."""
    if k == "bevel":
        _keys(o, ("edges", "width", "segments", "profile", "crease", "name"), w)
        out = {"op": k, "edges": _edges(o.get("edges"), f"{w}.edges"),
               "width": _num(o.get("width"), f"{w}.width", 1e-3, 1e4),
               "segments": _num(o.get("segments", 1), f"{w}.segments", 1, 8, integer=True),
               "profile": _num(o.get("profile", 0.5), f"{w}.profile", 0.05, 1.0)}
        if "crease" in o:
            out["crease"] = _num(o["crease"], f"{w}.crease", 0, 1)
        return _opt_name(o, out, w)
    if k == "support_loops":
        _keys(o, ("edges", "distance"), w)
        return {"op": k, "edges": _edges(o.get("edges"), f"{w}.edges"),
                "distance": _num(o.get("distance"), f"{w}.distance", 1e-3, 1e4)}
    if k == "inset":
        _keys(o, ("faces", "thickness", "depth", "individual", "crease", "name"), w)
        if not isinstance(o.get("individual", False), bool):
            raise OpError(f"{w}.individual must be true or false.")
        out = {"op": k, "faces": _faces(o.get("faces"), f"{w}.faces"),
               "thickness": _num(o.get("thickness"), f"{w}.thickness", 1e-3, 1e4),
               "depth": _num(o.get("depth", 0.0), f"{w}.depth", -1e4, 1e4), "individual": o.get("individual", False)}
        if "crease" in o:
            out["crease"] = _num(o["crease"], f"{w}.crease", 0, 1)
        return _opt_name(o, out, w)
    if k in ("panel_line", "trim_strip"):
        third = "depth" if k == "panel_line" else "height"
        _keys(o, ("edges", "width", third, "crease", "name"), w)
        out = {"op": k, "edges": _edges(o.get("edges"), f"{w}.edges"),
               "width": _num(o.get("width"), f"{w}.width", 1e-3, 1e4),
               third: _num(o.get(third), f"{w}.{third}", 1e-3, 1e4),
               "crease": _num(o.get("crease", 1.0), f"{w}.crease", 0, 1)}
        return _opt_name(o, out, w)
    if k == "solidify":
        _keys(o, ("thickness", "offset", "rim_crease"), w)
        t = _num(o.get("thickness"), f"{w}.thickness", -1e4, 1e4)
        if abs(t) < 1e-3:
            raise OpError(f"{w}.thickness must not be zero.")
        return {"op": k, "thickness": t, "offset": _num(o.get("offset", -1.0), f"{w}.offset", -1, 1),
                "rim_crease": _num(o.get("rim_crease", 0.0), f"{w}.rim_crease", 0, 1)}
    if k == "bridge":
        _keys(o, ("faces_a", "faces_b", "cuts", "twist", "name"), w)
        out = {"op": k, "faces_a": _faces(o.get("faces_a"), f"{w}.faces_a"),
               "faces_b": _faces(o.get("faces_b"), f"{w}.faces_b"),
               "cuts": _num(o.get("cuts", 0), f"{w}.cuts", 0, 32, integer=True),
               "twist": _num(o.get("twist", 0), f"{w}.twist", -64, 64, integer=True)}
        return _opt_name(o, out, w)
    if k == "kit_place":
        return _check_kit(o, w)
    return None


def _check_kit(o, w):
    from ..game import kit
    _keys(o, ("part", "params", "faces", "mode", "at", "normal", "snap", "scale", "rotation", "offset", "name",
              "kit"), w)                       # kit: the version a normalised op carries (replaced by the current one)
    try:
        params = kit.check_params(o.get("part"), o.get("params"))
        part = kit.build(o["part"], params)
    except kit.KitError as e:
        raise OpError(f"{w}: {e}", "Kit parts: " + ", ".join(kit.names()))
    out = {"op": "kit_place", "part": o["part"], "params": params, "kit": kit.KIT_VERSION}
    if ("faces" in o) == ("at" in o):
        raise OpError(f"{w} needs faces (with mode each or center) or at (points), not both.")
    if "faces" in o:
        _keys(o, ("part", "params", "faces", "mode", "scale", "rotation", "offset", "name", "kit"), w)
        if o.get("mode", "each") not in ("each", "center"):
            raise OpError(f"{w}.mode must be each (one per face) or center (one at the selection's centre).")
        out["faces"] = _faces(o["faces"], f"{w}.faces")
        out["mode"] = o.get("mode", "each")
        count = 1
    else:
        if "mode" in o:
            raise OpError(f"{w}.mode is only for faces; at places one copy per point.")
        at = o["at"]
        if not isinstance(at, list) or not 1 <= len(at) <= MAX_PLACE:
            raise OpError(f"{w}.at must list 1..{MAX_PLACE} points [x, y, z].")
        out["at"] = [_vec(p, f"{w}.at[{j}]") for j, p in enumerate(at)]
        snap = o.get("snap", False)
        if not isinstance(snap, bool):
            raise OpError(f"{w}.snap must be true or false.")
        if snap == ("normal" in o):
            raise OpError(f"{w} with at needs normal: [x,y,z] or snap: true (the nearest surface point and its "
                          "normal), not both.")
        if snap:
            out["snap"] = True
        else:
            n = _vec(o["normal"], f"{w}.normal")
            if math.hypot(*n) < 1e-9:
                raise OpError(f"{w}.normal must not be zero.")
            out["normal"] = n
        count = len(at)
    sc = o.get("scale", 1.0)
    if isinstance(sc, list):
        out["scale"] = _vec(sc, f"{w}.scale", 0.01, 100)
    else:
        s = _num(sc, f"{w}.scale", 0.01, 100)
        out["scale"] = [s, s, s]
    out["rotation"] = _num(o.get("rotation", 0.0), f"{w}.rotation", -360, 360)
    out["offset"] = _num(o.get("offset", 0.0), f"{w}.offset", -1e3, 1e3)
    if len(part.V) * count > MAX_POINTS:
        raise OpError(f"{w}: {count} copies of {o['part']} ({len(part.V)} points each) exceed {MAX_POINTS} points.")
    return _opt_name(o, out, w)


def expand(o: dict) -> dict:
    """The op as the runner gets it: a kit_place op carries its part's geometry (scaled, turned about +Z), built here
    from the checked numbers; every other op goes as it is."""
    if o["op"] != "kit_place":
        return o
    from ..game import kit
    s = kit.build(o["part"], o["params"])
    t = math.radians(o["rotation"])
    c, sn = math.cos(t), math.sin(t)
    V = []
    for x, y, z in s.V.tolist():
        x, y, z = x * o["scale"][0], y * o["scale"][1], z * o["scale"][2]
        V.append([round(c * x - sn * y, 6), round(sn * x + c * y, 6), round(z, 6)])
    return dict(o, mesh={"V": V, "F": s.F, "C": s.C})


def validate_ops(ops) -> list[dict]:
    """The op list checked and normalised (defaults filled in), or OpError naming the op and what is wrong."""
    if isinstance(ops, str):
        try:
            ops = json.loads(ops)
        except ValueError as e:
            raise OpError(f"The op list is not JSON: {e}.", "Send a list of op objects.")
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        raise OpError(f"ops must be a list of 1..{MAX_OPS} ops.", "Start with {\"op\": \"cage_new\", ...}.")
    try:
        size = len(json.dumps(ops))
    except (TypeError, ValueError) as e:
        raise OpError(f"The op list is not plain JSON data: {e}.")
    if size > MAX_JSON:
        raise OpError(f"The op list is {size} bytes; the limit is {MAX_JSON}.")
    out = []
    high = False
    for i, o in enumerate(ops):
        if not isinstance(o, dict) or not isinstance(o.get("op"), str):
            raise OpError(f"op {i} must be an object with an \"op\" name.", index=i)
        if "high_only" in o:
            if not isinstance(o["high_only"], bool) or o["op"] == "cage_new":
                raise OpError(f"op {i}: high_only must be true or false, and cage_new does not take it.", index=i)
            ho = o["high_only"]
            o = {k: v for k, v in o.items() if k != "high_only"}
        else:
            ho = False
        if high and not ho:
            raise OpError(f"op {i} ({o['op']}) follows a high_only op, so it must be high_only too.", HIGH_ONLY_RULE,
                          index=i)
        high = high or ho
        if o["op"] not in OP_SCHEMA:
            raise OpError(f"op {i}: unknown op “{o['op'][:40]}”.", "Ops: " + ", ".join(OP_SCHEMA), index=i)
        if (o["op"] == "cage_new") != (i == 0):
            raise OpError(f"op {i}: cage_new must be the first op and appear only once.", index=i)
        try:
            n = _check_one(i, o)
        except OpError as e:
            e.index = i
            if not e.hint:
                e.hint = f"{o['op']}: {OP_SCHEMA[o['op']]}"
            raise
        if ho:
            n["high_only"] = True
        out.append(n)
    return out


def op_key(ops: list, blender_version: str = "") -> str:
    """The key an op list is stored under: canonical ops, runner version and Blender major.minor (the runner's
    results are only promised to replay on one Blender line)."""
    from ..studio import H
    v = compat.parse(blender_version)
    return H("model_mesh", RUNNER_VERSION, list(v[:2]) if v else None, validate_ops(ops))


def offline_flag(blender_version: str) -> list[str]:
    """--offline-mode exists from Blender 4.2."""
    v = compat.parse(blender_version)
    return ["--offline-mode"] if v and v[:2] >= (4, 2) else []


def command(app: str, blender_version: str, job_path: Path) -> list[str]:
    return [app, "-b", "--factory-startup", "-noaudio", "-Y", *offline_flag(blender_version),
            "--python-exit-code", "3", "--python", str(RUNNER), "--", str(job_path)]


def scrubbed_env(work: Path) -> dict:
    """What Blender sees of the environment: a fixed PATH, a temporary HOME and TMPDIR, the locale. Nothing else
    (no PYTHONPATH/PYTHONHOME, no user Blender folders, no tokens)."""
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin" if os.name != "nt" else os.environ.get("SystemRoot", r"C:\Windows"),
           "HOME": str(work), "TMPDIR": str(work), "TMP": str(work), "TEMP": str(work),
           "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "BLENDER_USER_RESOURCES": str(work / "blender-user")}
    if os.name == "nt":
        for k in ("SystemRoot", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            env.setdefault(k, str(work) if k != "SystemRoot" else os.environ.get(k, r"C:\Windows"))
    return env


# ---- running -------------------------------------------------------------------------------------------------

def run_ops(ops, cfg: dict | None = None, timeout: float = TIMEOUT_S, on_stage=None, label: str = "",
            export_subdiv: int | None = None, app: str | None = None, keep_dir: Path | None = None) -> dict:
    """Validate ops, run them in Blender, return {"cage": CageData, "hash", "key", "ops": per-op seconds,
    "stages": n, "seconds", "blender"}.

    on_stage(event): called for each op with the stage event (meshsource.stage_event), feature "model_mesh:<i>:<op>".
    export_subdiv: also return Blender's own Catmull-Clark subdivision of the result at that level ("subdiv": V),
    without the limit-surface projection (verification against form.craft.subd.catmull_clark).
    Raises OpError (before Blender starts), BlenderMissing or BlenderFailed (a timeout kills Blender)."""
    norm = validate_ops(ops)
    if app is None:
        r = resolve(cfg)
        if not r["available"]:
            raise BlenderMissing(r["reason"])
        app, ver = r["app"], r["version"]
    else:
        ver = version(app)
    key = op_key(norm, ver)
    work = Path(tempfile.mkdtemp(prefix="form-model-"))
    try:
        (work / "blender-user").mkdir()
        (work / "stages").mkdir()
        job = {"runner": RUNNER_VERSION, "ops": [expand(o) for o in norm], "out": str(work / "result.json"),
               "stage_dir": str(work / "stages"), "preview_levels": PREVIEW_LEVELS}
        if export_subdiv:
            job["export_subdiv"] = {"levels": int(export_subdiv)}
        jp = work / "job.json"
        jp.write_text(json.dumps(job), encoding="utf-8")
        log, stages, report = _run(command(app, ver, jp), work, timeout, norm, on_stage, label)
        res = work / "result.json"
        if not report or not report.get("ok") or not res.is_file():
            err = (report or {}).get("error") or "Blender stopped without a result."
            at = (report or {}).get("op")
            where = f" at op {at} ({norm[at]['op']})" if isinstance(at, int) and 0 <= at < len(norm) else ""
            why = compat.wrap_message("blender", ver, f"The modelling ops failed{where}: {err}", tail(log, 60))
            if why:
                raise BlenderFailed(why[0], why[1], tail(log))
            raise BlenderFailed(f"The modelling ops failed{where}: {err}",
                                "Fix that op (indices refer to the cage as the ops before it left it).", tail(log))
        out = json.loads(res.read_text(encoding="utf-8"))
        cage = meshsource.CageData.from_dict(out["cage"])
        if keep_dir:
            keep_dir = Path(keep_dir)
            keep_dir.mkdir(parents=True, exist_ok=True)
            tmp = keep_dir / f".{key}.tmp"
            tmp.mkdir(exist_ok=True)
            (tmp / "ops.json").write_text(json.dumps(norm), encoding="utf-8")
            cage.save(tmp / "cage.json")
            (tmp / "report.json").write_text(json.dumps({"hash": cage.hash(), "blender": ver, "ops": out["ops"]}),
                                             encoding="utf-8")
            final = keep_dir / key
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            os.replace(tmp, final)
        result = {"cage": cage, "hash": cage.hash(), "key": key, "ops": out["ops"], "stages": stages,
                  "blender": ver, "seconds": report.get("seconds")}
        if "subdiv" in out:
            result["subdiv"] = out["subdiv"]
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run(cmd, work: Path, timeout: float, norm: list, on_stage, label: str):
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=str(work), env=scrubbed_env(work), text=True, encoding="utf-8", errors="replace",
                                start_new_session=(os.name != "nt"))
    except OSError as e:
        raise BlenderFailed(f"Could not start Blender: {e}", f"Check [blender].app, or reinstall from {DOWNLOAD_URL}")
    killed = {"v": False}

    def watchdog():                                # the blender.py pattern, but the whole process group goes
        if proc.poll() is None:
            killed["v"] = True
            try:
                if os.name != "nt":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except OSError:
                proc.kill()
    timer = threading.Timer(timeout, watchdog)
    timer.daemon = True
    timer.start()
    log: list[str] = []
    stages = 0
    report = None
    stage_root = (work / "stages").resolve()
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            log.append(line)
            if len(log) > 4000:
                del log[:2000]
            if line.startswith("FORM_STAGE "):
                p = Path(line[11:].strip()).resolve()
                if p.parent != stage_root:         # only files in this run's own stage folder are read
                    continue
                stages += 1
                if on_stage:
                    try:
                        _idx = int(p.stem.rsplit("_", 1)[-1])
                        name = norm[_idx]["op"] if 0 <= _idx < len(norm) else "op"
                        ev = meshsource.stage_event(p, f"model_mesh:{_idx}:{name}", label or name.replace("_", " "),
                                                    of=len(norm))
                        on_stage(ev)
                    except (OSError, ValueError, IndexError):
                        pass
            elif line.startswith("FORM_RESULT "):
                try:
                    report = json.loads(line[12:])
                except ValueError:
                    report = None
        proc.wait()
    finally:
        timer.cancel()
        proc.stdout.close()
    text = "\n".join(log)
    if killed["v"]:
        raise BlenderFailed(f"Blender did not finish the modelling ops within {timeout:.0f} s and was stopped.",
                            "Use fewer or lighter ops (remesh and scatter are the slow ones), or raise the timeout. "
                            "Nothing was saved.", tail(text))
    if report is not None:
        report["seconds"] = round(time.time() - t0, 3)
    if proc.returncode != 0 and report and report.get("ok"):
        report = {"ok": False, "error": f"Blender exited with code {proc.returncode}."}
    return text, stages, report


# ---- the MCP tool (wired by the integration package, not here) ------------------------------------------------------

def model_mesh(st, project: str, ops, expect_head: int, timeout: float = TIMEOUT_S, on_stage=None) -> dict:
    """Run ops for a project. Reads the project, never writes it: the result goes to <data>/.cache/model_mesh/<key>/
    (ops.json, cage.json, report.json), and the cage comes back as source for update_design."""
    norm = validate_ops(ops)                       # refused here, before the project is read or Blender starts
    p = st.load(project)
    if expect_head is None or p["head"] != expect_head:
        from ..studio import StudioError
        raise StudioError(f"The project is at revision {p['head']}, not {expect_head}.",
                          "Read the project again (get_project) and pass its head as expect_head.", status=409,
                          head=p["head"])
    if on_stage is None and hasattr(st, "_draft_sink"):
        draft = "draft-" + secrets.token_hex(8)
        on_stage = st._draft_sink(draft, p.get("name", project))
    else:
        draft = None
    r = run_ops(norm, cfg=getattr(st, "cfg", None), timeout=timeout, on_stage=on_stage,
                keep_dir=Path(st.root) / ".cache" / "model_mesh")
    cage = r["cage"]
    return {"project": project, "base_rev": p["head"], "key": r["key"], "hash": r["hash"], "draft": draft,
            "cage": cage.summary(), "cage_file": str(Path(st.root) / ".cache" / "model_mesh" / r["key"] / "cage.json"),
            "ops": r["ops"], "stages": r["stages"], "seconds": r["seconds"], "blender": r["blender"],
            "source": "from form import meshsource\nfrom form.craft import subd\n" + cage.literal(),
            "next": "Put `source` in the design (a FeatureDesign feature builds it with subd.Cage(CAGE.V, CAGE.F)."
                    "solid()), then update_design(..., expect_head=" + str(p["head"]) + "). Blender is the editor; "
                    "the design source stays the geometry authority."}


def register(mcp, get_studio=None, run=None) -> None:
    """Add model_mesh(project, ops, expect_head) to an MCP server.

    get_studio: () -> Studio (default: form.mcp_server.studio). run: async runner for blocking work that turns
    StudioError into tool errors (default: form.mcp_server._run)."""
    async def model_mesh_tool(project: str, ops: list, expect_head: int) -> dict:
        """Model a subdivision cage in Blender with declarative ops (never code), e.g.
        [{"op":"cage_new","primitive":"cube","size":[40,30,20]}, {"op":"name_region","name":"top",
        "faces":{"normal":[0,0,1],"within_deg":10}}, {"op":"extrude_region","faces":{"region":"top"},"offset":8}].
        Ops: cage_new, extrude_region, loop_cut, move, crease, name_region, mirror, geonodes_array,
        geonodes_scatter, sculpt_ops, remesh, and the detail vocabulary bevel, support_loops, inset, panel_line,
        trim_strip, solidify, bridge, kit_place (original parametric parts: bolts, rivets, vents, hinges, straps,
        buckles, grips, pommels, greebles; a refused call lists them). Any op but cage_new may say high_only: true
        (last in the list): it details only the bake source, returned as the cage's `high`, never the LODs.
        Each op streams a level-2 preview to the app. Returns the cage (points, quads, creases, named regions) as
        design source for update_design; the project is not changed.
        Needs Blender 4.2+. Blender is not network-isolated by the OS."""
        st = (get_studio or _default_studio)()

        def go():
            try:
                return model_mesh(st, project, ops, expect_head)
            except OpError as e:
                from ..game import kit
                return {"refused": True, "error": e.public(), "schema": OP_SCHEMA, "selectors": SELECTORS,
                        "kit": kit.describe()}
            except (BlenderMissing, BlenderFailed) as e:
                return {"ok": False, "error": str(e), "hint": getattr(e, "hint", ""), "log_tail": getattr(e, "log", "")[-3000:],
                        "project_unchanged": True}
        if run is not None:
            return await run(go)
        from ..mcp_server import _run as default_run
        return await default_run(go)
    model_mesh_tool.__name__ = "model_mesh"
    model_mesh_tool.__qualname__ = "model_mesh"
    try:
        from mcp.types import ToolAnnotations
        ann = {"annotations": ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                                              open_world_hint=False)}
    except ImportError:
        ann = {}
    mcp.tool(name="model_mesh", **ann)(model_mesh_tool)


def _default_studio():
    from ..mcp_server import studio
    return studio()
