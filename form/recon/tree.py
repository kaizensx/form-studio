"""Layer 2: a feature tree rebuilt from the Layer 1 solid. Kernel worker only (imports OCCT). Beta.

1. Features are found on the Layer 1 B-rep (graph.py): holes (with counterbores, countersinks, drill points), constant
   radius fillets and equal-distance chamfers.
2. They are taken off the solid (BRepAlgoAPI_Defeaturing): what is left is the core, with sharp edges and no holes.
3. The core becomes the base of the recipe:
   - a revolution, when every face is round one axis (planes across it, cylinders, cones, tori, spheres on it): its
     profile is the core cut by a plane through the axis, with every diameter and height a Param;
   - an extrusion stack, when every face is across one direction or along it (planes, cylinders on that direction):
     the core is cut at the middle of every slab between two levels, the outlines become extrusions (the base, steps
     and bosses) and the holes in them pockets and cutouts, with heights and depths as Params (rectangles and circles
     get their sizes as Params too);
   - otherwise the core itself, kept as a solid the recipe reads (analytic, B-spline and frozen faces from Layer 1):
     an "embedded" base, exact, with the parametric features on top.
4. The features are put back in order: fillets and chamfers (on the edges nearest where they were, the radius or
   distance a Param), then holes (diameters snapped to standard sizes, depths, counterbore and countersink sizes as
   Params; holes of one kind on a grid, a line or a circle as one pattern).
5. The recipe is built, as the Studio builds it, and compared with the mesh (two-sided Hausdorff). A feature that
   fails to build or puts the result outside the limit is left in the base instead (and reported); a base that fails
   becomes the embedded core. Nothing is offered unless it is within the limit.
"""
from __future__ import annotations

import math
import os
import time
import traceback
from pathlib import Path

import numpy as np

from . import graph as gmod
from . import holes as holemod
from .features import PAR, _area2, _chain, _f, _grid, _polar, _v

MAX_FACES = 4000           # a Layer 1 solid with more faces than this (frozen facets, mostly) is not searched for features
ROLE = {"base": "structure", "step": "structure", "pocket": "structure", "hole": "interface", "fillet": "finish",
        "chamfer": "finish"}


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _canon(d):
    d = _unit(d)
    k = int(np.argmax(np.abs(d)))
    return -d if d[k] < 0 else d


def _frame(d):
    """x and y directions for a sketch across d: world axes when d is one."""
    k = int(np.argmax(np.abs(d)))
    if abs(abs(d[k]) - 1) < 1e-9:
        u = np.eye(3)[0 if k != 0 else 1]
    else:
        t = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
        u = _unit(np.cross(t, d))
    return u, np.cross(d, u)


# ---- defeaturing -----------------------------------------------------------------------------------------------------

def defeature(shape, faces):
    """The solid without these faces (their neighbours extended to close the gap), or None.

    OpenCascade's defeaturing can crash the process outright on some blends (a segmentation fault on a block whose
    rounded vertical and top edges meet in corner blends), so where the system can fork it runs in a child process:
    a crash there is a feature that will not come off (None), not the end of the reconstruction."""
    if not faces:
        return shape
    if hasattr(os, "fork") and os.environ.get("FORM_RECON_FORK", "1") != "0":
        if time.perf_counter() < _broken[0]:          # it just crashed or hung on this part: the rest would too
            return None
        out = _forked(_defeature, shape, faces)
        return out
    return _defeature(shape, faces)


DEFEATURE_S = 20.0         # seconds one defeaturing may take in its child before the feature is left on
BROKEN_S = 300.0           # after a crash or a hang, defeaturing is not tried again for this long (the same part)
_broken = [0.0]


def _forked(fn, shape, *args):
    """fn(shape, *args) -> shape or None, run in a forked child; the result comes back as a BRep file."""
    import tempfile
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    fd, path = tempfile.mkstemp(suffix=".brep", prefix="form-defeature-")
    os.close(fd)
    import warnings
    try:
        with warnings.catch_warnings():                 # the progress thread holds no lock the child needs; a child
            warnings.simplefilter("ignore", DeprecationWarning)    # that hangs anyway is stopped after DEFEATURE_S
            pid = os.fork()
        if pid == 0:                                    # the child: never returns into the parent's code
            code = 1
            try:
                out = fn(shape, *args)
                if out is not None and BRepTools.Write_s(out, path):
                    code = 0
            except BaseException:                       # noqa: BLE001
                code = 1
            os._exit(code)
        t_end = time.perf_counter() + DEFEATURE_S
        while True:                                     # a child that runs past DEFEATURE_S is stopped
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                break
            if time.perf_counter() > t_end:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                _broken[0] = time.perf_counter() + BROKEN_S
                return None
            time.sleep(0.02)
        if os.WIFSIGNALED(status):                      # a crash, not a feature that will not come off
            _broken[0] = time.perf_counter() + BROKEN_S
            return None
        if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
            return None
        sh = TopoDS_Shape()
        if not BRepTools.Read_s(sh, path, BRep_Builder()):
            return None
        return sh
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _defeature(shape, faces):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Defeaturing
    from .solid import check
    d = BRepAlgoAPI_Defeaturing()
    d.SetShape(shape)
    for f in faces:
        d.AddFaceToRemove(f)
    d.SetRunParallel(False)
    d.SetToFillHistory(True)
    try:
        d.Build()
    except Exception:                                   # noqa: BLE001
        return None
    if not d.IsDone() or not all(d.IsDeleted(f) for f in faces):
        return None                                     # it gives the shape back unchanged when a face will not go
    out = d.Shape()
    ck = check(out)
    return out if ck["valid"] and ck["solids"] == 1 else None


def remove_features(shape, G, feats):
    """Take off as many features as will go. Returns (core, removed, kept-with-reason)."""
    faces = lambda fs: [G.faces[i] for f in fs for i in f["faces"]]
    core = defeature(shape, faces(feats))
    if core is not None:
        return core, list(feats), []
    removed, kept = [], []
    for f in sorted(feats, key=lambda f: ("hole", "chamfer", "fillet").index(f["kind"])):
        c = defeature(shape, faces(removed + [f]))
        if c is None:
            kept.append(f)
        else:
            core = c
            removed.append(f)
    return (core if removed else shape), removed, kept


def _brief(f):
    out = {"kind": f["kind"]}
    if f["kind"] == "hole":
        out["diameter_mm"] = round(f["steps"][-1][1] if f["steps"][-1][0] == "cyl" else f["steps"][-1][2], 4)
    elif f["kind"] == "fillet":
        out["radius_mm"] = round(f["r"], 4)
    elif f["kind"] == "chamfer":
        out["width_mm"] = round(f["width"], 4)
    return out


# ---- what the core is ------------------------------------------------------------------------------------------------

def core_kind(G, ignore=frozenset()):
    """("revolve", o, a) | ("stack", d) | None, from the core's faces (except those in `ignore`)."""
    eps = 1e-5 * max(G.size, 1.0)
    infos = [G.info[i] for i in range(len(G.faces)) if i not in ignore]
    if any(d["kind"] in ("other", "bspline") for d in infos):
        return None
    tot = sum(d["area"] for d in infos)
    axes = [d for d in sorted(infos, key=lambda d: -d["area"]) if d["kind"] in ("cylinder", "cone", "torus")]
    for d0 in axes:
        o, a = d0["o"], _canon(d0["a"])
        ok = True
        for d in infos:
            k = d["kind"]
            if k == "plane":
                ok = abs(abs(d["a"] @ a) - 1) < 1e-7
            elif k == "sphere":
                ok = np.linalg.norm(np.cross(d["o"] - o, a)) < eps
            else:
                ok = abs(abs(d["a"] @ a) - 1) < 1e-7 and np.linalg.norm(np.cross(d["o"] - o, a)) < eps
            if not ok:
                break
        if ok:
            return ("revolve", o, a)
    cands = []
    for d in sorted(infos, key=lambda d: -d["area"]):
        if d["kind"] in ("plane", "cylinder"):
            c = _canon(d["a"])
            if not any(abs(c @ x) > PAR for x in cands):
                cands.append(c)
    for dd in cands:
        ok = True
        for d in infos:
            k = d["kind"]
            if k == "plane":
                ok = abs(abs(d["a"] @ dd) - 1) < 1e-7 or abs(d["a"] @ dd) < 1e-7
            elif k == "cylinder":
                ok = abs(abs(d["a"] @ dd) - 1) < 1e-7
            else:
                ok = False
            if not ok:
                break
        if ok:
            return ("stack", dd)
    return None


def _section(core, origin, normal):
    """Edges where the plane (origin, normal) cuts the core: [("line", p0, p1) | ("circle", c, n, r) |
    ("arc", p0, pm, p1)] in 3-D, or None when a cut edge is neither a line nor a circle."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    sec = BRepAlgoAPI_Section(core, gp_Pln(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, normal))), False)
    sec.Approximation(False)
    sec.ComputePCurveOn1(False)
    sec.Build()
    out = []
    ex = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
    while ex.More():
        c = BRepAdaptor_Curve(TopoDS.Edge(ex.Current()))
        t0, t1 = c.FirstParameter(), c.LastParameter()
        p0, p1, pm = gmod._np(c.Value(t0)), gmod._np(c.Value(t1)), gmod._np(c.Value(0.5 * (t0 + t1)))
        if c.GetType() == GeomAbs_Line:
            out.append(("line", p0, p1))
        elif c.GetType() == GeomAbs_Circle:
            ci = c.Circle()
            if abs((t1 - t0) - 2 * math.pi) < 1e-9:
                out.append(("circle", gmod._np(ci.Location()), gmod._np(ci.Axis().Direction()), ci.Radius()))
            else:
                out.append(("arc", p0, pm, p1))
        else:
            SECTION_MISS.append(str(c.GetType()))
            return None
        ex.Next()
    return out


SECTION_MISS: list = []


def _to2d(elems, o, u, w):
    def q(p):
        r = p - o
        return np.array([r @ u, r @ w])
    out = []
    for e in elems:
        if e[0] == "circle":
            out.append(("circle", q(e[1]), e[3]))
        else:
            out.append((e[0],) + tuple(q(p) for p in e[1:]))
    return out


def _merge_lines(loop, eps):
    """Join consecutive collinear lines (a cut splits a straight edge where other faces meet it)."""
    out = []
    for e in loop:
        if out and e[0] == "line" and out[-1][0] == "line":
            a, b, c = out[-1][1], out[-1][2], e[2]
            ab, ac = b - a, c - a
            if abs(ab[0] * ac[1] - ab[1] * ac[0]) <= eps * max(np.linalg.norm(ac), 1e-12) and ab @ (c - b) > 0:
                out[-1] = ("line", a, c)
                continue
        out.append(e)
    if len(out) > 2 and out[0][0] == "line" and out[-1][0] == "line":
        a, b, c = out[-1][1], out[-1][2], out[0][2]
        ab, ac = b - a, c - a
        if abs(ab[0] * ac[1] - ab[1] * ac[0]) <= eps * max(np.linalg.norm(ac), 1e-12) and ab @ (c - b) > 0:
            out[0] = ("line", a, c)
            out.pop()
    return out


def _poly(loop, n=24):
    pts = []
    for e in loop:
        if e[0] == "circle":
            c, r = e[1], e[2]
            return np.array([c + r * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(0, 2 * math.pi, 64, endpoint=False)])
        if e[0] == "line":
            pts.append(e[1])
        else:
            from .brep import _circle
            p0, pm, p1 = e[1], e[2], e[3]
            P3 = np.c_[np.array([p0, pm, p1]), np.zeros(3)]
            c, _, r, _ = _circle(P3)
            c = c[:2]
            a0, am, a1 = (math.atan2(*(p - c)[::-1]) for p in (p0, pm, p1))
            # go from a0 to a1 through am
            def norm(x):
                return x % (2 * math.pi)
            span = norm(a1 - a0)
            if norm(am - a0) > span:
                span = span - 2 * math.pi
            for t in np.linspace(0, 1, n, endpoint=False):
                ang = a0 + span * t
                pts.append(c + r * np.array([math.cos(ang), math.sin(ang)]))
    return np.array(pts)


def _inside(pt, poly):
    x, y = pt
    n = len(poly)
    c = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1:
            c = not c
    return c


def _sig(loop, nd=5):
    """A key for comparing loops between slabs."""
    pts = []
    for e in loop:
        if e[0] == "circle":
            pts.append((round(float(e[1][0]), nd), round(float(e[1][1]), nd), round(float(e[2]), nd)))
        else:
            for p in e[1:]:
                pts.append((round(float(p[0]), nd), round(float(p[1]), nd)))
    return tuple(sorted(set(pts)))


def stack_plan(core, G, d):
    """Slabs of the core along d: levels, and per slab the outer loops and their holes, in the sketch frame."""
    eps = 1e-6 * max(G.size, 1.0)
    u, w = _frame(d)
    lv = sorted({round(float(G.info[i]["o"] @ d), 9) for i in range(len(G.faces))
                 if G.info[i]["kind"] == "plane" and abs(abs(G.info[i]["a"] @ d) - 1) < 1e-7})
    levels = []
    for z in lv:
        if not levels or z - levels[-1] > 1e-6 * max(G.size, 1.0):
            levels.append(z)
    if len(levels) < 2:
        return None, "fewer than two levels across the direction"
    o = levels[0] * d
    slabs = []
    for z0, z1 in zip(levels, levels[1:]):
        el = _section(core, (0.5 * (z0 + z1)) * d, d)
        if el is None:
            return None, "a cut through the core has an edge that is neither a line nor a circle"
        el = _to2d(el, (0.5 * (z0 + z1)) * d, u, w)
        try:
            loops = _chain(el, max(1e-6 * G.size, 1e-7))
        except ValueError as e:
            return None, str(e)
        loops = [_merge_lines(lp, max(1e-9 * G.size, 1e-12)) for lp in loops]
        polys = [_poly(lp) for lp in loops]
        depth = []
        for i, lp in enumerate(loops):
            pt = polys[i][0] if len(polys[i]) else np.zeros(2)
            # a point just inside the loop's first edge is enough: loops do not cross
            depth.append(sum(_inside(pt, polys[j]) for j in range(len(loops)) if j != i))
        outer = [i for i in range(len(loops)) if depth[i] % 2 == 0]
        faces = []
        for i in outer:
            inner = [j for j in range(len(loops)) if depth[j] == depth[i] + 1 and _inside(polys[j][0], polys[i])]
            faces.append({"outer": loops[i], "inner": [loops[j] for j in inner]})
        slabs.append({"z0": z0 - levels[0], "z1": z1 - levels[0], "faces": faces})
    return {"kind": "stack", "d": d, "u": u, "w": w, "o": o, "levels": [z - levels[0] for z in levels], "slabs": slabs}, ""


def prisms(plan):
    """Outer loops and inner loops that repeat over consecutive slabs, as prisms: (kind, loop, z0, z1)."""
    out = []
    for kind in ("outer", "inner"):
        open_ = {}                                   # sig -> [loop, z0, z1]
        for sl in plan["slabs"]:
            here = {}
            for f in sl["faces"]:
                for lp in ([f["outer"]] if kind == "outer" else f["inner"]):
                    here[_sig(lp)] = lp
            for k in list(open_):
                if k not in here or abs(open_[k][2] - sl["z0"]) > 1e-9:
                    out.append((kind, *open_.pop(k)))
            for k, lp in here.items():
                if k in open_:
                    open_[k][2] = sl["z1"]
                else:
                    open_[k] = [lp, sl["z0"], sl["z1"]]
        out += [(kind, *v) for v in open_.values()]
    return out


def revolve_plan(core, G, o, a, ignore=frozenset()):
    """The profile of a core that is round one axis, read from its faces: every face of a revolution is bounded by
    circles round the axis, so a plane gives a line across, a cylinder or cone a line along, a torus or sphere an arc."""
    eps = max(1e-5 * G.size, 1e-7)
    u, _ = _frame(a)

    def rz(p):
        r = p - o
        z = float(r @ a)
        return np.array([float(np.linalg.norm(r - z * a)), z])
    elems, seen = [], set()
    for i, d in enumerate(G.info):
        if i in ignore:
            continue
        circ = []
        for j, es in G.nb[i].items():
            for ei in es:
                m = G.edge_mid(ei)
                if (m["kind"] == "circle" and abs(abs(m["a"] @ a) - 1) < 1e-7
                        and np.linalg.norm(np.cross(m["o"] - o, a)) < eps):      # round the axis, not a hole's rim
                    circ.append(np.array([m["r"], float((m["o"] - o) @ a)]))
        if not circ:
            continue
        circ = sorted({(round(float(c[0]), 9), round(float(c[1]), 9)) for c in circ})
        C = np.array(circ)
        k = d["kind"]
        if k == "plane":
            z = float((d["o"] - o) @ a)
            r0 = 0.0 if len(C) == 1 else float(C[:, 0].min())
            e = ("line", np.array([r0, z]), np.array([float(C[:, 0].max()), z]))
        elif k in ("cylinder", "cone"):
            if len(C) < 2:
                if k == "cone":                        # a cone to a point on the axis
                    ap = rz(d["apex"])
                    e = ("line", np.array([0.0, ap[1]]), C[0])
                else:
                    return None, "a cylinder with one boundary circle"
            else:
                i0, i1 = int(np.argmin(C[:, 1])), int(np.argmax(C[:, 1]))
                e = ("line", C[i0], C[i1])
        elif k in ("torus", "sphere"):
            if len(C) < 2:
                return None, f"a {k} with one boundary circle"
            pm = rz(d["pt"])
            e = ("arc", C[0], pm, C[-1])
        else:
            return None, f"a {k} face"
        key = tuple(np.round(np.concatenate([p for p in e[1:]]), 6))
        rkey = tuple(np.round(np.concatenate([p for p in reversed(e[1:])]), 6))
        if key in seen or rkey in seen:
            continue
        seen.add(key)
        if np.linalg.norm(e[1] - e[-1]) > eps:
            elems.append(e)
    ends = [p for e in elems for p in (e[1], e[-1])]
    on_axis = [p for p in ends if abs(p[0]) < eps]
    if len(on_axis) == 2 and np.linalg.norm(on_axis[0] - on_axis[1]) > eps:
        elems.append(("line", on_axis[0], on_axis[1]))
    try:
        loops = _chain(elems, eps)
    except ValueError as e:
        return None, str(e)
    if len(loops) != 1:
        return None, f"{len(loops)} profiles round the axis"
    loop = _merge_lines(loops[0], max(1e-9 * G.size, 1e-12))
    loop, rounds = _profile_rounds(loop, eps)
    return {"kind": "revolve", "o": o, "a": a, "u": u, "loop": loop, "rounds": rounds}, ""


def _meet(a0, a1, b0, b1):
    """Where the line through a0, a1 meets the line through b0, b1 (2-D), or None if parallel."""
    da, db = a1 - a0, b1 - b0
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-12 * max(np.linalg.norm(da) * np.linalg.norm(db), 1e-300):
        return None
    t = ((b0[0] - a0[0]) * db[1] - (b0[1] - a0[1]) * db[0]) / den
    return a0 + t * da


def _profile_rounds(loop, eps):
    """Arcs tangent to the lines on both sides (fillets) and short lines at equal angles to both neighbours (chamfers)
    become sharp corners plus a 2-D fillet or chamfer there: [(kind, corner, size)]."""
    from .brep import _circle
    out, rounds = list(loop), []
    changed = True
    while changed:
        changed = False
        n = len(out)
        for i in range(n):
            e, prev, nxt = out[i], out[i - 1], out[(i + 1) % n]
            if n < 4 or prev[0] != "line" or nxt[0] != "line" or e is prev or e is nxt:
                continue
            if e[0] == "arc":
                p0, pm, p1 = e[1], e[2], e[3]
                c, _, r, _ = _circle(np.c_[np.array([p0, pm, p1]), np.zeros(3)])
                c = c[:2]
                t0, t1 = _unit(prev[2] - prev[1]), _unit(nxt[2] - nxt[1])
                if abs(_unit(p0 - c) @ t0) > 1e-3 or abs(_unit(p1 - c) @ t1) > 1e-3:
                    continue
                kind, size = "fillet", r
            elif e[0] == "line":
                L = np.linalg.norm(e[2] - e[1])
                d0, d1, de = _unit(prev[2] - prev[1]), _unit(nxt[2] - nxt[1]), _unit(e[2] - e[1])
                a0 = math.degrees(math.acos(max(-1, min(1, float(d0 @ de)))))
                a1 = math.degrees(math.acos(max(-1, min(1, float(de @ d1)))))
                if not (20 < a0 < 70 and abs(a0 - a1) < 1.0) or L > 0.75 * min(np.linalg.norm(prev[2] - prev[1]),
                                                                                np.linalg.norm(nxt[2] - nxt[1])):
                    continue
                kind, size = "chamfer", None
            else:
                continue
            corner = _meet(prev[1], prev[2], nxt[1], nxt[2])
            if corner is None:
                continue
            if kind == "chamfer":
                size = float(np.linalg.norm(corner - e[1]))
            rounds.append((kind, corner, float(size)))
            j = (i + 1) % n
            out[i - 1] = ("line", prev[1], corner)
            out[j] = ("line", corner, nxt[2])
            out.pop(i)
            changed = True
            break
    return out, rounds


# ---- source ----------------------------------------------------------------------------------------------------------

class Src:
    def __init__(self, name):
        self.name = name
        self.params = []            # (key, value, label, feature, note, lo, hi, step, unit)
        self.feats = []             # (id, label, role, doc)
        self.body = []
        self.spans = {}             # feature id -> (first line, last line) in body
        self._cur = None

    def param(self, key, value, label, feature, note, lo=None, hi=None, step=0.01, unit="mm"):
        value = round(float(value), 4)
        if lo is None:
            lo = round(max(0.01, value * 0.1), 4)
        if hi is None:
            hi = round(value * 4 + 1, 4)
        self.params.append((key, value, label, feature, note, lo, hi, step, unit))
        return f"v[{key!r}]"

    def feature(self, fid, label, role, doc=""):
        self.feats.append((fid, label, role, doc))
        self._cur = fid
        self.spans[fid] = [len(self.body), len(self.body)]

    def add(self, *lines):
        self.body += lines
        if self._cur:
            self.spans[self._cur][1] = len(self.body)

    def text(self, doc, imports=("Align", "Axis", "Edge", "Location", "Plane", "Polyline", "ThreePointArc", "Vector",
                                 "Wire", "chamfer", "extrude", "fillet", "make_face", "revolve")):
        L = ['"""' + doc + '\n"""', "import math", "",
             "from build123d import " + ", ".join(imports), "",
             "from form.recipes.base import Feature, Param, Recipe, Stage",
             "from form.recon.ops import edges_near, hole, vertices_near", "", "",
             "class Design(Recipe):",
             f"    title = {(self.name + ' (reconstructed)')!r}",
             "    summary = 'Rebuilt from a mesh as a feature tree: base, then features in order.'",
             "    params = ["]
        for key, val, label, feat, note, lo, hi, step, unit in self.params:
            L.append(f"        Param({key!r}, {label!r}, {_f(val)}, {_f(lo)}, {_f(hi)}, {step}, {unit!r}, \"form\", {feat!r}, "
                     f"{note!r}, provenance=\"mesh\"),")
        L += ["    ]", "    features = ["]
        L += [f"        Feature({fid!r}, {label!r}, {role!r}, {doc!r})," for fid, label, role, doc in self.feats]
        L += ["    ]", "", "    def build(self, v):", "        stages = []"]
        self.first_body_line = "\n".join(L).count("\n") + 2
        L += ["        " + b for b in self.body]
        L += ["        return stages"]
        return "\n".join(L) + "\n"

    def feature_at(self, lineno):
        """The feature whose code holds this line of the text."""
        i = lineno - self.first_body_line
        for fid, (a, b) in self.spans.items():
            if a <= i < b:
                return fid
        return None


def _loop_lines(loop, var, pt, s):
    """Code for one 2-D loop as a list of edges in `var`; pt(p) is the 3-D point code."""
    out = [f"{var} = []"]
    run = []

    def flush():
        if len(run) >= 2:
            out.append(f"{var} += Polyline({', '.join(pt(p) for p in run)}).edges()")
        run.clear()
    for e in loop:
        if e[0] == "line":
            if not run:
                run.append(e[1])
            run.append(e[2])
        else:
            flush()
            out.append(f"{var}.append(ThreePointArc({pt(e[1])}, {pt(e[2])}, {pt(e[3])}))")
    flush()
    return out


def _is_rect(loop, eps):
    if len(loop) != 4 or any(e[0] != "line" for e in loop):
        return None
    P = np.array([e[1] for e in loop])
    xs, ys = np.unique(np.round(P[:, 0], 9)), np.unique(np.round(P[:, 1], 9))
    if len(xs) != 2 or len(ys) != 2:
        return None
    for e in loop:
        dx, dy = abs(e[2][0] - e[1][0]), abs(e[2][1] - e[1][1])
        if dx > eps and dy > eps:
            return None
    return float(xs[0]), float(ys[0]), float(xs[1] - xs[0]), float(ys[1] - ys[0])


def _at(z):
    return "" if z == "0" else f"Location(D * {z}) * "


def _minus(a, b):
    return a if b == "0" else f"{a} - {b}"


def _stack_source(S, plan, eps):
    d, u = plan["d"], plan["u"]
    S.add(f"pl = Plane(origin={_v(plan['o'])}, x_dir={_v(u)}, z_dir={_v(d)})",
          "P = lambda x, y: pl.from_local_coords((x, y))",
          "D = pl.z_dir")
    pr = prisms(plan)
    vol = lambda p: abs(_area2(p[1])) * (p[3] - p[2])
    outer = sorted([p for p in pr if p[0] == "outer"], key=lambda p: -vol(p))
    inner = sorted([p for p in pr if p[0] == "inner"], key=lambda p: (-p[3], p[2]))
    levels = {0.0: "0"}
    names = {}

    def lvl(z):
        for k, ex in levels.items():
            if abs(k - z) < 1e-7:
                return ex
        return None

    def face_code(lp, var, feat, label):
        rect = _is_rect(lp, eps)
        if lp[0][0] == "circle":
            c, r = lp[0][1], lp[0][2]
            k = S.param(f"{feat}_d", 2 * r, f"{label} diameter", feat, "computed from mesh: diameter of a round outline")
            return [f"{var} = make_face(Wire([Edge.make_circle({k} / 2, Plane(origin=P{_v(c)}, x_dir=pl.x_dir, z_dir=pl.z_dir))]))"]
        if rect:
            x0, y0, W, H = rect
            kw = S.param(f"{feat}_x", W, f"{label} length along x", feat, "computed from mesh: size of a rectangular outline")
            kh = S.param(f"{feat}_y", H, f"{label} length along y", feat, "computed from mesh: size of a rectangular outline")
            px = lambda k: k if abs(x0) < 5e-7 else f"{_f(x0)} + {k}"
            py = lambda k: k if abs(y0) < 5e-7 else f"{_f(y0)} + {k}"
            return [f"{var} = make_face(Wire(Polyline(P({_f(x0)}, {_f(y0)}), P({px(kw)}, {_f(y0)}), "
                    f"P({px(kw)}, {py(kh)}), P({_f(x0)}, {py(kh)}), close=True).edges()))"]
        lines = _loop_lines(lp, "e", lambda q: f"P{_v(q)}", S)
        return lines + [f"{var} = make_face(Wire(e))"]

    for k, (_, lp, z0, z1) in enumerate(outer):
        feat = "base" if k == 0 else f"step{k}"
        label = "Base" if k == 0 else f"Step {k}"
        S.feature(feat, label, ROLE["base" if k == 0 else "step"],
                  "An extrusion of an outline read off the mesh" + ("" if k == 0 else ", added to the base") + ".")
        lo = lvl(z0)
        if lo is None:
            lo = _f(z0)
        hi = lvl(z1)
        amount = None
        if hi is None:
            kh = S.param(f"{feat}_h", z1 - z0, f"{label} height", feat, "computed from mesh: distance between its end faces")
            hi = f"({lo} + {kh})" if lo != "0" else kh
            levels[z1] = hi
            amount = kh
        S.add(*face_code(lp, "f", feat, label))
        S.add(f"solid = {_at(lo)}extrude(f, amount={amount or _minus(hi, lo)}, dir=D)",
              "body = solid" if k == 0 else "body = body + solid",
              f"stages.append(Stage({feat!r}, body))")
        names[feat] = (lp, z0, z1)
    S.stack = {"d": d, "s0": float(plan["o"] @ d), "levels": levels}
    for k, (_, lp, z0, z1) in enumerate(inner, 1):
        lo, hi = lvl(z0), lvl(z1)
        through = lo is not None and hi is not None
        feat = f"cutout{k}" if through else f"pocket{k}"
        label = f"Cutout {k}" if through else f"Pocket {k}"
        S.feature(feat, label, ROLE["pocket"], "A recess cut into the outline above or below it." if not through else
                  "An opening through the outline.")
        amount = None
        if hi is not None and lo is None:
            kd = S.param(f"{feat}_depth", z1 - z0, f"{label} depth", feat, "computed from mesh: depth below the face it opens in")
            lo, amount = f"({hi} - {kd})", kd
        elif lo is not None and hi is None:
            kd = S.param(f"{feat}_depth", z1 - z0, f"{label} depth", feat, "computed from mesh: depth above the face it opens in")
            hi, amount = f"({lo} + {kd})", kd
        elif lo is None and hi is None:
            lo, hi = _f(z0), _f(z1)
        S.add(*face_code(lp, "f", feat, label))
        S.add(f"body = body - {_at(lo)}extrude(f, amount={amount or _minus(hi, lo)}, dir=D)",
              f"stages.append(Stage({feat!r}, body))")


def _revolve_source(S, plan, eps):
    o, a, u = plan["o"], plan["a"], plan["u"]
    loop = plan["loop"]
    S.feature("base", "Base", ROLE["base"], "A revolution of a profile read off the mesh.")
    zmin = min(float(q[1]) for e in loop for q in e[1:])
    o = o + zmin * a                                  # the profile starts at z = 0
    loop = [(e[0],) + tuple(np.array([q[0], q[1] - zmin]) for q in e[1:]) for e in loop]
    plan = {**plan, "rounds": [(k, np.array([c[0], c[1] - zmin]), sz) for k, c, sz in plan.get("rounds", [])]}
    rs = sorted({round(float(e[k][0]), 6) for e in loop for k in (1, 2) if e[0] == "line"
                 and abs(e[1][0] - e[2][0]) < eps and abs(e[1][0]) > eps})
    zs = sorted({round(float(e[k][1]), 6) for e in loop for k in (1, 2) if e[0] == "line" and abs(e[1][1] - e[2][1]) < eps})
    z0 = 0.0
    rkey, zkey = {}, {}
    for i, r in enumerate(rs, 1):
        rkey[r] = S.param(f"d{i}", 2 * r, f"Diameter {i}", "base", "computed from mesh: diameter of a turned surface")
    for z in zs:
        if abs(z - z0) < 1e-6:
            continue
        zkey[z] = S.param(f"h{len(zkey) + 1}", z - z0, f"Height {len(zkey) + 1}", "base",
                          "computed from mesh: height of a face across the axis above the lowest one")

    def rz(q):
        r, z = float(q[0]), float(q[1])
        rk = next((k for rr, k in rkey.items() if abs(rr - r) < eps), None)
        zk = next((k for zz, k in zkey.items() if abs(zz - z) < eps), None)
        rs_ = f"{rk} / 2" if rk else _f(r)
        zs_ = zk if zk else _f(z)
        return f"({rs_}, 0, {zs_})"
    S.add(*_loop_lines(loop, "e", rz, S))
    place = f"Location(Plane(origin={_v(o)}, x_dir={_v(u)}, z_dir={_v(a)}))"
    S.add("prof = make_face(Wire(e))",
          f"body = {place} * revolve(prof, Axis.Z)",
          "stages.append(Stage('base', body))")
    groups = {}
    for kind, corner, size in plan.get("rounds", []):
        groups.setdefault((kind, round(size, 3)), []).append((corner, size))
    count = {"fillet": 0, "chamfer": 0}
    for (kind, _), items in sorted(groups.items()):
        count[kind] += 1
        fid = f"{kind}{count[kind]}"
        label = f"{'Fillet' if kind == 'fillet' else 'Chamfer'} {count[kind]}"
        val = float(np.mean([s for _, s in items]))
        S.feature(fid, label, ROLE[kind], f"{len(items)} turned edge{'s' if len(items) > 1 else ''}, "
                  f"{'rounded' if kind == 'fillet' else 'bevelled'} in the profile.")
        key = S.param(f"{fid}_{'r' if kind == 'fillet' else 'd'}", val, f"{label} {'radius' if kind == 'fillet' else 'distance'}",
                      fid, "computed from mesh: " + ("radius of the fitted torus" if kind == "fillet" else
                                                     "distance from the sharp corner along the profile"),
                      lo=round(val * 0.05, 4), hi=round(val * 3 + 1, 4))
        pts = ", ".join(rz(c) for c, _ in items)
        S.add(f"prof = {kind}(vertices_near(prof, [{pts}], within={_f(max(2 * val, 0.5))}), {key})",
              f"body = {place} * revolve(prof, Axis.Z)",
              f"stages.append(Stage({fid!r}, body))")
        S.profile_rounds = getattr(S, "profile_rounds", []) + [{"kind": kind, "feature": fid, "size_mm": round(val, 4),
                                                                "edges": len(items)}]


def _embedded_source(S, ref):
    S.feature("base", "Base", ROLE["base"], "The solid under the features, kept exactly as reconstructed (Layer 1 faces).")
    k = S.param("scale_pct", 100, "Base scale", "base", "100 = the size of the mesh", lo=1, hi=1000, step=0.1, unit="%")
    S.add(f"body = self.reference({ref!r})",
          f"if abs({k} - 100) > 1e-9:",
          f"    body = body.scale({k} / 100)",
          "stages.append(Stage('base', body))")


def _sharp_point(G, f):
    """A point on the sharp edge a fillet or chamfer replaced: nearest to the face's middle, on both rail planes."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    g = f["groups"][0]
    i0 = G.groups[g][0]
    p = G.info[i0]["pt"]
    qs, ns = [], []
    for h in f["rails"][:2]:
        best = None
        for ei in G.gnb(g).get(h, []):
            dd = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex(), G.edges[ei][0])
            if dd.IsDone() and dd.NbSolution() and (best is None or dd.Value() < best[0]):
                best = (dd.Value(), gmod._np(dd.PointOnShape2(1)))
        if best is None:
            return None
        q = best[1]
        j = next(j for j in G.groups[h])
        qs.append(q)
        ns.append(G.normal_at(j, q))
    n1, n2 = ns
    A = np.array([[n1 @ n1, n1 @ n2], [n1 @ n2, n2 @ n2]])
    b = np.array([n1 @ (p - qs[0]), n2 @ (p - qs[1])])
    try:
        lam = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return None
    x = p - lam[0] * n1 - lam[1] * n2
    dist = [abs(float(np.linalg.norm(x - q))) for q in qs]
    return x, dist


def _finish_source(S, G, fils, chams, report):
    """Fillets and chamfers on the edges nearest where they were; one Param per radius or distance."""
    for kind, fs in (("chamfer", chams), ("fillet", fils)):
        groups = {}
        for f in fs:
            sp = _sharp_point(G, f)
            if sp is None:
                report.append({**_brief(f), "why": "its sharp edge could not be located"})
                continue
            f["sharp"], f["dist"] = sp
            size = f["r"] if kind == "fillet" else float(np.mean(f["dist"]))
            key = (round(size, 3), id(f) if f.get("solo") else 0)    # one op per edge once a shared op has failed
            groups.setdefault(key, []).append(f)
        for k, (size, grp) in enumerate(sorted(groups.items()), 1):
            vals = [f["r"] if kind == "fillet" else float(np.mean(f["dist"])) for f in grp]
            val = float(np.mean(vals))
            fid = f"{kind}{k}"
            label = f"{'Fillet' if kind == 'fillet' else 'Chamfer'} {k}"
            S.feature(fid, label, ROLE[kind], f"{len(grp)} edge{'s' if len(grp) > 1 else ''}, found where the "
                      f"{'rounded' if kind == 'fillet' else 'bevelled'} faces were.")
            note = ("computed from mesh: radius of the fitted round" if kind == "fillet"
                    else "computed from mesh: distance from the sharp edge to each side of the bevel")
            key = S.param(f"{fid}_{'r' if kind == 'fillet' else 'd'}", val, f"{label} {'radius' if kind == 'fillet' else 'distance'}",
                          fid, note, lo=round(val * 0.05, 4), hi=round(val * 3 + 1, 4))
            pts = ", ".join(_v(f["sharp"]) for f in grp)
            within = round(max(val * 2, 0.5), 3)
            S.add(f"body = {kind}(edges_near(body, [{pts}], within={_f(within)}), {key})",
                  f"stages.append(Stage({fid!r}, body))")
            for f in grp:
                f["feature"] = fid


def _hole_key(h):
    return (tuple((s[0],) + tuple(round(x, 4) for x in s[1:]) for s in h["steps"]), tuple(np.round(_canon(h["dir"]), 5)),
            h["through"], h["tip_angle"] and round(h["tip_angle"], 2), tuple(np.round(h["dir"], 5)))


def free_run(V, F, p, d, cap):
    """How far a ray from p along d goes before it meets the mesh (at most cap)."""
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    e1, e2 = B - A, C - A
    h = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(det) > 1e-14
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    sv = p - A
    uu = np.einsum("ij,ij->i", sv, h) * inv
    q = np.cross(sv, e1)
    vv = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (uu >= -1e-9) & (vv >= -1e-9) & (uu + vv <= 1 + 1e-9) & (t > 1e-6)
    return float(min(t[hit].min(), cap)) if hit.any() else float(cap)


def _overshoot(V, F, grp, size):
    """Overshoot before the entry and past the far end that stays in air (so a hole stays open when a face moves),
    measured along each hole of the group on the mesh."""
    if V is None:
        return 1.0, 1.0
    cap = 0.5 * size
    o_in, o_out = cap, cap
    for h in grp:
        d = _unit(h["dir"])
        L = sum(s[-1] for s in h["steps"])
        o_in = min(o_in, free_run(V, F, h["origin"] - 1e-4 * d, -d, cap))
        if h["through"]:
            o_out = min(o_out, free_run(V, F, h["origin"] + (L + 1e-4) * d, d, cap))
    return max(1.0, round(0.9 * o_in, 3)), max(1.0, round(0.9 * o_out, 3))


def _level_shift(S, grp):
    """Code for how far a group of holes along the stack direction moves when the level it enters at changes, or ""."""
    st = getattr(S, "stack", None)
    if not st:
        return ""
    d = st["d"]
    zs = set()
    for h in grp:
        if abs(abs(h["dir"] @ d) - 1) > 1e-7:
            return ""
        zs.add(round(float(h["origin"] @ d) - st["s0"], 6))
    if len(zs) != 1:
        return ""
    z = zs.pop()
    ex = next((e for k, e in st["levels"].items() if abs(k - z) < 1e-6), None)
    if not ex or "v[" not in ex:
        return ""
    return f"D * ({ex} - {_f(z)})"


def _holes_source(S, hs, tol, V=None, F=None, size=100.0):
    groups = {}
    for h in hs:
        groups.setdefault(_hole_key(h), []).append(h)
    for k, (key, grp) in enumerate(groups.items(), 1):
        h0 = grp[0]
        fid = f"hole{k}"
        n = len(grp)
        steps = h0["steps"]
        last = steps[-1]
        d_main = last[1] if last[0] == "cyl" else last[2]
        snap = holemod.snap(d_main, within=max(2 * tol, 0.02))
        kind = "hole"
        if len(steps) == 2 and steps[0][0] == "cyl" and steps[1][0] == "cyl" and steps[0][1] > steps[1][1]:
            kind = "counterbored hole"
        elif len(steps) == 2 and steps[0][0] == "cone" and steps[1][0] == "cyl":
            kind = "countersunk hole"
        label = f"Hole {k}" + (f" ({n}×)" if n > 1 else "")
        S.feature(fid, label, ROLE["hole"], f"{n} {kind}{'s' if n > 1 else ''}, "
                  f"{'through' if h0['through'] else 'blind'}; Ø{snap['measured_mm']:.3f} mm measured"
                  + (f", {snap['standard']}" if snap.get("standard") else "") + ".")
        kd = S.param(f"{fid}_d", snap["diameter_mm"], f"{label} diameter", fid,
                     f"computed from mesh: Ø{snap['measured_mm']:.3f} mm measured" + (f", snapped to {snap['standard']}" if snap.get("standard") else ""))
        code_steps = []
        for i, st in enumerate(steps):
            final = i == len(steps) - 1
            if st[0] == "cyl":
                dcode = kd if final else S.param(f"{fid}_cbore_d" if i == 0 else f"{fid}_step{i}_d", st[1],
                                                 f"{label} counterbore diameter" if i == 0 else f"{label} step {i} diameter",
                                                 fid, "computed from mesh: diameter of a wider part of the hole")
                if final and h0["through"]:
                    lcode = _f(st[2])
                else:
                    lcode = S.param(f"{fid}_depth" if final else (f"{fid}_cbore_depth" if i == 0 else f"{fid}_step{i}_depth"),
                                    st[2], f"{label} depth" if final else f"{label} counterbore depth", fid,
                                    "computed from mesh: depth along the hole's axis")
                code_steps.append(f"({dcode}, {lcode})")
            else:
                _, d0, d1, L = st
                ang = 2 * math.degrees(math.atan2(abs(d0 - d1) / 2, L))
                if i == 0 and not final:
                    kc = S.param(f"{fid}_csink_d", d0, f"{label} countersink diameter", fid,
                                 f"computed from mesh: top diameter of a {ang:.1f}° countersink")
                    nxt = steps[i + 1]
                    dn = kd if i + 1 == len(steps) - 1 else _f(nxt[1])
                    code_steps.append(f"('cone', {kc}, {dn}, ({kc} - {dn}) / 2 / math.tan(math.radians({_f(ang)} / 2)))")
                else:
                    code_steps.append(f"('cone', {_f(d0)}, {_f(d1)}, {_f(L)})")
        tip = f", tip_angle={_f(h0['tip_angle'])}" if h0["tip_angle"] else ""
        shift = _level_shift(S, grp)                   # a hole entering a face whose height is a Param moves with it
        wrap = (lambda c: f"Vector(*{c}) + {shift}") if shift else (lambda c: c)
        o_in, o_out = _overshoot(V, F, grp, size)
        thr = (f", through=True, overshoot={_f(o_in)}, beyond={_f(o_out)}" if h0["through"]
               else (f", overshoot={_f(o_in)}" if o_in != 1.0 else ""))
        steps_code = "[" + ", ".join(code_steps) + "]"
        pat = None
        if n >= 2:
            a = _canon(h0["dir"])
            C = np.array([h["origin"] - (h["origin"] @ a) * a for h in grp])
            pat = _grid(C, tol) or (_polar(C, a, tol) if n >= 3 else None)
        s_ax = float(h0["origin"] @ _canon(h0["dir"]))
        a = _canon(h0["dir"])
        if pat and pat["kind"] in ("grid", "line"):
            p1 = S.param(f"{fid}_pitch1", pat["pitch1_mm"], f"{label} pitch", fid, "computed from mesh: spacing of the hole centres",
                         lo=round(pat["pitch1_mm"] * 0.25, 4)) if pat["n1"] > 1 else "0"
            p2 = S.param(f"{fid}_pitch2", pat["pitch2_mm"], f"{label} second pitch", fid,
                         "computed from mesh: spacing of the hole centres", lo=round(pat["pitch2_mm"] * 0.25, 4)) if pat["n2"] > 1 else "0"
            centre = pat["centre"] + s_ax * a
            S.add(f"for i in range({pat['n1']}):",
                  f"    for j in range({pat['n2']}):",
                  f"        c = tuple(s + (i - {_f((pat['n1'] - 1) / 2)}) * {p1} * e1 + (j - {_f((pat['n2'] - 1) / 2)}) * {p2} * e2"
                  f" for s, e1, e2 in zip({_v(centre)}, {_v(pat['e1'])}, {_v(pat['e2'])}))",
                  f"        body = body - hole({wrap('c')}, {_v(h0['dir'])}, {steps_code}{thr}{tip})")
        elif pat and pat["kind"] == "polar":
            kp = S.param(f"{fid}_pcd", pat["pcd_mm"], f"{label} pitch circle diameter", fid,
                         "computed from mesh: circle through the hole centres")
            S.add(f"for k in range({pat['n']}):",
                  f"    t = math.radians({_f(pat['start_deg'])} + k * 360 / {pat['n']})",
                  f"    c = tuple(cc + {kp} / 2 * (math.cos(t) * uu + math.sin(t) * ww) + {_f(s_ax)} * ax"
                  f" for cc, uu, ww, ax in zip({_v(pat['centre'])}, {_v(pat['u'])}, {_v(pat['w'])}, {_v(a)}))",
                  f"    body = body - hole({wrap('c')}, {_v(h0['dir'])}, {steps_code}{thr}{tip})")
        else:
            for h in grp:
                S.add(f"body = body - hole({wrap(_v(h['origin']))}, {_v(h['dir'])}, {steps_code}{thr}{tip})")
        S.add(f"stages.append(Stage({fid!r}, body))")
        for h in grp:
            h["feature"] = fid
        h0["pattern"] = (pat or {}).get("kind", "single" if n == 1 else "set")
        rec = {"feature": fid, "kind": h0["pattern"], "holes": n, "diameter_mm": snap["diameter_mm"]}
        if pat and pat["kind"] == "polar":
            rec.update({"n": pat["n"], "pcd_mm": round(pat["pcd_mm"], 4)})
        elif pat:
            rec.update({"n1": pat["n1"], "n2": pat["n2"], "pitch1_mm": round(pat["pitch1_mm"], 4), "pitch2_mm": round(pat["pitch2_mm"], 4)})
        S.patterns = getattr(S, "patterns", []) + [rec]


# ---- the layer -------------------------------------------------------------------------------------------------------

def _build(src):
    """Build a design source as the Studio does. Returns the final shape; an exception carries `.line`, the line of
    the source it came from (None when it did not come from the source)."""
    import tempfile
    from ..recipes import SOURCE_PREFIX, load_source, source_id
    rid = source_id(src)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"{rid[len(SOURCE_PREFIX):]}.py"
        p.write_text(src, encoding="utf-8")
        try:
            rec = load_source(p, rid)
            stages = rec.build(rec.validate(rec.defaults()))
        except Exception as e:                         # noqa: BLE001
            e.line = next((fr.lineno for fr in reversed(traceback.extract_tb(e.__traceback__)) if fr.filename == str(p)), None)
            raise
    return stages[-1].shape


def _verify(src, V, F, tol, refs):
    from . import solid, verify
    from ..recipes import meshsolid
    meshsolid.set_paths(refs)
    try:
        shape = _build(src)
    finally:
        meshsolid.set_paths({})
    ck = solid.check(shape.wrapped)
    P, T = solid.tessellate(shape, max(tol / 10, 1e-4))
    cmp = verify.compare(V, F, P, T)
    return shape, ck, P, T, cmp


def _blame(G, feats, P, dev, limit):
    """Features near the places where the rebuilt part is outside the limit."""
    bad = P[dev > limit]
    if not len(bad):
        return []
    out = []
    for f in feats:
        pts = np.array([G.info[i]["center"] for i in f["faces"]] + [G.info[i]["pt"] for i in f["faces"]])
        if f.get("sharp") is not None:
            pts = np.vstack([pts, f["sharp"]])
        reach = 3 * (f.get("r") or 0) + 2.0
        if f["kind"] == "hole":
            reach = max(s[1] if s[0] == "cyl" else s[1] for s in f["steps"]) + 1.0
        d = np.min(np.linalg.norm(bad[:, None, :] - pts[None, :, :], axis=2), axis=1)
        if np.any(d < reach):
            out.append(f)
    return out


def _on_axis(G, f, o, a, eps):
    """Is this feature round the axis (o, a): a bore on it, a torus fillet or a cone chamfer of a turned edge?"""
    if f["kind"] == "hole":
        return abs(abs(f["dir"] @ a) - 1) < 1e-7 and np.linalg.norm(np.cross(f["origin"] - o, a)) < eps
    d = G.info[f["faces"][0]]
    if d["kind"] not in ("torus", "cone"):
        return False
    return abs(abs(d["a"] @ a) - 1) < 1e-7 and np.linalg.norm(np.cross(d["o"] - o, a)) < eps


def _revolve_keeping(shape, G, feats, eps):
    """A revolution read straight off the solid: the features round its axis stay in the profile, the holes off it
    are cut afterwards (their faces are skipped when the profile is read)."""
    tried = []
    for gi in sorted(range(len(G.groups)), key=lambda g: -G.ginfo(g)["area"])[:12]:
        d = G.ginfo(gi)
        if d["kind"] not in ("cylinder", "cone", "torus"):
            continue
        o, a = d["o"], _canon(d["a"])
        if any(abs(abs(a @ b) - 1) < 1e-7 and np.linalg.norm(np.cross(o - p, b)) < eps for p, b in tried):
            continue
        tried.append((o, a))
        prof = [f for f in feats if _on_axis(G, f, o, a, eps)]
        others = [f for f in feats if not any(f is q for q in prof)]
        if not all(f["kind"] == "hole" for f in others):
            continue
        ignore = frozenset(i for f in others for i in f["faces"])
        k = core_kind(G, ignore)
        if k and k[0] == "revolve" and abs(abs(k[2] @ a) - 1) < 1e-7:
            return shape, others, [], G, k, prof, ignore
    return None


def _choose(shape, G, feats, tol, force_embedded):
    """Take the features off; if what is left is no simple base, try a revolution that keeps the features round its
    axis in the profile (a bore, turned fillets and chamfers) and takes off only the others.
    Returns (core, removed, kept, core graph, kind, features left in the profile)."""
    eps = 1e-5 * max(G.size, 1.0)
    if not force_embedded:                         # a turned part first: nothing needs to come off for its profile
        got = _revolve_keeping(shape, G, feats, eps)
        if got is not None:
            return got
    core, removed, kept = remove_features(shape, G, feats)
    Gc = gmod.Graph(core, tol)
    kind = None if force_embedded else core_kind(Gc)
    if kind is not None and kind[0] == "revolve":
        prof = [f for f in kept if _on_axis(G, f, kind[1], kind[2], eps)]
        return core, removed, [f for f in kept if not any(f is q for q in prof)], Gc, kind, prof, frozenset()
    if force_embedded or (kind is not None and not kept):
        return core, removed, kept, Gc, kind, [], frozenset()
    tried = []
    for gi in sorted(range(len(G.groups)), key=lambda g: -G.ginfo(g)["area"]):
        d = G.ginfo(gi)
        if d["kind"] not in ("cylinder", "cone", "torus"):
            continue
        o, a = d["o"], _canon(d["a"])
        if any(abs(abs(a @ b) - 1) < 1e-7 and np.linalg.norm(np.cross(o - p, b)) < eps for p, b in tried):
            continue
        tried.append((o, a))
        prof = [f for f in feats if _on_axis(G, f, o, a, eps)]
        if not prof:
            continue
        others = [f for f in feats if not any(f is q for q in prof)]
        if all(f["kind"] == "hole" for f in others):
            # holes off the axis need not come off: the profile is read from the faces round the axis
            ignore = frozenset(i for f in others for i in f["faces"])
            k2 = core_kind(G, ignore)
            if k2 and k2[0] == "revolve" and abs(abs(k2[2] @ a) - 1) < 1e-7:
                return shape, others, [], G, k2, prof, ignore
        core2, rem2, kept2 = remove_features(shape, G, others)
        Gc2 = gmod.Graph(core2, tol)
        k2 = core_kind(Gc2)
        if k2 and k2[0] == "revolve" and abs(abs(k2[2] @ a) - 1) < 1e-7:
            return core2, rem2, kept2, Gc2, k2, prof, frozenset()
        if len(tried) >= 4:
            break
    return core, removed, kept, Gc, kind, [], frozenset()


def recipe(V, F, shape, tol, name="part", limit=None, out_dir=None, progress=None, deadline=None) -> dict:
    """The feature-tree recipe of a Layer 1 solid. Returns {"report", "source", "verified", "shape", "P", "T", "cmp"}."""
    say = progress or (lambda d: None)
    t0 = time.perf_counter()
    limit = tol if limit is None else limit
    from .solid import check as _check
    nf = _check(shape)["faces"]
    if nf > MAX_FACES:
        return {"report": {"beta": True, "method": "feature tree", "faces": nf,
                           "error": f"The Layer 1 solid has {nf:,} faces (frozen facets, mostly); the feature search "
                                    f"stops at {MAX_FACES:,}. Layer 1 is the result."}}
    G = gmod.Graph(shape, tol)
    hs = gmod.holes(G)
    skip = {g for h in hs for g in h["groups"]}
    fils = gmod.blends(G, skip)
    chams = gmod.chamfers(G, skip | {g for f in fils for g in f["groups"]})
    rep = {"beta": True, "method": "feature tree", "limit_mm": round(limit, 6),
           "found": {"holes": len(hs), "fillets": len(fils), "chamfers": len(chams)}}
    feats = hs + fils + chams
    left_in_base = []
    force_embedded = False
    attempts = []
    result = None
    last_src = None
    for attempt in range(8):
        if deadline is not None and attempt and time.perf_counter() > deadline:
            attempts.append({"stopped": "the time budget ran out; the best attempt so far is the result"})
            break
        say({"stage": "layer2", "text": f"Taking {len(feats)} features off the solid", "fraction": 0.1 + 0.2 * attempt})
        core, removed, kept, Gc, kind, in_profile, ignore = _choose(shape, G, feats, tol, force_embedded)
        left_in_base += [{**_brief(f), "why": "it could not be taken off the solid to find the shape under it"} for f in kept]
        feats = removed + in_profile
        plan, why = None, "the core has faces neither across nor along one direction, nor round one axis"
        if kind and kind[0] == "stack":
            plan, why = stack_plan(core, Gc, kind[1])
        elif kind and kind[0] == "revolve":
            plan, why = revolve_plan(core, Gc, kind[1], kind[2], ignore)
        S = Src(name)
        refs = {}
        eps = 1e-6 * max(G.size, 1.0)
        if plan is not None and plan["kind"] == "stack":
            _stack_source(S, plan, eps)
            base = "extrusion stack"
        elif plan is not None:
            _revolve_source(S, plan, max(eps, 1e-7))
            base = "revolution"
        else:
            ref = f"{name}_base.step"
            path = Path(out_dir or ".") / ref
            from .pipeline import _step
            _step(core, path)
            refs = {ref: str(path)}
            _embedded_source(S, ref)
            base = "embedded solid"
        frep = []
        _finish_source(S, G, [f for f in removed if f["kind"] == "fillet"], [f for f in removed if f["kind"] == "chamfer"], frep)
        left_in_base += frep
        hole_feats = [f for f in removed if f["kind"] == "hole"]
        _holes_source(S, hole_feats, tol, V, F, G.size)
        doc = (f"{name}: reconstructed from a mesh by Form Studio (Layer 2, feature tree, beta).\n\n"
               f"Base: {base}{'' if base != 'embedded solid' else ' (the shape under the features, read from ' + next(iter(refs)) + ')'}; "
               f"then {len(removed)} features. Every Param value is computed from the mesh (hole sizes snapped to "
               "standard sizes within reach); outline coordinates are read off the mesh.")
        src = S.text(doc)
        say({"stage": "layer2", "text": "Building the feature tree and comparing it with the mesh", "fraction": 0.3 + 0.2 * attempt})
        try:
            rshape, ck, P, T, cmp = _verify(src, V, F, tol, refs)
        except Exception as e:                         # noqa: BLE001
            line = getattr(e, "line", None)
            fid = S.feature_at(line) if line else None
            attempts.append({"base": base, "features": len(removed), "error": f"{type(e).__name__}: {e}"[:300], "feature": fid})
            last_src = src
            culprit = [f for f in removed if f.get("feature") == fid] if fid else []
            if fid == "base" or (fid and fid.startswith(("step", "pocket", "cutout"))):
                force_embedded = True
                continue
            # a fillet or chamfer op on several edges failed: try its edges one by one before giving any up, so one
            # edge that will not round does not take the others (or the whole tree) with it
            finish = culprit if culprit else ([f for f in removed if f["kind"] in ("fillet", "chamfer")]
                                              if any(w in str(e).lower() for w in ("fillet", "chamfer")) else [])
            if finish and (len(finish) > 1 or not culprit) and not all(f.get("solo") for f in finish):
                for f in finish:
                    f["solo"] = True
                continue
            if culprit:
                left_in_base += [{**_brief(f), "why": f"its operation failed: {type(e).__name__}"} for f in culprit]
                feats = [f for f in feats if not any(f is c for c in culprit)]
                continue
            if not force_embedded:
                force_embedded = True
                continue
            break
        ok = ck["valid"] and ck["solids"] == 1 and cmp["hausdorff_mm"] <= limit
        attempts.append({"base": base, "features": len(removed), "hausdorff_mm": round(cmp["hausdorff_mm"], 6),
                         "valid": ck["valid"]})
        plan_axis = (plan["o"], plan["a"]) if plan is not None and plan["kind"] == "revolve" else None
        result = (src, rshape, ck, P, T, cmp, base, removed, refs, ok, S, in_profile, core, plan_axis)
        if ok:
            break
        culprit = _blame(G, removed, P, cmp["_rec_dev"], limit)
        if culprit and len(culprit) < len(removed) + 1:
            left_in_base += [{**_brief(f), "why": f"put back, it left the part {cmp['hausdorff_mm']:.4f} mm from the mesh"} for f in culprit]
            feats = [f for f in feats if not any(f is c for c in culprit)]
            continue
        if not force_embedded and base != "embedded solid":
            force_embedded = True
            continue
        break
    rep["attempts"] = attempts
    rep["left_in_base"] = left_in_base
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    if result is None:
        rep["error"] = "The feature tree did not build. " + (attempts[-1].get("error", "") if attempts else "")
        return {"report": rep, "source": last_src}
    src, rshape, ck, P, T, cmp, base, removed, refs, ok, S, in_profile, core, plan_axis = result
    rep["driven_by_params_pct"] = 100.0 if base != "embedded solid" else _driven_share(rshape.wrapped, core, tol)
    rep.update({"kind": "feature tree", "base": base, "valid": ck["valid"], "solids": ck["solids"],
                "volume_mm3": round(ck["volume_mm3"], 4), "verified": bool(ok),
                **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in cmp.items() if not k.startswith("_")}})
    rep["features"] = _feature_report(removed, tol)
    rep["patterns"] = getattr(S, "patterns", [])
    try:
        from .features import symmetry
        axis = (plan_axis[0], plan_axis[1]) if plan_axis is not None else None
        rep["symmetry"] = symmetry(V, F, tol, axis)
    except Exception:                                  # noqa: BLE001
        rep["symmetry"] = []
    for f in in_profile:
        if f["kind"] == "hole" and base == "revolution":
            d = _feature_report([f], tol)[0]
            d.update({"kind": "bore", "feature": "base", "in_profile": True})
            rep["features"].append(d)
    for r in getattr(S, "profile_rounds", []):
        rep["features"].append({"kind": r["kind"], "feature": r["feature"], "provenance": "computed from mesh", "in_profile": True,
                                ("radius_mm" if r["kind"] == "fillet" else "distance_mm"): r["size_mm"], "edges": r["edges"]})
    rep["holes"] = [h for h in rep["features"] if h["kind"] == "hole"]
    if refs:
        rep["base_file"] = next(iter(refs))
    if not ok:
        rep["error"] = (f"The feature tree builds, but it is {cmp['hausdorff_mm']:.4f} mm from the mesh (limit {limit:.4f} mm)"
                        if ck["valid"] else "The feature tree builds an invalid solid.")
    return {"report": rep, "source": src, "verified": ok, "shape": rshape.wrapped, "P": P, "T": T, "cmp": cmp, "refs": refs}


def _driven_share(shape, core, tol):
    """Share of the surface area that the recipe's Params drive, when the base is the embedded core: the faces that
    are not on the core (made by a feature: a hole wall, a fillet, a chamfer)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from . import distance, solid
    Pc, Tc = solid.tessellate(core, max(tol / 10, 1e-4))
    md = distance.MeshDistance(Pc, Tc)
    tot = drv = 0.0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(ex.Current(), g)
        Pf, Tf = solid.tessellate(ex.Current(), max(tol / 10, 1e-4))
        a = g.Mass()
        tot += a
        if len(Tf):
            S, _, _ = distance.sample_surface(Pf, Tf, max(float(np.sqrt(a / 400)), 1e-3))   # spread over the face
            if float(np.median(md.closest(S)[0])) > 2 * tol:
                drv += a
        ex.Next()
    return round(100 * drv / tot, 2) if tot else 0.0


def _feature_report(fs, tol):
    out = []
    for f in fs:
        d = {"kind": f["kind"], "feature": f.get("feature"), "provenance": "computed from mesh"}
        if f["kind"] == "hole":
            last = f["steps"][-1]
            dm = last[1] if last[0] == "cyl" else last[2]
            sz = holemod.snap(dm, within=max(2 * tol, 0.02))
            d.update({"diameter_mm": sz["diameter_mm"], "measured_mm": sz["measured_mm"], "standard": sz["standard"],
                      "through": f["through"], "axis": [round(float(x), 6) for x in f["dir"]],
                      "at": [round(float(x), 4) for x in f["origin"]],
                      "steps": [[s[0]] + [round(float(x), 4) for x in s[1:]] for s in f["steps"]],
                      "pattern": f.get("pattern")})
            if f["tip_angle"]:
                d["tip_angle_deg"] = round(f["tip_angle"], 2)
        elif f["kind"] == "fillet":
            d.update({"radius_mm": round(f["r"], 4), "convex": bool(f["convex"])})
        else:
            d.update({"distance_mm": round(float(np.mean(f.get("dist", [f["width"] / math.sqrt(2)] * 2))), 4)})
        out.append(d)
    return out
