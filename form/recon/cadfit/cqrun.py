"""CADFit's CadQuery scripts, read and built with build123d: never run as a program.

CADFit (vendor/) writes small CadQuery scripts for every candidate it tries and, upstream, runs each one in a Python
subprocess. Form Studio has no CadQuery (its OCP build differs from build123d's), and a generated script is code. So the
script is parsed (ast) and only this subset is accepted, one statement at a time:

    import cadquery as cq / import math              ignored
    name = (x, y, z)                                 a tuple of numbers
    name = cq.Plane(origin=, normal=, xDir=)         a sketch plane (xDir may be left out)
    name = cq.Workplane(plane)
    name = w.moveTo(x, y) .lineTo(x, y) .threePointArc((x, y), (x, y)) .circle(r) .close() .add(other)
    name = w.extrude(h)                              h may be negative (along -normal)
    name = w.revolve(angleDegrees=, axisStart=(x, y, z), axisEnd=(x, y, z))     axis in the plane's coordinates
    name = a.union(b) / a.cut(b)
    cq.exporters.export(result, 'path.stl')          only into the folder set by allow()
    open('path', 'w').close()                        an empty file (CADFit's "no solid"), same folder rule
    print(...)                                       ignored

Anything else (a call, attribute, loop, name it does not know) raises Unsupported and the candidate fails, as a
failing CadQuery script would. `program(text)` returns the same script as a tree of operations, for the translation to
Form Studio Params (translate.py). Part of the CADFit folder: see PERMISSION.md.
"""
from __future__ import annotations

import ast
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT: list[Path | None] = [None]
STL_TOL = (2e-3, 0.1)              # linear and angular deflection of the STL export (CADFit works in a [-1, 1] box)


class Unsupported(ValueError):
    """The script uses something outside the subset."""


def allow(folder) -> None:
    """The only folder exports may write into (the candidate's work folder). None: no export is allowed."""
    _ROOT[0] = Path(folder).resolve() if folder else None


def _target(p) -> Path:
    if not isinstance(p, str):
        raise Unsupported("an export path must be a string")
    root = _ROOT[0]
    path = Path(p).resolve()
    if root is None or (path != root and root not in path.parents):
        raise Unsupported(f"export outside the work folder refused: {p}")
    return path


# ---------------------------------------------------------------- the model a script builds

@dataclass
class Plane:
    origin: np.ndarray
    x: np.ndarray
    n: np.ndarray

    @property
    def y(self):
        return np.cross(self.n, self.x)

    def world(self, p):
        p = list(p) + [0.0] * (3 - len(p))
        return self.origin + p[0] * self.x + p[1] * self.y + p[2] * self.n


def _plane(origin, normal, xdir=None) -> Plane:
    o = np.asarray(origin, dtype=float)
    n = np.asarray(normal, dtype=float)
    if np.linalg.norm(n) < 1e-12:
        raise Unsupported("a plane with no normal")
    n = n / np.linalg.norm(n)
    if xdir is None:                                    # CadQuery's choice for a plane given by its normal only
        ref = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        xdir = np.cross(ref, n) if abs(n[2]) < 0.9 else ref - n * float(ref @ n)
    x = np.asarray(xdir, dtype=float)
    x = x - n * float(x @ n)                            # CADFit rounds to 5 decimals: make it exactly orthogonal
    if np.linalg.norm(x) < 1e-9:
        raise Unsupported("a plane's x direction is along its normal")
    return Plane(o, x / np.linalg.norm(x), n)


@dataclass
class Loop:
    """A closed outline in a plane's coordinates: segments ("line", p0, p1) | ("arc", p0, pm, p1), or a circle."""
    segs: list = field(default_factory=list)
    circle: tuple | None = None                         # (cx, cy, r)

    def points(self, n_arc=12):
        if self.circle is not None:
            cx, cy, r = self.circle
            t = np.linspace(0, 2 * math.pi, 48, endpoint=False)
            return np.c_[cx + r * np.cos(t), cy + r * np.sin(t)]
        pts = []
        for s in self.segs:
            if s[0] == "line":
                pts.append(s[1])
            else:
                pts += list(_arc_points(s[1], s[2], s[3], n_arc)[:-1])
        return np.asarray(pts, dtype=float)

    def area(self):
        P = self.points()
        if len(P) < 3:
            return 0.0
        return float(abs(np.dot(P[:, 0], np.roll(P[:, 1], -1)) - np.dot(P[:, 1], np.roll(P[:, 0], -1))) / 2)


def _arc_points(p0, pm, p1, n):
    """Points along the circle through p0, pm, p1 from p0 to p1 passing pm (a straight line when collinear)."""
    a, b, c = (np.asarray(p, dtype=float) for p in (p0, pm, p1))
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-14:
        return np.array([a, c])
    ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
    uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
    o = np.array([ux, uy])
    r = float(np.linalg.norm(a - o))
    ang = lambda p: math.atan2(p[1] - o[1], p[0] - o[0])
    t0, tm, t1 = ang(a), ang(b), ang(c)
    ccw = lambda s, e: (e - s) % (2 * math.pi)
    if ccw(t0, tm) <= ccw(t0, t1):                     # pm lies on the counter-clockwise way from p0 to p1
        ts = t0 + np.linspace(0, ccw(t0, t1), n + 1)
    else:
        ts = t0 - np.linspace(0, ccw(t1, t0), n + 1)
    return np.c_[o[0] + r * np.cos(ts), o[1] + r * np.sin(ts)]


@dataclass
class Op:
    """A tree: ("extrude", plane, loops, h) | ("revolve", plane, loops, a0, a1, angle) | ("add" | "union" | "cut", a, b)."""
    node: tuple

    def leaves(self):
        out = []

        def walk(t):
            if t[0] in ("extrude", "revolve"):
                out.append(t)
            else:
                walk(t[1].node)
                walk(t[2].node)
        walk(self.node)
        return out


class _Ctx:
    """CadQuery's shared context: the wires a workplane chain has closed, waiting for an extrude or revolve."""

    def __init__(self, plane):
        self.plane = plane
        self.pending: list[Loop] = []


class WP:
    """A CadQuery Workplane, as far as the subset needs it: a context, the open path and the point it is at, or a
    solid (an Op tree) once extruded."""

    def __init__(self, ctx, path=None, cur=None, op=None):
        self.ctx, self.path, self.cur, self.op = ctx, path, cur, op

    def _go(self, path, cur):
        return WP(self.ctx, path, cur, self.op)

    def moveTo(self, x=0.0, y=0.0):
        return self._go(None, (float(x), float(y)))

    def lineTo(self, x, y):
        cur = self.cur or (0.0, 0.0)
        path = (self.path or []) + [("line", cur, (float(x), float(y)))]
        return self._go(path, path[-1][2])

    def threePointArc(self, pm, p1):
        cur = self.cur or (0.0, 0.0)
        path = (self.path or []) + [("arc", cur, _pt(pm), _pt(p1))]
        return self._go(path, path[-1][3])

    def close(self):
        segs = list(self.path or [])
        if not segs:
            raise Unsupported("close() with no outline")
        start = segs[0][1]
        end = segs[-1][-1]
        if math.dist(start, end) > 1e-9:
            segs.append(("line", end, start))
        self.ctx.pending.append(Loop(segs=segs))
        return self._go(None, start)

    def circle(self, r):
        c = self.cur or (0.0, 0.0)
        if not float(r) > 0:
            raise Unsupported("a circle needs a positive radius")
        self.ctx.pending.append(Loop(circle=(c[0], c[1], float(r))))
        return self._go(None, c)

    def add(self, other):
        if not isinstance(other, WP):
            raise Unsupported("add() of something that is not a workplane")
        if other.op is None:                            # a loop of this chain: its wires are already pending
            return self
        if self.op is None:
            return WP(self.ctx, None, self.cur, other.op)
        return WP(self.ctx, None, self.cur, Op(("add", self.op, other.op)))

    def _take(self):
        loops = [lp for lp in self.ctx.pending if lp.area() > 1e-14]
        self.ctx.pending = []
        if not loops:
            raise Unsupported("nothing to extrude")
        return loops

    def extrude(self, h):
        h = float(h)
        if abs(h) < 1e-12:
            raise Unsupported("an extrusion of no height")
        return WP(_Ctx(self.ctx.plane), None, None, Op(("extrude", self.ctx.plane, self._take(), h)))

    def revolve(self, angleDegrees=360.0, axisStart=(0, 0, 0), axisEnd=(0, 1, 0)):
        return WP(_Ctx(self.ctx.plane), None, None, Op(("revolve", self.ctx.plane, self._take(), _p3(axisStart),
                                                         _p3(axisEnd), float(angleDegrees))))

    def _bool(self, other, kind):
        if not isinstance(other, WP) or self.op is None or other.op is None:
            raise Unsupported(f"{kind}() needs two solids")
        return WP(_Ctx(self.ctx.plane), None, None, Op((kind, self.op, other.op)))

    def union(self, other):
        return self._bool(other, "union")

    def cut(self, other):
        return self._bool(other, "cut")


def _pt(v):
    if not isinstance(v, (tuple, list)) or len(v) != 2:
        raise Unsupported("a point (x, y) was expected")
    return (float(v[0]), float(v[1]))


def _p3(v):
    if not isinstance(v, (tuple, list)) or len(v) != 3:
        raise Unsupported("a point (x, y, z) was expected")
    return tuple(float(x) for x in v)


# ---------------------------------------------------------------- reading the script

_WP_METHODS = {"moveTo", "lineTo", "threePointArc", "close", "circle", "add", "extrude", "revolve", "union", "cut"}


class _Reader:
    def __init__(self, export=True):
        self.env: dict = {}
        self.export = export
        self.exports: list = []

    def num(self, node):
        v = self.ev(node)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise Unsupported("a number was expected")
        return float(v)

    def ev(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = self.num(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = self.num(node.left), self.num(node.right)
            if isinstance(node.op, ast.Div) and b == 0:
                raise Unsupported("division by zero")
            return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b, ast.Div: a / b if b else 0.0}[type(node.op)]
        if isinstance(node, ast.Tuple):
            return tuple(self.ev(e) for e in node.elts)
        if isinstance(node, ast.Name):
            if node.id not in self.env:
                raise Unsupported(f"unknown name {node.id}")
            return self.env[node.id]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math" \
                and node.attr == "pi":
            return math.pi
        if isinstance(node, ast.Call):
            return self.call(node)
        raise Unsupported(f"{type(node).__name__} is not part of the subset")

    def call(self, node):
        f = node.func
        args = [self.ev(a) for a in node.args]
        kw = {k.arg: self.ev(k.value) for k in node.keywords if k.arg}
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "cq":
            if f.attr == "Plane":
                names = ("origin", "xDir", "normal")
                d = dict(zip(names, args))
                d.update(kw)
                if set(d) - set(names):
                    raise Unsupported("cq.Plane takes origin, xDir, normal")
                return _plane(d.get("origin", (0, 0, 0)), d.get("normal", (0, 0, 1)), d.get("xDir"))
            if f.attr == "Workplane":
                pl = args[0] if args else kw.get("inPlane")
                if not isinstance(pl, Plane):
                    raise Unsupported("cq.Workplane needs a cq.Plane")
                return WP(_Ctx(pl))
            raise Unsupported(f"cq.{f.attr}")
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute) and isinstance(f.value.value, ast.Name) \
                and f.value.value.id == "cq" and f.value.attr == "exporters" and f.attr == "export":
            if len(args) < 2 or not isinstance(args[0], WP) or args[0].op is None:
                raise Unsupported("export needs a solid and a path")
            self.exports.append((args[0].op, args[1]))
            if self.export:
                write_stl(args[0].op, _target(args[1]))
            return None
        if isinstance(f, ast.Attribute):
            obj = self.ev(f.value)
            if isinstance(obj, WP) and f.attr in _WP_METHODS:
                return getattr(obj, f.attr)(*args, **kw)
            raise Unsupported(f".{f.attr}()")
        if isinstance(f, ast.Name) and f.id == "print":
            return None
        raise Unsupported("a call outside the subset")

    def stmt(self, s):
        if isinstance(s, ast.Import):
            if any(a.name not in ("cadquery", "math") for a in s.names):
                raise Unsupported("only cadquery and math may be imported")
            return
        if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
            self.env[s.targets[0].id] = self.ev(s.value)
            return
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
            c = s.value
            # open('path', 'w').close(): CADFit's empty result file
            if isinstance(c.func, ast.Attribute) and c.func.attr == "close" and isinstance(c.func.value, ast.Call) \
                    and isinstance(c.func.value.func, ast.Name) and c.func.value.func.id == "open":
                a = [self.ev(x) for x in c.func.value.args]
                if len(a) != 2 or a[1] != "w":
                    raise Unsupported("open() outside the subset")
                if self.export:
                    _target(a[0]).write_bytes(b"")
                return
            self.call(c)
            return
        if isinstance(s, ast.Pass):
            return
        raise Unsupported(f"{type(s).__name__} statement")

    def run(self, text: str):
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            raise Unsupported(f"not Python: {e}") from None
        for s in tree.body:
            self.stmt(s)
        return self


def run_script(text: str) -> None:
    """Build what a CADFit script exports (into the folder set by allow()). Raises on anything outside the subset or a
    build that fails, as the CadQuery script would have."""
    _Reader(export=True).run(text)


def program(text: str) -> Op:
    """The solid a script exports last, else the one it names `result`, as an Op tree. Nothing is built."""
    r = _Reader(export=False).run(text)
    if r.exports:
        return r.exports[-1][0]
    res = r.env.get("result")
    if isinstance(res, WP) and res.op is not None:
        return res.op
    raise Unsupported("the script makes no solid")


# ---------------------------------------------------------------- building with build123d

def _bplane(pl: Plane):
    from build123d import Plane as BPlane
    return BPlane(origin=tuple(pl.origin), x_dir=tuple(pl.x), z_dir=tuple(pl.n))


def _wire(pl: Plane, lp: Loop):
    from build123d import Edge, Plane as BPlane, Wire
    if lp.circle is not None:
        cx, cy, r = lp.circle
        c = pl.world((cx, cy))
        return Wire([Edge.make_circle(r, BPlane(origin=tuple(c), x_dir=tuple(pl.x), z_dir=tuple(pl.n)))])
    edges = []
    for s in lp.segs:
        if s[0] == "line":
            a, b = pl.world(s[1]), pl.world(s[2])
            if np.linalg.norm(a - b) > 1e-12:
                edges.append(Edge.make_line(tuple(a), tuple(b)))
        else:
            a, m, b = pl.world(s[1]), pl.world(s[2]), pl.world(s[3])
            try:
                edges.append(Edge.make_three_point_arc(tuple(a), tuple(m), tuple(b)))
            except Exception:                           # noqa: BLE001 - collinear: CadQuery fails here too
                edges.append(Edge.make_line(tuple(a), tuple(b)))
    if not edges:
        raise Unsupported("an outline with no edges")
    return Wire(edges)


def _faces(pl: Plane, loops):
    """Faces from closed outlines: an outline inside an odd number of others is a hole in the smallest one around it
    (CadQuery's nesting of the wires it extrudes)."""
    from build123d import Face
    from ._compat import _inside
    pts = [lp.points() for lp in loops]
    area = [lp.area() for lp in loops]
    order = sorted(range(len(loops)), key=lambda i: -area[i])
    parent = {}
    for k, i in enumerate(order):
        for j in reversed(order[:k]):                   # the smallest larger outline that holds it
            if _inside(pts[j], pts[i][:1]).all() and _inside(pts[j], pts[i]).mean() > 0.9:
                parent[i] = j
                break
    depth = {}
    for i in order:
        depth[i] = 0 if i not in parent else depth[parent[i]] + 1
    faces = []
    for i in order:
        if depth[i] % 2:
            continue
        holes = [_wire(pl, loops[j]) for j in order if parent.get(j) == i and depth[j] == depth[i] + 1]
        faces.append(Face(_wire(pl, loops[i]), holes))
    return faces


def build(op: Op):
    """The solids an Op tree makes, as a list of build123d Solids (CadQuery's add() keeps them apart)."""
    from build123d import Axis, Solid, Vector
    t = op.node
    if t[0] == "extrude":
        pl, loops, h = t[1], t[2], t[3]
        return [Solid.extrude(f, Vector(*(pl.n * h))) for f in _faces(pl, loops)]
    if t[0] == "revolve":
        pl, loops, a0, a1, ang = t[1], t[2], t[3], t[4], t[5]
        p0, p1 = pl.world(a0), pl.world(a1)
        ax = Axis(tuple(p0), tuple(p1 - p0))
        return [Solid.revolve(f, ang, ax) for f in _faces(pl, loops)]
    a, b = build(t[1]), build(t[2])
    if t[0] == "add":
        return a + b
    from build123d import Compound
    A, B = Compound(a), Compound(b)
    r = A.fuse(B) if t[0] == "union" else A.cut(B)
    return list(r.solids())


def write_stl(op: Op, path: Path) -> None:
    from build123d import Compound, export_stl
    solids = build(op)
    if not solids:
        raise Unsupported("the script makes no solid")
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = export_stl(Compound(solids), str(path), tolerance=STL_TOL[0], angular_tolerance=STL_TOL[1])
    if ok is False or not os.path.exists(path):
        raise RuntimeError("the STL export failed")
