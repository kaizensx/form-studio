"""form.sketch2d: constrained 2D sketches whose dimensions are a design's parameters.

Draw the profile roughly, say what must hold (coincident, horizontal, tangent, equal, symmetric, ...) and name the
dimensions that drive it. The solver places the geometry; a changed dimension re-solves the sketch instead of breaking
a hand-typed list of coordinates, so the profile keeps its intent (the arc stays tangent, the slot stays centred).

    from form.sketch2d import Sketch
    s = Sketch("bracket")
    o = s.point(0, 0, fix=True)
    a, b, c = s.point(60, 0), s.point(60, 8), s.point(8, 8)
    ...
    base = s.line(o, a); s.horizontal(base)
    s.length(base, 60, "base_len", label="Base length", lo=30, hi=120)
    s.radius(fillet, 4, "inner_r")

    class Design(Recipe):
        params = s.params(feature="bracket") + [Param("depth", ...)]
        def build(self, v):
            return [Stage("bracket", extrude(s.face(v), v["depth"]))]

Entities: point, line, arc (centre, start, end; counter-clockwise from start to end), circle (centre, radius).
Constraints: coincident, horizontal, vertical, parallel, perpendicular, tangent (line-arc, arc-arc, line-circle),
equal (lengths or radii), symmetric (two points about a line), midpoint, on (a point on a line or circle), fix,
collinear, and the dimensions length, distance (point-point, point-line), hdist / vdist, radius, diameter and angle.
A named dimension is a Param (s.params()); an unnamed one is fixed.

The solver (form/sketch2d/solver.py) is plain numpy, so a sketch solves in the engine, the MCP server or the app
without the kernel. Only face() / wire() need build123d.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..recipes.base import Param, RecipeError
from . import solver as S

__all__ = ["Sketch", "SketchError", "Point", "Line", "Arc", "Circle"]


class SketchError(RecipeError):
    """A sketch that does not solve: names the constraints that conflict and the dimensions involved."""


@dataclass(eq=False)
class Point:
    sk: "Sketch"
    i: int
    x: float
    y: float
    fixed: bool = False
    name: str = ""

    def __repr__(self):
        return f"P{self.i}({self.x:g},{self.y:g})"


@dataclass(eq=False)
class Line:
    a: Point
    b: Point
    construction: bool = False
    i: int = 0

    @property
    def kind(self):
        return "line"


@dataclass(eq=False)
class Arc:
    c: Point
    s: Point
    e: Point
    construction: bool = False
    i: int = 0

    @property
    def kind(self):
        return "arc"


@dataclass(eq=False)
class Circle:
    c: Point
    r: float
    construction: bool = False
    i: int = 0
    ri: int = -1                    # index of the radius unknown in the last compiled problem

    @property
    def kind(self):
        return "circle"


@dataclass
class Dim:
    name: str
    value: float
    label: str
    unit: str
    lo: float
    hi: float
    step: float
    doc: str = ""


@dataclass
class Con:
    kind: str
    ents: tuple
    dim: Dim | None = None
    value: float | None = None       # an unnamed dimension's fixed value
    sign: float = 0.0                # side / branch chosen from the geometry as drawn, kept on every re-solve
    text: str = ""


class Solved:
    """A solved sketch: point positions and radii, by entity."""

    def __init__(self, sk: "Sketch", x, res: S.Result, values: dict):
        self.sk, self.x, self.result, self.values = sk, x, res, values
        self.pts = [(float(x[2 * p.i]), float(x[2 * p.i + 1])) for p in sk.points]

    def p(self, pt: Point) -> tuple:
        return self.pts[pt.i]

    def radius(self, e) -> float:
        if isinstance(e, Circle):
            return float(self.x[e.ri])
        cx, cy = self.p(e.c)
        sx, sy = self.p(e.s)
        return math.hypot(sx - cx, sy - cy)

    def arc_angles(self, a: Arc) -> tuple[float, float]:
        """Start and end angle (radians), end > start, counter-clockwise."""
        cx, cy = self.p(a.c)
        sx, sy = self.p(a.s)
        ex, ey = self.p(a.e)
        t0 = math.atan2(sy - cy, sx - cx)
        t1 = math.atan2(ey - cy, ex - cx)
        while t1 <= t0 + 1e-9:
            t1 += 2 * math.pi
        return t0, t1

    def arc_mid(self, a: Arc) -> tuple:
        t0, t1 = self.arc_angles(a)
        cx, cy = self.p(a.c)
        r = self.radius(a)
        tm = (t0 + t1) / 2
        return (cx + r * math.cos(tm), cy + r * math.sin(tm))

    def measure(self, name: str) -> float:
        """The current value of a named dimension (measured on the solved geometry)."""
        for c in self.sk.cons:
            if c.dim and c.dim.name == name:
                return self.sk._measure(c, self)
        raise KeyError(name)


class Sketch:
    def __init__(self, name: str = "sketch"):
        self.name = name
        self.points: list[Point] = []
        self.ents: list = []
        self.cons: list[Con] = []
        self._nominal: Solved | None = None
        self._last: Solved | None = None

    # ── entities ──────────────────────────────────────────────────────────────
    def point(self, x: float, y: float, fix: bool = False, name: str = "") -> Point:
        p = Point(self, len(self.points), float(x), float(y), fix, name)
        self.points.append(p)
        if fix:
            self.cons.append(Con("fix", (p,), value=None, text=f"fix {name or p}"))
        self._nominal = None
        return p

    def _pt(self, p) -> Point:
        if isinstance(p, Point):
            return p
        return self.point(*p)

    def line(self, a, b, construction: bool = False) -> Line:
        ln = Line(self._pt(a), self._pt(b), construction, len(self.ents))
        self.ents.append(ln)
        self._nominal = None
        return ln

    def polyline(self, *pts, close: bool = False) -> list[Line]:
        """Lines through points ((x, y) or Point), joined end to start; close joins the last to the first."""
        P = [self._pt(p) for p in pts]
        lines = [self.line(P[k], P[k + 1]) for k in range(len(P) - 1)]
        if close:
            lines.append(self.line(P[-1], P[0]))
        return lines

    def arc(self, c, s, e, construction: bool = False) -> Arc:
        """An arc round centre c from s to e, counter-clockwise. The radius follows |s - c| = |e - c| (enforced)."""
        a = Arc(self._pt(c), self._pt(s), self._pt(e), construction, len(self.ents))
        self.ents.append(a)
        self.cons.append(Con("arc", (a,), text="arc radius"))
        self._nominal = None
        return a

    def circle(self, c, r: float, construction: bool = False) -> Circle:
        ci = Circle(self._pt(c), float(r), construction, len(self.ents))
        self.ents.append(ci)
        self._nominal = None
        return ci

    # ── constraints ───────────────────────────────────────────────────────────
    def _con(self, kind, *ents, dim=None, value=None, text=""):
        c = Con(kind, ents, dim, value, text=text or kind)
        self.cons.append(c)
        self._nominal = None
        return c

    def coincident(self, p: Point, q: Point):
        return self._con("coincident", p, q)

    def fix(self, p: Point):
        p.fixed = True
        return self._con("fix", p)

    def horizontal(self, ln: Line):
        return self._con("horizontal", ln)

    def vertical(self, ln: Line):
        return self._con("vertical", ln)

    def parallel(self, l1: Line, l2: Line):
        return self._con("parallel", l1, l2)

    def perpendicular(self, l1: Line, l2: Line):
        return self._con("perpendicular", l1, l2)

    def collinear(self, l1: Line, l2: Line):
        self._con("on", l2.a, l1)
        return self._con("on", l2.b, l1)

    def tangent(self, a, b):
        """Line-arc, line-circle, arc-arc, arc-circle or circle-circle tangency. The side (or inside/outside) is the
        one the sketch was drawn with, and stays so when dimensions change."""
        if isinstance(a, Line) and isinstance(b, Line):
            raise SketchError("Two lines cannot be tangent.", self.name, "Use parallel or collinear.")
        if isinstance(b, Line):
            a, b = b, a
        return self._con("tangent", a, b)

    def equal(self, a, b):
        if isinstance(a, Line) != isinstance(b, Line):
            raise SketchError("equal() takes two lines (lengths) or two arcs/circles (radii).", self.name)
        return self._con("equal", a, b)

    def symmetric(self, p: Point, q: Point, axis: Line):
        return self._con("symmetric", p, q, axis)

    def midpoint(self, p: Point, ln: Line):
        return self._con("midpoint", p, ln)

    def on(self, p: Point, e):
        return self._con("on", p, e)

    # dimensions: a name makes it a parameter
    def _dim(self, name, value, label, unit, lo, hi, step, doc):
        if not name:
            return None
        if any(c.dim and c.dim.name == name for c in self.cons):
            raise SketchError(f"Sketch {self.name}: the dimension name {name!r} is used twice.", self.name,
                              "Give every dimension its own name.", [name])
        v = float(value)
        if unit == "°":
            lo = max(0.0, v - 45) if lo is None else lo
            hi = min(180.0, v + 45) if hi is None else hi
        else:
            lo = round(v * 0.5, 3) if lo is None else lo
            hi = round(v * 1.6, 3) if hi is None else hi
        return Dim(name, v, label or name.replace("_", " ").capitalize(), unit, float(lo), float(hi), float(step), doc)

    def length(self, ln: Line, value: float, name: str = "", label: str = "", lo=None, hi=None, step: float = 0.1, doc=""):
        return self._con("length", ln, dim=self._dim(name, value, label, "mm", lo, hi, step, doc), value=float(value),
                         text=f"length {name or value}")

    def distance(self, p: Point, q, value: float, name: str = "", label: str = "", lo=None, hi=None, step: float = 0.1,
                 doc=""):
        """Point-point distance, or point-line distance when q is a Line."""
        kind = "pldist" if isinstance(q, Line) else "distance"
        return self._con(kind, p, q, dim=self._dim(name, value, label, "mm", lo, hi, step, doc), value=float(value),
                         text=f"distance {name or value}")

    def hdist(self, p: Point, q: Point, value: float, name: str = "", label: str = "", lo=None, hi=None, step=0.1, doc=""):
        """q.x - p.x = value."""
        return self._con("hdist", p, q, dim=self._dim(name, value, label, "mm", lo, hi, step, doc), value=float(value),
                         text=f"horizontal distance {name or value}")

    def vdist(self, p: Point, q: Point, value: float, name: str = "", label: str = "", lo=None, hi=None, step=0.1, doc=""):
        """q.y - p.y = value."""
        return self._con("vdist", p, q, dim=self._dim(name, value, label, "mm", lo, hi, step, doc), value=float(value),
                         text=f"vertical distance {name or value}")

    def radius(self, e, value: float, name: str = "", label: str = "", lo=None, hi=None, step: float = 0.1, doc=""):
        return self._con("radius", e, dim=self._dim(name, value, label, "mm", lo, hi, step, doc), value=float(value),
                         text=f"radius {name or value}")

    def diameter(self, e, value: float, name: str = "", label: str = "", lo=None, hi=None, step: float = 0.1, doc=""):
        return self._con("diameter", e, dim=self._dim(name, value, label, "mm", lo, hi, step, doc), value=float(value),
                         text=f"diameter {name or value}")

    def angle(self, l1: Line, l2: Line, deg: float, name: str = "", label: str = "", lo=None, hi=None, step: float = 0.5,
              doc=""):
        """The angle from l1's direction to l2's, counter-clockwise, in degrees."""
        return self._con("angle", l1, l2, dim=self._dim(name, deg, label, "°", lo, hi, step, doc), value=float(deg),
                         text=f"angle {name or deg}")

    # ── common profiles (each fully constrained, its sizes named when names are given) ──────────────────────
    def rounded_rect(self, w: float, h: float, r: float, center=(0.0, 0.0), names=("", "", ""), fix_center: bool = True,
                     labels=("", "", "")) -> dict:
        """A rectangle w x h with four tangent corner arcs of radius r, centred on center. names: (width, height,
        radius) dimension names ("" = fixed). Returns its lines, arcs, corner centres and centre point."""
        cx, cy = center
        hw, hh = w / 2, h / 2
        P = self.point
        b0, b1 = P(cx - hw + r, cy - hh), P(cx + hw - r, cy - hh)
        r0, r1 = P(cx + hw, cy - hh + r), P(cx + hw, cy + hh - r)
        t0, t1 = P(cx + hw - r, cy + hh), P(cx - hw + r, cy + hh)
        l0, l1 = P(cx - hw, cy + hh - r), P(cx - hw, cy - hh + r)
        cbr, ctr = P(cx + hw - r, cy - hh + r), P(cx + hw - r, cy + hh - r)
        ctl, cbl = P(cx - hw + r, cy + hh - r), P(cx - hw + r, cy - hh + r)
        bot, rig, top, lef = self.line(b0, b1), self.line(r0, r1), self.line(t0, t1), self.line(l0, l1)
        arcs = [self.arc(cbr, b1, r0), self.arc(ctr, r1, t0), self.arc(ctl, t1, l0), self.arc(cbl, l1, b0)]
        self.horizontal(bot); self.horizontal(top); self.vertical(rig); self.vertical(lef)
        for ln, a in ((bot, arcs[0]), (rig, arcs[0]), (rig, arcs[1]), (top, arcs[1]), (top, arcs[2]), (lef, arcs[2]),
                      (lef, arcs[3]), (bot, arcs[3])):
            self.tangent(ln, a)
        for a in arcs[1:]:
            self.equal(arcs[0], a)
        self.radius(arcs[0], r, names[2], labels[2])
        self.hdist(l1, r0, w, names[0], labels[0])
        self.vdist(b0, t1, h, names[1], labels[1])
        c = P(cx, cy, fix=fix_center)
        self.midpoint(c, self.line(cbl, ctr, construction=True))
        return {"lines": [bot, rig, top, lef], "arcs": arcs, "centers": [cbr, ctr, ctl, cbl], "center": c,
                "points": [b0, b1, r0, r1, t0, t1, l0, l1]}

    def slot(self, length: float, width: float, center=(0.0, 0.0), names=("", ""), fix_center: bool = True) -> dict:
        """An obround slot: centre distance `length` between its two end arcs, width = 2 x radius, horizontal."""
        cx, cy = center
        L, r = length / 2, width / 2
        P = self.point
        c1, c2 = P(cx - L, cy), P(cx + L, cy)
        a0, a1, b0, b1 = P(cx - L, cy - r), P(cx + L, cy - r), P(cx + L, cy + r), P(cx - L, cy + r)
        bot, top = self.line(a0, a1), self.line(b0, b1)
        right, left = self.arc(c2, a1, b0), self.arc(c1, b1, a0)
        self.horizontal(bot)
        for ln, a in ((bot, right), (top, right), (top, left), (bot, left)):
            self.tangent(ln, a)
        self.equal(left, right)
        axis = self.line(c1, c2, construction=True)
        self.horizontal(axis)
        self.distance(c1, c2, length, names[0])
        self.diameter(right, width, names[1])
        c = P(cx, cy, fix=fix_center)
        self.midpoint(c, axis)
        return {"lines": [bot, top], "arcs": [left, right], "centers": [c1, c2], "center": c}

    # ── parameters ────────────────────────────────────────────────────────────
    def dims(self) -> list[Dim]:
        return [c.dim for c in self.cons if c.dim]

    def params(self, feature: str = "", group: str = "form", prefix: str = "") -> list[Param]:
        """Every named dimension as a Param (key = prefix + name), for a Recipe's params list."""
        return [Param(prefix + d.name, d.label, d.value, d.lo, d.hi, d.step, d.unit, group, feature or self.name,
                      d.doc or f"Driving dimension of sketch {self.name}.") for d in self.dims()]

    def defaults(self) -> dict:
        return {d.name: d.value for d in self.dims()}

    # ── compile and solve ─────────────────────────────────────────────────────
    def _compile(self, values: dict, start: Solved | None) -> S.Problem:
        prob = S.Problem()
        for p in self.points:
            x, y = (start.pts[p.i] if start else (p.x, p.y))
            prob.var(x, f"{p}.x")
            prob.var(y, f"{p}.y")
        for e in self.ents:
            if isinstance(e, Circle):
                r = start.radius(e) if start and e.ri >= 0 else e.r
                e.ri = prob.var(r, f"circle{e.i}.r")

        def P(p):
            return [2 * p.i, 2 * p.i + 1]

        def ent_idx(e):
            if isinstance(e, Line):
                return P(e.a) + P(e.b)
            if isinstance(e, Arc):
                return P(e.c) + P(e.s)
            return P(e.c) + [e.ri]

        def ent_r(v):   # (cx, cy, r) from an arc's (cx, cy, sx, sy) or a circle's (cx, cy, r)
            if len(v) == 4:
                return v[0], v[1], math.hypot(v[2] - v[0], v[3] - v[1])
            return v[0], v[1], v[2]

        x0 = prob.x0
        for cid, c in enumerate(self.cons):
            k, E = c.kind, c.ents
            target = (values.get(c.dim.name, c.dim.value) if c.dim else c.value)
            if k == "fix":
                p = E[0]
                fx, fy = p.x, p.y
                prob.add(lambda v, fx=fx, fy=fy: [v[0] - fx, v[1] - fy], P(p), cid, 2)
            elif k == "arc":
                a = E[0]
                prob.add(lambda v: [math.hypot(v[2] - v[0], v[3] - v[1]) - math.hypot(v[4] - v[0], v[5] - v[1])],
                         P(a.c) + P(a.s) + P(a.e), cid)
            elif k == "coincident":
                prob.add(lambda v: [v[0] - v[2], v[1] - v[3]], P(E[0]) + P(E[1]), cid, 2)
            elif k == "horizontal":
                prob.add(lambda v: [v[3] - v[1]], P(E[0].a) + P(E[0].b), cid)
            elif k == "vertical":
                prob.add(lambda v: [v[2] - v[0]], P(E[0].a) + P(E[0].b), cid)
            elif k in ("parallel", "perpendicular"):
                f = S.sin_between if k == "parallel" else S.cos_between
                prob.add(lambda v, f=f: [10.0 * f((v[2] - v[0], v[3] - v[1]), (v[6] - v[4], v[7] - v[5]))],
                         P(E[0].a) + P(E[0].b) + P(E[1].a) + P(E[1].b), cid)
            elif k == "angle":
                t = math.radians(target)
                prob.add(lambda v, t=t: [10.0 * _wrap(math.atan2(v[7] - v[5], v[6] - v[4]) - math.atan2(v[3] - v[1], v[2] - v[0]) - t)],
                         P(E[0].a) + P(E[0].b) + P(E[1].a) + P(E[1].b), cid)
            elif k == "length":
                prob.add(lambda v, t=target: [math.hypot(v[2] - v[0], v[3] - v[1]) - t], P(E[0].a) + P(E[0].b), cid)
            elif k == "distance":
                prob.add(lambda v, t=target: [math.hypot(v[2] - v[0], v[3] - v[1]) - t], P(E[0]) + P(E[1]), cid)
            elif k == "hdist":
                prob.add(lambda v, t=target: [v[2] - v[0] - t], P(E[0]) + P(E[1]), cid)
            elif k == "vdist":
                prob.add(lambda v, t=target: [v[3] - v[1] - t], P(E[0]) + P(E[1]), cid)
            elif k == "pldist":
                p, ln = E
                idx = P(p) + P(ln.a) + P(ln.b)
                if not c.sign:
                    c.sign = 1.0 if S.signed_dist(*[x0[i] for i in idx]) >= 0 else -1.0
                prob.add(lambda v, t=target, s=c.sign: [S.signed_dist(*v) - s * t], idx, cid)
            elif k in ("radius", "diameter"):
                t = target if k == "radius" else target / 2
                prob.add(lambda v, t=t: [ent_r(v)[2] - t], ent_idx(E[0]), cid)
            elif k == "equal":
                a, b = E
                if isinstance(a, Line):
                    prob.add(lambda v: [math.hypot(v[2] - v[0], v[3] - v[1]) - math.hypot(v[6] - v[4], v[7] - v[5])],
                             ent_idx(a) + ent_idx(b), cid)
                else:
                    na = len(ent_idx(a))
                    prob.add(lambda v, na=na: [ent_r(v[:na])[2] - ent_r(v[na:])[2]], ent_idx(a) + ent_idx(b), cid)
            elif k == "midpoint":
                p, ln = E
                prob.add(lambda v: [2 * v[0] - v[2] - v[4], 2 * v[1] - v[3] - v[5]], P(p) + P(ln.a) + P(ln.b), cid, 2)
            elif k == "on":
                p, e = E
                if isinstance(e, Line):
                    prob.add(lambda v: [S.signed_dist(*v)], P(p) + P(e.a) + P(e.b), cid)
                else:
                    prob.add(lambda v: [math.hypot(v[0] - v[2], v[1] - v[3]) - ent_r(v[2:])[2]], P(p) + ent_idx(e), cid)
            elif k == "symmetric":
                p, q, ax = E

                def sym(v):
                    px, py, qx, qy, ax_, ay, bx, by = v
                    ux, uy = S._unit(bx - ax_, by - ay)
                    return [S.signed_dist((px + qx) / 2, (py + qy) / 2, ax_, ay, bx, by), (qx - px) * ux + (qy - py) * uy]
                prob.add(sym, P(p) + P(q) + P(ax.a) + P(ax.b), cid, 2)
            elif k == "tangent":
                a, b = E
                shared = _shared(a, b)
                if shared is not None:
                    # the two meet at a point: tangent there means the radius (or both radii) is square to the line
                    # (or in line with each other). Unlike a distance equation this stays well-conditioned at the
                    # answer, so the degrees of freedom left are counted right.
                    if isinstance(a, Line):
                        other = a.b if shared is a.a else a.a
                        prob.add(lambda v: [10.0 * S.cos_between((v[2] - v[0], v[3] - v[1]), (v[4] - v[0], v[5] - v[1]))],
                                 P(shared) + P(other) + P(b.c), cid)
                    else:
                        prob.add(lambda v: [10.0 * S.sin_between((v[2] - v[0], v[3] - v[1]), (v[4] - v[0], v[5] - v[1]))],
                                 P(shared) + P(a.c) + P(b.c), cid)
                    continue
                if isinstance(a, Line):
                    idx = P(a.a) + P(a.b) + ent_idx(b)
                    if not c.sign:
                        v = [x0[i] for i in idx]
                        c.sign = 1.0 if S.signed_dist(v[4], v[5], *v[:4]) >= 0 else -1.0

                    def tl(v, s=c.sign):
                        cx, cy, r = ent_r(v[4:])
                        return [S.signed_dist(cx, cy, *v[:4]) - s * r]
                    prob.add(tl, idx, cid)
                else:
                    na = len(ent_idx(a))
                    idx = ent_idx(a) + ent_idx(b)
                    if not c.sign:
                        v = [x0[i] for i in idx]
                        c1, c2 = ent_r(v[:na]), ent_r(v[na:])
                        d = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
                        ext, inn = abs(d - (c1[2] + c2[2])), abs(d - abs(c1[2] - c2[2]))
                        c.sign = 2.0 if ext <= inn else (1.0 if c1[2] >= c2[2] else -1.0)

                    def ta(v, na=na, s=c.sign):
                        c1, c2 = ent_r(v[:na]), ent_r(v[na:])
                        d = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
                        return [d - (c1[2] + c2[2])] if s == 2.0 else [d - s * (c1[2] - c2[2])]
                    prob.add(ta, idx, cid)
            else:
                raise SketchError(f"Unknown constraint {k}", self.name)
        return prob

    def _measure(self, c: Con, sol: Solved) -> float:
        E = c.ents
        if c.kind == "length":
            (ax, ay), (bx, by) = sol.p(E[0].a), sol.p(E[0].b)
            return math.hypot(bx - ax, by - ay)
        if c.kind == "distance":
            (ax, ay), (bx, by) = sol.p(E[0]), sol.p(E[1])
            return math.hypot(bx - ax, by - ay)
        if c.kind == "hdist":
            return sol.p(E[1])[0] - sol.p(E[0])[0]
        if c.kind == "vdist":
            return sol.p(E[1])[1] - sol.p(E[0])[1]
        if c.kind == "pldist":
            return abs(S.signed_dist(*sol.p(E[0]), *sol.p(E[1].a), *sol.p(E[1].b)))
        if c.kind == "radius":
            return sol.radius(E[0])
        if c.kind == "diameter":
            return 2 * sol.radius(E[0])
        if c.kind == "angle":
            (a, b), (p, q) = (sol.p(E[0].a), sol.p(E[0].b)), (sol.p(E[1].a), sol.p(E[1].b))
            return math.degrees(_wrap(math.atan2(q[1] - p[1], q[0] - p[0]) - math.atan2(b[1] - a[1], b[0] - a[0])))
        raise KeyError(c.kind)

    def _try(self, values: dict, start: Solved | None) -> Solved:
        prob = self._compile(values, start)
        res = S.solve(prob)
        return Solved(self, res.x, res, values)

    def solve(self, values: dict | None = None) -> Solved:
        """Place the geometry for these dimension values (a design's v, or {} for the defaults). Re-solves start from
        the solution at the defaults; a large change is walked there in steps, so the solution stays on the branch
        the sketch was drawn on. Raises SketchError naming the conflicting constraints."""
        vals = {d.name: float((values or {}).get(d.name, d.value)) for d in self.dims()}
        if self._nominal is None:
            nom = self._try(self.defaults(), None)
            if not nom.result.ok:
                raise self._error(nom)
            self._nominal = nom
        nom = self._nominal
        if all(abs(vals[k] - nom.values[k]) < 1e-12 for k in vals):
            self._last = nom
            return nom
        base = self._last if self._last is not None else nom
        sol = self._try(vals, base)
        steps = 2
        while not sol.result.ok and steps <= 16:       # homotopy: walk the dimensions there from the defaults
            cur = nom
            for k in range(1, steps + 1):
                mid = {n: nom.values[n] + (vals[n] - nom.values[n]) * k / steps for n in vals}
                cur = self._try(mid, cur)
                if not cur.result.ok:
                    break
            sol = cur
            steps *= 2
        if not sol.result.ok:
            raise self._error(sol)
        self._check_arcs(sol)
        self._last = sol
        return sol

    def _check_arcs(self, sol: Solved):
        for e in self.ents:
            if isinstance(e, (Arc, Circle)) and sol.radius(e) < 1e-4:
                raise SketchError(f"Sketch {self.name}: an arc shrank to nothing at these dimensions.", self.name,
                                  "Change the dimensions back toward their defaults.", [d.name for d in self.dims()])
            if isinstance(e, Line):
                (ax, ay), (bx, by) = sol.p(e.a), sol.p(e.b)
                if math.hypot(bx - ax, by - ay) < 1e-4:
                    raise SketchError(f"Sketch {self.name}: a line shrank to nothing at these dimensions.", self.name,
                                      "Change the dimensions back toward their defaults.", [d.name for d in self.dims()])

    def _error(self, sol: Solved) -> SketchError:
        bad = [self.cons[cid] for _, cid in sol.result.worst[:3]]
        names = [c.dim.name for c in bad if c.dim] or [d.name for d in self.dims()]
        what = "; ".join(c.text for c in bad) or "the constraints"
        return SketchError(f"Sketch {self.name} does not solve: {what} cannot all hold "
                           f"(residual {sol.result.residual:.3g} mm).", self.name,
                           "Over-constrained or a dimension out of reach: remove a constraint that repeats another, or "
                           "move these dimensions toward their defaults.", names)

    def report(self, values: dict | None = None) -> dict:
        """How the sketch stands: entities, constraints, degrees of freedom left, solve time."""
        sol = self.solve(values)
        r = sol.result
        return {"sketch": self.name, "entities": len(self.ents), "points": len(self.points),
                "constraints": len([c for c in self.cons if c.kind != "arc"]), "dimensions": len(self.dims()),
                "dof": r.dof, "fully_constrained": r.dof == 0, "solve_ms": round(r.ms, 3), "iterations": r.iters,
                "residual_mm": r.residual}

    # ── output ────────────────────────────────────────────────────────────────
    def edges2d(self, values: dict | None = None) -> list[dict]:
        """The solved profile as plain data: [{kind: line, a, b} | {kind: arc, c, r, a0, a1, s, e, m} | {kind: circle, c, r}]."""
        sol = self.solve(values)
        out = []
        for e in self.ents:
            if e.construction:
                continue
            if isinstance(e, Line):
                out.append({"kind": "line", "a": sol.p(e.a), "b": sol.p(e.b)})
            elif isinstance(e, Arc):
                t0, t1 = sol.arc_angles(e)
                out.append({"kind": "arc", "c": sol.p(e.c), "r": sol.radius(e), "a0": t0, "a1": t1, "s": sol.p(e.s),
                            "e": sol.p(e.e), "m": sol.arc_mid(e)})
            else:
                out.append({"kind": "circle", "c": sol.p(e.c), "r": sol.radius(e)})
        return out

    def polygons(self, values: dict | None = None, seg_deg: float = 6.0) -> list[list[tuple]]:
        """Closed loops as point lists (arcs sampled), largest first. Plain numpy-free Python; for drawings and tests."""
        loops = _loops(self.edges2d(values))
        out = []
        for loop in loops:
            pts = []
            for ed in loop:
                pts.extend(_sample(ed, seg_deg)[:-1])
            out.append(pts)
        out.sort(key=lambda p: -abs(_area(p)))
        return out

    def wires(self, values: dict | None = None, plane=None):
        """build123d wires of the profile (each closed loop), on plane (default XY)."""
        from build123d import Edge, Plane, Vector, Wire
        plane = plane or Plane.XY
        loops = _loops(self.edges2d(values))
        wires = []
        for loop in loops:
            edges = []
            for ed in loop:
                if ed["kind"] == "line":
                    edges.append(Edge.make_line(Vector(*ed["a"], 0), Vector(*ed["b"], 0)))
                elif ed["kind"] == "arc":
                    a, m, b = (ed["s"], ed["m"], ed["e"]) if not ed.get("rev") else (ed["e"], ed["m"], ed["s"])
                    edges.append(Edge.make_three_point_arc(Vector(*a, 0), Vector(*m, 0), Vector(*b, 0)))
                else:
                    edges.append(Edge.make_circle(ed["r"], Plane(origin=(ed["c"][0], ed["c"][1], 0))))
            w = Wire(edges) if len(edges) == 1 else Wire.combine(edges)[0]
            wires.append(plane.location * w if plane is not Plane.XY else w)
        return wires

    def face(self, values: dict | None = None, plane=None):
        """The profile as a build123d Face (or a Compound of faces when it has several separate regions): the largest
        loop is the outside, loops inside another are holes. Values: a design's v (only this sketch's names are read)."""
        from build123d import Compound, Face, Plane
        plane = plane or Plane.XY
        wires = self.wires(values)
        loops = _loops(self.edges2d(values))
        ploys = [[q for ed in loop for q in _sample(ed, 6.0)[:-1]] for loop in loops]
        order = sorted(range(len(loops)), key=lambda i: -abs(_area(ploys[i])))
        depth = {}
        for i in order:
            depth[i] = sum(1 for j in order if j != i and abs(_area(ploys[j])) > abs(_area(ploys[i]))
                           and _inside(ploys[i][0], ploys[j]))
        faces = []
        for i in order:
            if depth[i] % 2:
                continue
            holes = [wires[j] for j in order if depth[j] == depth[i] + 1 and _inside(ploys[j][0], ploys[i])]
            faces.append(Face(wires[i], holes))
        if not faces:
            raise SketchError(f"Sketch {self.name} has no closed profile.", self.name,
                              "Join the lines and arcs end to end (coincident) into closed loops.")
        out = faces[0] if len(faces) == 1 else Compound(faces)
        return plane.location * out if plane is not Plane.XY else out

    def svg(self, values: dict | None = None, size: int = 520, dims: bool = True) -> str:
        """A drawing of the solved sketch with its named dimensions (for reports and the agent)."""
        sol = self.solve(values)
        pts = [q for poly in self.polygons(values) for q in poly] or sol.pts
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        lo_x, hi_x, lo_y, hi_y = min(xs), max(xs), min(ys), max(ys)
        span = max(hi_x - lo_x, hi_y - lo_y, 1e-6)
        k = (size - 80) / span

        def X(p):
            return 40 + (p[0] - lo_x) * k, size - 40 - (p[1] - lo_y) * k
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">',
                 '<rect width="100%" height="100%" fill="#fbfaf7"/>']
        for poly in self.polygons(values):
            d = " ".join(f"{'M' if i == 0 else 'L'}{X(p)[0]:.1f},{X(p)[1]:.1f}" for i, p in enumerate(poly)) + " Z"
            parts.append(f'<path d="{d}" fill="#e8e4da" stroke="#22252a" stroke-width="1.6"/>')
        for e in self.ents:
            if e.construction and isinstance(e, Line):
                a, b = X(sol.p(e.a)), X(sol.p(e.b))
                parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="#7a8796" '
                             'stroke-dasharray="6 4"/>')
        if dims:
            for c in self.cons:
                if not c.dim:
                    continue
                q = [sol.p(e) if isinstance(e, Point) else sol.p(e.a) if isinstance(e, Line) else sol.p(e.c) for e in c.ents]
                if isinstance(c.ents[0], Line):
                    q = [sol.p(c.ents[0].a), sol.p(c.ents[0].b)]
                mx = sum(p[0] for p in q) / len(q)
                my = sum(p[1] for p in q) / len(q)
                x, y = X((mx, my))
                u = "°" if c.dim.unit == "°" else ""
                parts.append(f'<text x="{x:.1f}" y="{y - 6:.1f}" font-family="Menlo, monospace" font-size="11" '
                             f'fill="#1f6f5c" text-anchor="middle">{c.dim.name} {self._measure(c, sol):.2f}{u}</text>')
        parts.append("</svg>")
        return "\n".join(parts)


# ── loops ─────────────────────────────────────────────────────────────────────

def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _ends(ed):
    if ed["kind"] == "line":
        return ed["a"], ed["b"]
    if ed["kind"] == "arc":
        return ed["s"], ed["e"]
    return None


def _close(p, q, tol=1e-5):
    return abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol


def _loops(edges: list[dict]) -> list[list[dict]]:
    """Chain edges into closed loops (each edge oriented along its loop: 'rev' marks one walked backwards)."""
    loops, rest = [], []
    for ed in edges:
        (loops if ed["kind"] == "circle" else rest).append(ed if ed["kind"] != "circle" else [ed])
    loops = [x for x in loops]
    rest = list(rest)
    while rest:
        first = dict(rest.pop(0))
        loop = [first]
        start, cur = _ends(first)
        guard = 0
        while not _close(cur, start) and guard < 10000:
            guard += 1
            for k, ed in enumerate(rest):
                a, b = _ends(ed)
                if _close(a, cur):
                    loop.append(dict(ed)); cur = b; rest.pop(k); break
                if _close(b, cur):
                    e2 = dict(ed); e2["rev"] = True
                    loop.append(e2); cur = a; rest.pop(k); break
            else:
                raise SketchError("The sketch has an open chain: an end that meets nothing near "
                                  f"({cur[0]:.3f}, {cur[1]:.3f}).", "", "Make the profile's lines and arcs meet end "
                                  "to end (coincident), or mark guide lines construction=True.")
        loops.append(loop)
    return loops


def _sample(ed, seg_deg: float = 6.0) -> list[tuple]:
    if ed["kind"] == "line":
        pts = [ed["a"], ed["b"]]
    else:
        c, r = ed["c"], ed["r"]
        a0, a1 = (ed["a0"], ed["a1"]) if ed["kind"] == "arc" else (0.0, 2 * math.pi)
        n = max(2, int(math.degrees(a1 - a0) / seg_deg) + 1)
        pts = [(c[0] + r * math.cos(a0 + (a1 - a0) * i / n), c[1] + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
    return pts[::-1] if ed.get("rev") else pts


def _area(poly) -> float:
    return 0.5 * sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))


def _inside(p, poly) -> bool:
    c = False
    x, y = p
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[i - 1]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            c = not c
    return c



def _shared(a, b):
    """The point a line or arc shares with an arc (as an end), or None."""
    ends = lambda e: (e.a, e.b) if isinstance(e, Line) else (e.s, e.e) if isinstance(e, Arc) else ()
    for p in ends(a):
        if any(p is q for q in ends(b)):
            return p
    return None
