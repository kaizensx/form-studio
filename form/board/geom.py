"""Plane geometry for copper: every copper shape is a convex skeleton (a point, a segment or a convex polygon) grown
by a radius, so the gap between two shapes is the distance between their skeletons minus both radii, in closed form.

    circle (round pad, via)      one point, r = d / 2
    track, oval pad              a segment, r = width / 2
    rectangular pad              four corners, r = 0
    rounded-rectangle pad        the rectangle shrunk by the corner radius, r = the corner radius (exact)

No grid and no sampling: these are the numbers Form Studio's own clearance check reports (form/board/drc.py), and
the ones the router's pull-tight pass tests a segment with before it keeps it. Pure Python.
"""
from __future__ import annotations

import math

Shape = tuple          # (points: tuple[(x, y), ...], r: float)


def pt_seg(p, a, b) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    L = vx * vx + vy * vy
    if L == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)


def _orient(o, p, q) -> float:
    return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])


def seg_cross(a, b, c, d) -> bool:
    """Segments ab and cd share a point (touching counts)."""
    d1, d2, d3, d4 = _orient(c, d, a), _orient(c, d, b), _orient(a, b, c), _orient(a, b, d)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True

    def on(p, q, r):
        return min(p[0], q[0]) - 1e-12 <= r[0] <= max(p[0], q[0]) + 1e-12 and \
            min(p[1], q[1]) - 1e-12 <= r[1] <= max(p[1], q[1]) + 1e-12
    return (d1 == 0 and on(c, d, a)) or (d2 == 0 and on(c, d, b)) or (d3 == 0 and on(a, b, c)) or (d4 == 0 and on(a, b, d))


def seg_seg(a, b, c, d) -> float:
    if seg_cross(a, b, c, d):
        return 0.0
    return min(pt_seg(a, c, d), pt_seg(b, c, d), pt_seg(c, a, b), pt_seg(d, a, b))


def inside_convex(p, poly) -> bool:
    """p inside or on a convex polygon (either winding)."""
    pos = neg = False
    n = len(poly)
    for i in range(n):
        o = _orient(poly[i], poly[(i + 1) % n], p)
        if o > 1e-12:
            pos = True
        elif o < -1e-12:
            neg = True
        if pos and neg:
            return False
    return True


def inside(p, poly) -> bool:
    """p inside any simple polygon (even-odd)."""
    x, y = p
    c = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[i - 1]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def _edges(pts):
    n = len(pts)
    if n == 1:
        return [(pts[0], pts[0])]
    if n == 2:
        return [(pts[0], pts[1])]
    return [(pts[i], pts[(i + 1) % n]) for i in range(n)]


def skeleton_dist(a, b) -> float:
    """Distance between two convex skeletons (0 when they touch or one holds the other)."""
    if len(a) >= 3 and inside_convex(b[0], a):
        return 0.0
    if len(b) >= 3 and inside_convex(a[0], b):
        return 0.0
    best = math.inf
    for p, q in _edges(a):
        for r, s in _edges(b):
            d = seg_seg(p, q, r, s)
            if d < best:
                best = d
                if d == 0.0:
                    return 0.0
    return best


def gap(s1: Shape, s2: Shape) -> float:
    """Copper to copper: negative when the shapes overlap by that much (at most the sum of the radii)."""
    return skeleton_dist(s1[0], s2[0]) - s1[1] - s2[1]


def pt_gap(p, s: Shape) -> float:
    """From a point to a shape's copper (negative inside, down to -r; 0 inside a polygon skeleton's interior - r)."""
    pts = s[0]
    if len(pts) >= 3 and inside_convex(p, pts):
        return -s[1]
    return min(pt_seg(p, q, r) for q, r in _edges(pts)) - s[1]


def inset(p, s: Shape) -> float:
    """How far a point is inside a shape's copper (positive inside, negative outside): the room a track end has."""
    pts = s[0]
    if len(pts) >= 3:
        if inside_convex(p, pts):
            return min(pt_seg(p, q, r) for q, r in _edges(pts)) + s[1]
        return s[1] - min(pt_seg(p, q, r) for q, r in _edges(pts))
    return s[1] - min(pt_seg(p, q, r) for q, r in _edges(pts))


def bbox(s: Shape) -> tuple:
    xs = [p[0] for p in s[0]]
    ys = [p[1] for p in s[0]]
    r = s[1]
    return min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r


def circle(c, d: float) -> Shape:
    return ((float(c[0]), float(c[1])),), d / 2.0


def capsule(a, b, w: float) -> Shape:
    return ((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))), w / 2.0


def rot(p, deg: float):
    """KiCad's rotation on its y-down sheet (counter-clockwise as seen on screen), as form.board.model.rot."""
    a = math.radians(deg or 0.0)
    c, s = math.cos(a), math.sin(a)
    return p[0] * c + p[1] * s, -p[0] * s + p[1] * c


def pad_shape(shape: str, at, w: float, h: float, angle: float = 0.0, rratio: float = 0.25) -> tuple[Shape, bool]:
    """A pad's copper as (Shape, exact). circle, oval, rect and roundrect are exact; any other shape (trapezoid,
    custom) is its bounding rectangle, which is said (exact=False)."""
    x, y = at
    if shape == "circle" or (shape == "oval" and abs(w - h) < 1e-9):
        return circle(at, min(w, h)), True
    if shape == "oval":
        r = min(w, h) / 2.0
        half = (max(w, h) - min(w, h)) / 2.0
        d = (half, 0.0) if w >= h else (0.0, half)
        a, b = rot((-d[0], -d[1]), angle), rot(d, angle)
        return (((x + a[0], y + a[1]), (x + b[0], y + b[1])), r), True
    r = 0.0
    exact = shape in ("rect", "roundrect")
    if shape == "roundrect":
        r = max(0.0, min(rratio, 0.5)) * min(w, h)
    hw, hh = w / 2.0 - r, h / 2.0 - r
    if hw <= 1e-9 and hh <= 1e-9:
        return circle(at, 2 * r), exact
    if hw <= 1e-9 or hh <= 1e-9:
        d = (max(hw, 0.0), max(hh, 0.0))
        a, b = rot((-d[0], -d[1]), angle), rot(d, angle)
        return (((x + a[0], y + a[1]), (x + b[0], y + b[1])), r), exact
    cs = [rot(q, angle) for q in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
    return (tuple((x + q[0], y + q[1]) for q in cs), r), exact


def poly_seg_dist(poly, a, b, closed: bool = True) -> float:
    """From segment ab to a polyline's edges (the boundary only)."""
    n = len(poly)
    best = math.inf
    for i in range(n if closed else n - 1):
        d = seg_seg(a, b, poly[i], poly[(i + 1) % n])
        if d < best:
            best = d
            if d == 0.0:
                break
    return best


class Index:
    """A uniform hash of shapes by bounding box, for "what is near this segment"."""

    def __init__(self, cell: float = 2.0):
        self.cell = cell
        self.grid: dict = {}
        self.items: dict = {}
        self._n = 0

    def _cells(self, bb):
        c = self.cell
        for gx in range(int(math.floor(bb[0] / c)), int(math.floor(bb[2] / c)) + 1):
            for gy in range(int(math.floor(bb[1] / c)), int(math.floor(bb[3] / c)) + 1):
                yield gx, gy

    def add(self, shape: Shape, **meta) -> int:
        self._n += 1
        i = self._n
        bb = bbox(shape)
        self.items[i] = (shape, meta, bb)
        for k in self._cells(bb):
            self.grid.setdefault(k, []).append(i)
        return i

    def remove(self, i: int) -> None:
        it = self.items.pop(i, None)
        if it is None:
            return
        for k in self._cells(it[2]):
            lst = self.grid.get(k)
            if lst and i in lst:
                lst.remove(i)

    def near(self, bb, margin: float = 0.0):
        """(id, shape, meta) of every item whose box comes within margin of the box bb, once each."""
        q = (bb[0] - margin, bb[1] - margin, bb[2] + margin, bb[3] + margin)
        seen = set()
        for k in self._cells(q):
            for i in self.grid.get(k, ()):
                if i in seen:
                    continue
                seen.add(i)
                s, meta, b = self.items[i]
                if b[0] <= q[2] and b[2] >= q[0] and b[1] <= q[3] and b[3] >= q[1]:
                    yield i, s, meta
