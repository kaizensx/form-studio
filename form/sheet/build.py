"""Sheet-metal features for a design's code: a base flange, edge flanges, hems, jogs, relief cuts and louvres, each
with its thickness and inside bend radius, built as one constant-thickness solid that form/sheet/unfold.py can lay
flat again.

    from form.sheet.build import Sheet

    class Design(FeatureDesign):
        t = Param("t", "Thickness", 1.5, 0.5, 6)
        ...
        @feature("Sheet")
        def sheet(self, v, body):
            s = Sheet(t=v["t"], r=v["r"])                     # r: inside bend radius (default: the material's)
            b = s.base([(0, 0), (120, 0), (120, 80), (0, 80)])
            s.flange(b.edge(0), length=30, angle=90)            # edge 0 of the base outline, bent up 90°
            f = s.flange(b.edge(2), length=20, angle=90, start=10, end=10, relief="obround")
            s.hem(f.far(), length=8)                            # folded back flat over the flange
            s.jog(b.edge(1), offset=6, length=25)               # two opposite bends: a step of 6 mm
            s.louvre(b, at=(60, 40), length=30, width=6, height=3)
            return s.solid()

Conventions (one per sheet, stated so the flat pattern is unambiguous):

- The base outline is a polygon in the XY plane, counter-clockwise, the sheet from z = 0 up to z = t.
- A flange starts at its parent's edge (the parent keeps its outline; the bend lies outside it). "up" bends toward
  the parent's +normal (the side the sheet's top faces), "down" toward the other side. angle is the bend angle:
  how far the flange turns from the parent's plane (90 for a right angle, 180 for a hem).
- A flange spans the whole edge unless `start` / `end` (mm from each end) shorten it; a shortened flange cuts a
  relief at each shortened end into the parent: `relief="rect"` or `"obround"`, width (default t) and depth
  (default r + t). The relief width ≥ t follows Fractory, *Sheet Metal Bending* (2026-09-21 revision, read
  2026-11-28): "The width of such a cut should be above the material thickness." The depth r + t is Form Studio's
  default (unsourced): it reaches past the bend zone.
- A hem is a flange of angle 180 with an inside radius of half its gap (default gap = t, Protolabs' minimum inside
  diameter, see form/sheet/tables/bend.toml).
- A louvre is a formed feature: a lanced, raised hood. It is not developable, so the unfold reports it and does not
  lay it flat (form/sheet/unfold.py); `solid(forms=False)` builds the sheet without it and `marks()` gives its
  footprint for the flat pattern's etch layer.

Nothing here decides whether a part can be made: the sheet-metal rules (form/dfm/rules/sheet_metal.toml) and the
unfold do, on the solid this returns.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


class SheetError(ValueError):
    pass


def _v(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _unit(x) -> np.ndarray:
    x = _v(x)
    n = float(np.linalg.norm(x))
    if n < 1e-12:
        raise SheetError("A zero-length direction.")
    return x / n


@dataclass
class Edge:
    """An edge a flange can be bent from: a frame on its parent (origin at the edge's start, u along the edge, o
    outward in the parent's plane, n the parent's normal toward its top side), its length and its parent."""
    origin: np.ndarray
    u: np.ndarray
    o: np.ndarray
    n: np.ndarray
    length: float
    parent: "Plate"
    name: str = ""


@dataclass
class Plate:
    """A flat piece of the sheet: the base or a flange's straight part."""
    kind: str                         # base | flange
    name: str
    sheet: "Sheet"
    outline: list = field(default_factory=list)       # base: 2D polygon (CCW) in its own frame
    frame: tuple | None = None                         # flange: (origin, u, o, n), width along u, length along o
    width: float = 0.0
    length: float = 0.0

    def edge(self, i: int) -> Edge:
        """Edge i of the base outline (from vertex i to i + 1), or for a flange: 0 the far edge, 1 and 3 its
        sides (not supported as bend edges), 2 the bend edge itself (not free)."""
        if self.kind != "base":
            if i == 0:
                return self.far()
            raise SheetError("A flange's only free bend edge here is its far edge (edge 0, or far()).")
        pts = self.outline
        n = len(pts)
        a, b = _v(pts[i % n]), _v(pts[(i + 1) % n])
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 1e-9:
            raise SheetError(f"Edge {i} of the base has no length.")
        dirv = np.array([d[0], d[1], 0.0]) / L
        u = -dirv                                         # walk it backwards: (u, o, n) is right-handed
        o = np.array([dirv[1], -dirv[0], 0.0])            # outward of a counter-clockwise outline
        return Edge(np.array([b[0], b[1], 0.0]), u, o, np.array([0.0, 0.0, 1.0]), L, self, f"{self.name}.e{i}")

    def far(self) -> Edge:
        if self.kind == "base":
            raise SheetError("The base has edges 0..n-1, not a far edge.")
        O, u, o, n = self.frame
        return Edge(O + o * self.length, u, o, n, self.width, self, f"{self.name}.far")


@dataclass
class Bend:
    name: str
    edge: Edge
    angle: float
    r: float
    up: bool
    start: float
    end: float
    child: Plate | None = None

    def axis(self):
        """(point on the axis, unit direction) of the bend's cylinders."""
        e, t = self.edge, self.edge.parent.sheet.t
        O = e.origin + e.u * self.start
        c = O + e.n * (t + self.r) if self.up else O - e.n * self.r
        return c, e.u


@dataclass
class Louvre:
    plate: Plate
    at: tuple
    length: float
    width: float
    height: float


class Sheet:
    """One sheet-metal part: thickness t, inside bend radius r (one per sheet unless a flange sets its own)."""

    def __init__(self, t: float, r: float | None = None, material: str = ""):
        if t <= 0:
            raise SheetError("Thickness t must be positive.")
        self.t = float(t)
        self.r = float(r) if r is not None else self.t
        if self.r < 0:
            raise SheetError("The inside bend radius cannot be negative.")
        self.material = material
        self.base_plate: Plate | None = None
        self.bends: list[Bend] = []
        self.reliefs: list[tuple] = []
        self.louvres: list[Louvre] = []

    # ---- features ---------------------------------------------------------------------------------------------
    def base(self, outline) -> Plate:
        """The base flange: a polygon [(x, y), ...] in XY (made counter-clockwise), extruded t up from z = 0."""
        pts = [(float(x), float(y)) for x, y in outline]
        if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) < 3:
            raise SheetError("The base outline needs at least three points.")
        a = 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))
        if abs(a) < 1e-9:
            raise SheetError("The base outline has no area.")
        if a < 0:
            pts = pts[::-1]
        self.base_plate = Plate("base", "base", self, outline=pts)
        return self.base_plate

    def flange(self, edge: Edge, length: float, angle: float = 90.0, r: float | None = None, up: bool = True,
               start: float = 0.0, end: float = 0.0, relief: str = "rect", relief_w: float | None = None,
               relief_d: float | None = None, name: str = "") -> Plate:
        """An edge flange: bent `angle` degrees about `edge` (up or down), straight for `length` after the bend."""
        if not 0 < angle <= 180:
            raise SheetError("A bend angle is between 0 and 180 degrees.")
        if length < 0:
            raise SheetError("A flange length cannot be negative.")
        r = self.r if r is None else float(r)
        width = edge.length - start - end
        if width <= 1e-6:
            raise SheetError(f"The flange on {edge.name} has no width left after start and end.")
        if any(b.edge.parent is edge.parent and b.edge.name == edge.name for b in self.bends):
            raise SheetError(f"{edge.name} already has a flange.")
        name = name or f"flange{len(self.bends) + 1}"
        b = Bend(name, edge, float(angle), r, bool(up), float(start), float(end))
        th = math.radians(angle)
        u, o, n = edge.u, edge.o, edge.n
        O = edge.origin + u * start
        t = self.t
        if up:
            C = O + n * (t + r)
            org = C + (r + t) * (math.sin(th) * o - math.cos(th) * n)
            o2 = o * math.cos(th) + n * math.sin(th)
            n2 = n * math.cos(th) - o * math.sin(th)
        else:
            C = O - n * r
            org = C + r * (math.sin(th) * o + math.cos(th) * n)
            o2 = o * math.cos(th) - n * math.sin(th)
            n2 = n * math.cos(th) + o * math.sin(th)
        child = Plate("flange", name, self, frame=(org, u.copy(), o2, n2), width=width, length=float(length))
        b.child = child
        self.bends.append(b)
        rw = self.t if relief_w is None else float(relief_w)
        rd = (r + self.t) if relief_d is None else float(relief_d)
        for s0, shortened in ((start, start > 1e-9), (edge.length - end, end > 1e-9)):
            if shortened:
                self.reliefs.append((edge, s0, rw, rd, relief, s0 == start))
        return child

    def hem(self, edge: Edge, length: float, gap: float | None = None, up: bool = True, name: str = "") -> Plate:
        """A closed hem folded back over its parent: 180°, inside radius gap / 2 (default gap: t)."""
        gap = self.t if gap is None else float(gap)
        return self.flange(edge, length, 180.0, r=gap / 2, up=up, name=name or f"hem{len(self.bends) + 1}")

    def jog(self, edge: Edge, offset: float, length: float, angle: float = 90.0, r: float | None = None,
            up: bool = True) -> Plate:
        """A jog (joggle): a bend and the opposite bend, so the sheet continues parallel to its parent, `offset`
        higher (bottom face to bottom face), for `length` after the second bend."""
        r = self.r if r is None else float(r)
        th = math.radians(angle)
        rise = (2 * r + self.t) * (1 - math.cos(th))
        if offset < rise - 1e-9:
            raise SheetError(f"A jog of {offset:g} mm at {angle:g}° needs at least {rise:.3f} mm with r {r:g} and t "
                             f"{self.t:g} (two bends).")
        web = (offset - rise) / math.sin(th) if th < math.pi - 1e-9 else 0.0
        a = self.flange(edge, web, angle, r=r, up=up, name=f"jog{len(self.bends) + 1}a")
        return self.flange(a.far(), length, angle, r=r, up=not up, name=f"jog{len(self.bends) + 1}b")

    def louvre(self, plate: Plate, at, length: float, width: float, height: float) -> Louvre:
        """A louvre on the base: a slot `length` x `width` (its long side along X) lanced at one long side and the
        hood raised `height` at the other. A formed feature: not developable, so not laid flat by the unfold."""
        if plate.kind != "base":
            raise SheetError("Louvres are placed on the base here.")
        lv = Louvre(plate, (float(at[0]), float(at[1])), float(length), float(width), float(height))
        self.louvres.append(lv)
        return lv

    # ---- the solid --------------------------------------------------------------------------------------------
    def solid(self, forms: bool = True):
        """The part as one build123d solid (z = 0 is the base's bottom)."""
        from build123d import Box, Location, Plane, Polyline, Pos, Solid, extrude, make_face
        if self.base_plate is None:
            raise SheetError("A sheet starts with base().")
        t = self.t
        pts = self.base_plate.outline
        body = extrude(make_face(Polyline(*pts, pts[0])), amount=t)
        pieces = []
        for b in self.bends:
            c, ax = b.axis()
            e = b.edge
            width = e.length - b.start - b.end
            if b.up:
                x_dir, z_dir = -e.n, e.u
            else:
                x_dir, z_dir = e.n, -e.u
            org = c if b.up else c
            if not b.up:
                org = c + e.u * width                    # the sweep goes the other way round: start at the far end
            pl = Plane(origin=tuple(org), x_dir=tuple(x_dir), z_dir=tuple(z_dir))
            ro = b.r + t
            sector = Solid.make_cylinder(ro, width, pl, angle=b.angle)
            if b.r > 1e-9:
                sector = sector - Solid.make_cylinder(b.r, width, pl, angle=b.angle)
            pieces.append(sector)
            ch = b.child
            if ch.length > 1e-9:
                O, u, o, n = ch.frame
                pl2 = Plane(origin=tuple(O + u * (ch.width / 2) + o * (ch.length / 2) + n * (t / 2)),
                            x_dir=tuple(u), z_dir=tuple(n))
                pieces.append(Location(pl2) * Box(ch.width, ch.length, t))
        for p in pieces:
            body = body + p
        for e, s0, w, d, kind, at_start in self.reliefs:
            # the relief: w wide along the edge, beside the flange, d deep into the parent, through the sheet
            sgn = -1.0 if at_start else 1.0
            cu = e.origin + e.u * (s0 + sgn * w / 2)
            ctr = cu - e.o * (d / 2) + e.n * (t / 2)
            if kind == "obround":
                # the straight part ends exactly at the round end's centre (no sliver), and runs 0.01 mm past the
                # parent's edge so the cut opens cleanly
                ctr = cu - e.o * ((d - w / 2 - 0.01) / 2) + e.n * (t / 2)
                pl = Plane(origin=tuple(ctr), x_dir=tuple(e.u), z_dir=tuple(e.n))
                cut = Location(pl) * Box(w, d - w / 2 + 0.01, t * 3)
                tip = cu - e.o * (d - w / 2)
                from build123d import Cylinder
                cut = cut + Location(Plane(origin=tuple(tip + e.n * (t / 2)), x_dir=tuple(e.u), z_dir=tuple(e.n))) \
                    * Cylinder(w / 2, t * 3)
            else:
                pl = Plane(origin=tuple(ctr + e.o * 0.01), x_dir=tuple(e.u), z_dir=tuple(e.n))
                cut = Location(pl) * Box(w, d + 0.02, t * 3)
            body = body - cut
        if forms:
            for lv in self.louvres:
                body = self._louvre(body, lv)
        return body.solid() if hasattr(body, "solid") and not hasattr(body, "volume") else body

    def _louvre(self, body, lv: Louvre):
        from build123d import Box, Plane, Polyline, Pos, extrude, make_face
        t = self.t
        x, y = lv.at
        L, W, h = lv.length, lv.width, lv.height
        body = body - Pos(x, y, t / 2) * Box(L, W, t * 3)
        # the hood: hinged at the slot's -Y side, raised h at its +Y side; ends closed by two walls
        y0, y1 = y - W / 2, y + W / 2
        prof = [(y0, 0.0), (y1, h), (y1, h + t), (y0, t)]
        sec = make_face(Plane.YZ * Polyline(*prof, prof[0]))
        hood = Pos(x - L / 2, 0, 0) * extrude(sec, amount=L)
        tri = [(y0, 0.0), (y1, 0.0), (y1, h)]
        wall = make_face(Plane.YZ * Polyline(*tri, tri[0]))
        hood = hood + Pos(x - L / 2, 0, 0) * extrude(wall, amount=t) + Pos(x + L / 2 - t, 0, 0) * extrude(wall, amount=t)
        return body + hood

    def marks(self) -> list:
        """Footprints of formed features (louvres) on the base, as closed 2D polylines in the base's XY frame."""
        out = []
        for lv in self.louvres:
            x, y = lv.at
            L, W = lv.length, lv.width
            out.append({"kind": "louvre", "pts": [(x - L / 2, y - W / 2), (x + L / 2, y - W / 2), (x + L / 2, y + W / 2),
                                                  (x - L / 2, y + W / 2)], "lance": [(x - L / 2, y + W / 2), (x + L / 2, y + W / 2)]})
        return out

    def describe(self) -> dict:
        """The design intent: bends (angle, radius, direction), for reports and tests."""
        return {"t": self.t, "r": self.r, "material": self.material,
                "bends": [{"name": b.name, "angle": b.angle, "r": b.r, "up": b.up, "width": b.edge.length - b.start - b.end,
                           "length": b.child.length} for b in self.bends],
                "reliefs": len(self.reliefs), "louvres": len(self.louvres)}
