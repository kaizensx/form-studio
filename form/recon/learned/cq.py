"""Read a CadQuery program as a plan of sketch extrusions, without running it.

A learned model writes CadQuery code. It is never executed: this walks its syntax tree and accepts only the small
part of CadQuery that sketch-and-extrude parts use, recording what each call means:

    w = cq.Workplane('XY', origin=(x, y, z))          a sketch plane (XY, YZ, ZX, XZ, YX, ZY)
    w.workplane(offset=d)                              the same plane moved along its normal
    .sketch() .push([(x, y), ...]) .rect(w, h, mode=) .circle(r, mode=)
    .segment(p0, p1) / .segment(p1)  .arc(p0, p1, p2) / .arc(p1, p2)  .close() .assemble(mode=) .finalize()
    .moveTo(x, y) .lineTo(x, y) .threePointArc(p1, p2) .close() .rect(w, h) .circle(r)   (the Workplane forms)
    .extrude(d, both=False)  a.union(b)  a.cut(b)

Anything else (a function, a loop, an attribute this does not know, a revolve) is refused with the reason: the
caller then has no candidate, never a guess. Numbers may be written as literals, negatives and + - * / of them.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

import numpy as np

# CadQuery's named planes: (x direction, normal)
PLANES = {
    "XY": ((1, 0, 0), (0, 0, 1)), "YZ": ((0, 1, 0), (1, 0, 0)), "ZX": ((0, 0, 1), (0, 1, 0)),
    "XZ": ((1, 0, 0), (0, -1, 0)), "YX": ((0, 1, 0), (0, 0, -1)), "ZY": ((0, 0, 1), (-1, 0, 0)),
}


class Unsupported(ValueError):
    """The code uses something outside the subset: no plan."""


@dataclass
class Plane:
    origin: np.ndarray
    x: np.ndarray
    n: np.ndarray

    @property
    def y(self):
        return np.cross(self.n, self.x)

    def moved(self, d):
        return Plane(self.origin + float(d) * self.n, self.x, self.n)


@dataclass
class Item:
    """One closed shape of a sketch, in the plane's coordinates. kind: rect (c, w, h) | circle (c, r) | path
    (segments [("line", p0, p1) | ("arc", p0, pm, p1)])."""
    kind: str
    mode: str = "a"                      # a: add, s: subtract
    c: tuple = (0.0, 0.0)
    w: float = 0.0
    h: float = 0.0
    r: float = 0.0
    segs: list = field(default_factory=list)


@dataclass
class Extrude:
    plane: Plane
    items: list
    d0: float                            # from this distance along the normal ...
    d1: float                            # ... to this one (d0 < d1)


@dataclass
class Solid:
    """A boolean tree: ("extrude", Extrude) | ("union", a, b) | ("cut", a, b)."""
    node: tuple

    def extrusions(self):
        out = []

        def walk(t):
            if t[0] == "extrude":
                out.append(t[1])
            else:
                walk(t[1].node)
                walk(t[2].node)
        walk(self.node)
        return out


class _Sketch:
    def __init__(self, plane, ws=None):
        self.plane = plane
        self.items: list[Item] = []
        self.locs = [(0.0, 0.0)]
        self.segs: list = []
        self.cur = None
        self.ws = ws                     # a Workplane-level path (moveTo ...) writes into the Workplane, not a sketch

    def _end_path(self):
        if self.segs:
            self.items.append(Item("path", segs=self.segs))
        self.segs, self.cur = [], None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Unsupported(f"a number was expected, not {type(v).__name__}")
    return float(v)


def _pt(v):
    if not isinstance(v, (tuple, list)) or len(v) != 2:
        raise Unsupported("a point (x, y) was expected")
    return (_num(v[0]), _num(v[1]))


class _Eval:
    def __init__(self):
        self.env = {}

    # -- expressions --
    def ev(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str, bool)):     # a bool only ever reaches a flag (both=True)
                return node.value
            raise Unsupported(f"constant {node.value!r}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = _num(self.ev(node.operand))
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = _num(self.ev(node.left)), _num(self.ev(node.right))
            if isinstance(node.op, ast.Div) and b == 0:
                raise Unsupported("division by zero")
            return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b}.get(type(node.op), a / b if b else 0.0)
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(self.ev(e) for e in node.elts)
        if isinstance(node, ast.Name):
            if node.id not in self.env:
                raise Unsupported(f"unknown name {node.id!r}")
            return self.env[node.id]
        if isinstance(node, ast.Attribute):
            base = self.ev(node.value)
            if base == "cq-module" and node.attr == "Workplane":
                return "cq.Workplane"
            raise Unsupported(f"attribute {node.attr!r}")
        if isinstance(node, ast.Call):
            return self.call(node)
        raise Unsupported(f"{type(node).__name__} is not part of the subset")

    def call(self, node):
        args = [self.ev(a) for a in node.args]
        kw = {k.arg: self.ev(k.value) for k in node.keywords if k.arg}
        if len(kw) != len(node.keywords):
            raise Unsupported("**kwargs")
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and self.env.get(node.func.value.id) == "cq-module" and node.func.attr == "Workplane":
            name = str(args[0]) if args else str(kw.get("inPlane", "XY"))
            if name not in PLANES:
                raise Unsupported(f"plane {name!r}")
            x, n = PLANES[name]
            o = kw.get("origin", (0, 0, 0))
            if not isinstance(o, (tuple, list)) or len(o) != 3:
                raise Unsupported("origin must be (x, y, z)")
            return ("wp", Plane(np.array([_num(c) for c in o]), np.array(x, float), np.array(n, float)), None)
        if not isinstance(node.func, ast.Attribute):
            raise Unsupported("a call that is not a method")
        obj = self.ev(node.func.value)
        return self.method(obj, node.func.attr, args, kw)

    # -- methods --
    def method(self, obj, m, args, kw):
        if isinstance(obj, tuple) and obj and obj[0] == "wp":
            return self.wp(obj, m, args, kw)
        if isinstance(obj, _Sketch):
            return self.sk(obj, m, args, kw)
        if isinstance(obj, Solid):
            if m in ("union", "cut") and len(args) == 1 and isinstance(args[0], Solid):
                return Solid((m, obj, args[0]))
            raise Unsupported(f"solid.{m}")
        raise Unsupported(f".{m} on {type(obj).__name__}")

    def wp(self, obj, m, args, kw):
        _, plane, path = obj
        if m == "workplane":
            return ("wp", plane.moved(_num(kw.get("offset", args[0] if args else 0.0))), None)
        if m == "sketch":
            return _Sketch(plane)
        if m in ("moveTo", "lineTo", "threePointArc", "close", "rect", "circle", "center", "push", "pushPoints"):
            s = path if path is not None else _Sketch(plane, ws=True)
            if m == "moveTo":
                s._end_path()
                s.cur = _pt(args if len(args) == 2 else args[0])
            elif m == "lineTo":
                p = _pt(args if len(args) == 2 else args[0])
                s.segs.append(("line", s.cur or (0.0, 0.0), p))
                s.cur = p
            elif m == "threePointArc":
                pm, p1 = _pt(args[0]), _pt(args[1])
                s.segs.append(("arc", s.cur or (0.0, 0.0), pm, p1))
                s.cur = p1
            elif m == "close":
                if s.segs and s.segs[0][1] != s.cur:
                    s.segs.append(("line", s.cur, s.segs[0][1]))
                s._end_path()
            elif m in ("push", "pushPoints"):
                s.locs = [_pt(p) for p in args[0]]
            elif m == "center":
                s.locs = [(_num(args[0]), _num(args[1]))]
            elif m == "rect":
                for c in s.locs:
                    s.items.append(Item("rect", c=c, w=abs(_num(args[0])), h=abs(_num(args[1]))))
            elif m == "circle":
                for c in s.locs:
                    s.items.append(Item("circle", c=c, r=abs(_num(args[0]))))
            return ("wp", plane, s)
        if m == "extrude":
            if path is None:
                raise Unsupported("extrude with nothing drawn")
            path._end_path()
            return self._extrude(plane, path.items, args, kw)
        raise Unsupported(f"Workplane.{m}")

    def sk(self, s, m, args, kw):
        mode = str(kw.get("mode", "a"))
        if mode not in ("a", "s"):
            raise Unsupported(f"sketch mode {mode!r}")
        if m == "push":
            s.locs = [_pt(p) for p in args[0]]
        elif m == "reset":
            s.locs = [(0.0, 0.0)]
        elif m == "rect":
            for c in s.locs:
                s.items.append(Item("rect", mode=mode, c=c, w=abs(_num(args[0])), h=abs(_num(args[1]))))
        elif m == "circle":
            for c in s.locs:
                s.items.append(Item("circle", mode=mode, c=c, r=abs(_num(args[0]))))
        elif m == "segment":
            if len(args) == 2:
                p0, p1 = _pt(args[0]), _pt(args[1])
            else:
                p0, p1 = s.cur, _pt(args[0])
                if p0 is None:
                    raise Unsupported("segment without a start")
            s.segs.append(("line", p0, p1))
            s.cur = p1
        elif m == "arc":
            if len(args) == 3:
                p0, pm, p1 = _pt(args[0]), _pt(args[1]), _pt(args[2])
            else:
                p0, pm, p1 = s.cur, _pt(args[0]), _pt(args[1])
                if p0 is None:
                    raise Unsupported("arc without a start")
            s.segs.append(("arc", p0, pm, p1))
            s.cur = p1
        elif m == "close":
            if s.segs and s.segs[0][1] != s.cur:
                s.segs.append(("line", s.cur, s.segs[0][1]))
        elif m == "assemble":
            segs = s.segs
            s._end_path()
            if segs:
                s.items[-1].mode = mode
        elif m == "finalize":
            s._end_path()
            return ("wp", s.plane, s)
        else:
            raise Unsupported(f"Sketch.{m}")
        return s

    def _extrude(self, plane, items, args, kw):
        d = _num(args[0] if args else kw.get("until", kw.get("distance", 0.0)))
        if not items:
            raise Unsupported("extrude with an empty sketch")
        if abs(d) < 1e-12:
            raise Unsupported("extrude of zero length")
        both = bool(kw.get("both", False))
        d0, d1 = (-abs(d), abs(d)) if both else (min(0.0, d), max(0.0, d))
        return Solid(("extrude", Extrude(plane, list(items), d0, d1)))

    # -- statements --
    def run(self, code: str):
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise Unsupported(f"not Python: {e.msg} (line {e.lineno})") from None
        last = None
        for st in tree.body:
            if isinstance(st, ast.Import):
                for a in st.names:
                    if a.name != "cadquery":
                        raise Unsupported(f"import {a.name}")
                    self.env[a.asname or "cadquery"] = "cq-module"
                continue
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                v = self.ev(st.value)
                self.env[st.targets[0].id] = v
                if isinstance(v, Solid):
                    last = v
                continue
            if isinstance(st, ast.Expr):
                v = self.ev(st.value)
                if isinstance(v, Solid):
                    last = v
                continue
            raise Unsupported(f"{type(st).__name__} statement")
        res = self.env.get("r", last)
        if not isinstance(res, Solid):
            raise Unsupported("the code makes no solid")
        return res


def parse(code: str) -> Solid:
    """The plan of a CadQuery program (the variable `r`, else the last solid made). Raises Unsupported."""
    if len(code) > 200_000:
        raise Unsupported("the code is too long")
    return _Eval().run(code)
