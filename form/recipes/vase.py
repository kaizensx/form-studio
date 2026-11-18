"""Faceted vase and lamp shade: a low-poly body of flat triangles, twisted and bellied, that prints in vase mode.

The body is built facet by facet: rings of points up the height, each ring turned by the twist and (in the diamond
style) by half a facet against the one below, joined by flat triangles. Flat facets keep the exported mesh identical to
the CAD solid and give the crisp light-catching look of a low-poly vase. The wall is a second, smaller faceted surface
inside, so the part also prints as an ordinary hollow vase; in spiral ("vase") mode the slicer keeps only the outside.

Every facet is checked for its angle: none faces down more than 42° from vertical, so it prints without support. The
belly, neck and twist are limited by that rule, and the constraint names whichever one breaks it.

Lamp shade: the floor becomes the shade ring, with a hole for the lamp holder's thread and a ring of vents. It prints
ring-down and hangs ring-up. E27 holders take a shade ring on a thread about 40 mm across (assumed; measure yours).
"""
from __future__ import annotations

import math

from build123d import Align, Cylinder, Face, Pos, Shell, Solid, Wire

from .base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)
FOOT = 0.4
K = 1 / math.tan(math.radians(40))
MAX_DOWN = math.cos(math.radians(42))      # steepest allowed downward facet: 42° from vertical (the check warns past 45°)


def _blend(z, knots):
    """Radius at height z through (z, r) knots, eased (zero slope at every knot)."""
    for (z0, r0), (z1, r1) in zip(knots, knots[1:]):
        if z <= z1 + 1e-9:
            u = 0.0 if z1 - z0 < 1e-9 else max(0.0, min(1.0, (z - z0) / (z1 - z0)))
            return r0 + (r1 - r0) * (1 - math.cos(math.pi * u)) / 2
    return knots[-1][1]


class Vase(Recipe):
    id = "vase"
    title = "Faceted vase and lamp shade"
    summary = ("A low-poly vase of flat, twisted facets with a belly and neck you shape; prints hollow or in vase mode, "
               "or as a lamp shade for an E27 holder.")
    category = "Home"
    tags = ("vase", "vase mode", "spiral", "lamp shade", "low poly", "decor", "flowers")

    params = [
        Param("height", "Height", 150, 40, 175, 1, "mm", "form", "body"),
        Param("d_bottom", "Base diameter", 64, 30, 160, 1, "mm", "form", "body", "Across the corners of the base polygon."),
        Param("d_belly", "Belly diameter", 92, 30, 170, 1, "mm", "form", "body", "Widest point."),
        Param("belly_at", "Belly height", 0.42, 0.15, 0.85, 0.01, "", "form", "body", "Where the belly sits, as a fraction of the height."),
        Param("d_top", "Mouth diameter", 58, 20, 170, 1, "mm", "form", "body"),
        Param("sides", "Facets around", 14, 6, 40, 1, "", "form", "body", "Number of facets around the body."),
        Param("bands", "Bands up", 10, 2, 30, 1, "", "form", "body", "Rings of facets from base to mouth."),
        Param("diamond", "Diamond facets", 1, 0, 1, 1, "", "form", "body",
              "1 = each band turned half a facet against the one below (triangular facets); 0 = facets in columns."),
        Param("twist", "Twist", 30, -120, 120, 1, "deg", "form", "body", "Turn of the mouth against the base."),
        Param("wall", "Wall", 1.6, 1.2, 4, 0.1, "mm", "form", "cavity",
              "For an ordinary print. In vase mode the slicer prints one line on the outside instead."),
        Param("floor", "Floor", 2.0, 1.2, 6, 0.1, "mm", "form", "cavity"),
        Param("lamp", "Lamp shade", 0, 0, 1, 1, "", "form", "lamp_ring",
              "1 = a hole in the floor for the lamp holder and a ring of vents. Prints ring-down, hangs ring-up."),
        Param("holder_d", "Lamp holder thread", 40, 20, 60, 0.1, "mm", "brief", "lamp_ring",
              "Measure the outside of the thread the shade ring screws onto. E27 holders are about 40 mm (assumed); E14 about 28 mm.",
              "assumed"),
        Param("holder_clear", "Holder clearance / side", 0.4, 0.1, 1.5, 0.05, "mm", "interface", "lamp_ring"),
        Param("vents", "Vents", 8, 0, 16, 1, "", "form", "vents", "Holes around the holder that let heat out. 0 = none."),
    ]
    features = [
        Feature("body", "Faceted body", "structure"),
        Feature("cavity", "Inside", "access"),
        Feature("lamp_ring", "Holder hole", "interface", "The shade ring: clears the lamp holder's thread."),
        Feature("vents", "Vents", "access"),
    ]

    # ---- geometry -------------------------------------------------------------------------------
    @staticmethod
    def rings(v):
        """Outer and inner rings of points: lists of (z, [(x, y, z) ...])."""
        H, n, m = v["height"], int(round(v["sides"])), int(round(v["bands"]))
        knots = [(0.0, v["d_bottom"] / 2), (v["belly_at"] * H, v["d_belly"] / 2), (H, v["d_top"] / 2)]
        tw = math.radians(v["twist"])
        step = 2 * math.pi / n
        def ring(z, r, j):
            a0 = tw * z / H + (step / 2 if (v["diamond"] >= 0.5 and j % 2) else 0.0)
            return [(r * math.cos(a0 + i * step), r * math.sin(a0 + i * step), z) for i in range(n)]
        lift = FOOT * K
        outer = [ring(0.0, knots[0][1] - FOOT, 0), ring(lift, _blend(lift, knots), 0)]
        for j in range(1, m + 1):
            z = H * j / m
            outer.append(ring(z, _blend(z, knots), j))
        # the inside: the same rings, smaller by the wall measured square to the facets (the corner radius of a
        # polygon whose flats are `wall` inside the outer flats), starting at the floor
        cw = v["wall"] / math.cos(math.pi / n)
        inner = [ring(v["floor"], _blend(v["floor"], knots) - cw, 0)]
        for j in range(1, m + 1):
            z = H * j / m
            inner.append(ring(z, _blend(z, knots) - cw, j))
        return outer, inner

    @staticmethod
    def _tris(rings, flip=False):
        """Triangles joining consecutive rings, wound so the normal points away from the axis (towards it if flip)."""
        out = []
        for lo, hi in zip(rings, rings[1:]):
            n = len(lo)
            step = 2 * math.pi / n
            mid = math.atan2(lo[0][1], lo[0][0]) + step / 2
            # the point of the upper ring that sits over the gap between lo[0] and lo[1] (diamond facets), or over
            # lo[0] itself (columns): whichever of hi[0], hi[1] is nearer in angle
            def off(p, target):
                d = (math.atan2(p[1], p[0]) - target) % (2 * math.pi)
                return min(d, 2 * math.pi - d)
            diamond = off(hi[0], mid) < step / 4 or off(hi[1], mid) < step / 4
            k = (0 if off(hi[0], mid) <= off(hi[1], mid) else 1) if diamond else 0
            h = hi[k:] + hi[:k]
            for i in range(n):
                t1 = (lo[i], lo[(i + 1) % n], h[i])
                t2 = (h[i], lo[(i + 1) % n], h[(i + 1) % n])
                out += [t1[::-1], t2[::-1]] if flip else [t1, t2]
        return out

    def facets(self, v):
        outer, inner = self.rings(v)
        return self._tris(outer), self._tris(inner, flip=True), outer, inner

    @staticmethod
    def _normal(t):
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = t
        ux, uy, uz, wx, wy, wz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx
        L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        return nx / L, ny / L, nz / L

    def steepest(self, v):
        """The most downward-facing facet (outside, then inside), as the cosine of its angle from straight down."""
        to, ti, outer, _ = self.facets(v)
        lift_band = 2 * len(outer[0])                      # the foot chamfer band is meant to face down at 40°
        do = max((-self._normal(t)[2] for t in to[lift_band:]), default=0.0)
        di = max((-self._normal(t)[2] for t in ti), default=0.0)
        return do, di

    def constraints(self, v):
        out = []
        for k in ("sides", "bands", "diamond", "lamp", "vents"):
            if abs(v[k] - round(v[k])) > 1e-9:
                out.append(RecipeError(f"{self.spec(k).label} must be a whole number", self.spec(k).feature, "Use whole numbers.", [k]))
        if out:
            return out
        if v["d_top"] / 2 - v["wall"] / math.cos(math.pi / v["sides"]) < 6:
            out.append(RecipeError("The mouth is too narrow for the wall", "cavity", "Widen the mouth or thin the wall.", ["d_top", "wall"]))
        do, di = self.steepest(v)
        if do > MAX_DOWN:
            out.append(RecipeError(f"Some outside facets face {math.degrees(math.acos(do)):.0f}° from straight down; "
                                   "steeper than 42° needs support", "body",
                                   "Narrow the belly, raise it, or reduce the twist; more bands also soften the steps.",
                                   ["d_belly", "belly_at", "twist", "bands", "d_bottom"]))
        if di > MAX_DOWN:
            out.append(RecipeError(f"The inside of the neck faces {math.degrees(math.acos(di)):.0f}° from straight down; "
                                   "the neck closes in too fast to print", "cavity",
                                   "Widen the mouth, raise the belly less high, or add bands.", ["d_top", "belly_at", "d_belly", "bands"]))
        if v["lamp"] >= 0.5:
            rb = v["d_bottom"] / 2 * math.cos(math.pi / v["sides"]) - v["wall"]
            need = (v["holder_d"] / 2 + v["holder_clear"]) + (9 if v["vents"] else 3)
            if need > rb:
                out.append(RecipeError(f"The holder hole and vents need a base about {2 * need + 2 * v['wall']:.0f} mm across",
                                       "lamp_ring", "Widen the base, or use no vents.", ["d_bottom", "vents", "holder_d"]))
        return out

    def build(self, v):
        to, ti, outer, inner = self.facets(v)
        fz = lambda pts: Face(Wire.make_polygon([*pts], close=True))
        bottom = [fz(outer[0][::-1])]
        top_o, top_i = outer[-1], inner[-1]
        n = len(top_o)
        # filled body: outside facets, the base and a flat top
        body = Solid(Shell([fz(t) for t in to] + bottom + [fz(top_o)]))
        stages = [Stage("body", body)]
        # cavity: inside facets, its floor and a lid above the mouth
        H = v["height"]
        lid = [(x, y, H + 1) for x, y, _ in top_i]
        side = []
        for i in range(n):
            a, b = top_i[i], top_i[(i + 1) % n]
            side.append(fz([a, b, lid[(i + 1) % n], lid[i]]))
        cav = Solid(Shell([fz(t) for t in self._tris(inner)] + [fz(inner[0][::-1])] + side + [fz(lid)]))
        s = body - cav
        stages.append(Stage("cavity", s))
        if v["lamp"] >= 0.5:
            r = v["holder_d"] / 2 + v["holder_clear"]
            s = s - Pos(0, 0, -1) * Cylinder(r, v["floor"] + 2, align=A)
            stages.append(Stage("lamp_ring", s))
            nv = int(round(v["vents"]))
            if nv:
                rb = v["d_bottom"] / 2 * math.cos(math.pi / v["sides"]) - v["wall"]
                rv = (r + rb) / 2
                dv = min(6.0, (rb - r) - 2.4)
                holes = None
                for i in range(nv):
                    a = 2 * math.pi * (i + 0.5) / nv
                    h = Pos(rv * math.cos(a), rv * math.sin(a), -1) * Cylinder(dv / 2, v["floor"] + 2, align=A)
                    holes = h if holes is None else holes + h
                s = s - holes
                stages.append(Stage("vents", s))
        return stages

    # ---- interfaces -----------------------------------------------------------------------------
    def volume_ml(self, v):
        """What the vase holds up to the mouth: the inner rings as stacked frusta of their polygons."""
        _, inner = self.rings(v)
        n = len(inner[0])
        area = lambda ring: 0.5 * n * (math.hypot(ring[0][0], ring[0][1]) ** 2) * math.sin(2 * math.pi / n)
        tot = 0.0
        for lo, hi in zip(inner, inner[1:]):
            h, a0, a1 = hi[0][2] - lo[0][2], area(lo), area(hi)
            tot += h * (a0 + a1 + math.sqrt(a0 * a1)) / 3
        return tot / 1000

    def derived(self, v):
        rows = [{"key": "volume_ml", "label": "Holds", "value": self.volume_ml(v), "unit": "mL", "feature": "cavity",
                 "formula": "inside volume up to the mouth", "interface": False},
                {"key": "steepest", "label": "Steepest facet", "value": math.degrees(math.acos(max(self.steepest(v)))),
                 "unit": "deg", "feature": "body", "formula": "from straight down; 45° or more prints without support", "interface": False}]
        if v["lamp"] >= 0.5:
            rows.append({"key": "holder_hole", "label": "Holder hole", "value": v["holder_d"] + 2 * v["holder_clear"], "unit": "mm",
                         "feature": "lamp_ring", "formula": "holder thread + 2 × clearance", "interface": True})
        return rows

    def measure(self, v, faces_by_feature):
        if v["lamp"] < 0.5:
            return []
        rs = [e.radius for f in faces_by_feature.get("lamp_ring", []) if f.geom_type.name == "CYLINDER"
              for e in f.edges() if e.geom_type.name == "CIRCLE"]
        if not rs:
            return []
        return [{"key": "holder_hole", "label": "Holder hole", "intended": v["holder_d"] + 2 * v["holder_clear"], "modelled": 2 * max(rs)}]
