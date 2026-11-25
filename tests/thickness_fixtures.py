"""Solids with thin regions planted at known places, for form/thickness.py (tests/test_thickness.py).

Each fixture is (shape, planted) where planted is a list of {"name", "kind", "t", "box"}: the region's thinnest wall
in mm (an upper bound for a knife edge, which runs to nothing) and a box (lo, hi) the region lies in. Built with
build123d only; the numbers come from the construction, not from a measurement.
"""
from __future__ import annotations

from build123d import Align, Box, Compound, Cylinder, Face, Pos, Solid, Vector, Wire

MIN = (Align.MIN, Align.MIN, Align.MIN)


def _prism(points_xz, y0, y1):
    """A prism of a polygon in the XZ plane, from y0 to y1."""
    f = Face(Wire.make_polygon([(x, y0, z) for x, z in points_xz], close=True))
    s = Solid.extrude(f, Vector(0, y1 - y0, 0))
    return s if s.volume > 0 else Solid.extrude(f, Vector(0, y0 - y1, 0))


def _ridge_yz(x0, x1, yc, z0, base, top, h):
    """A ridge running along X: a trapezoid in YZ (base width at z0, top width at z0 + h)."""
    pts = [(x0, yc - base / 2, z0), (x0, yc + base / 2, z0), (x0, yc + top / 2, z0 + h), (x0, yc - top / 2, z0 + h)]
    return Solid.extrude(Face(Wire.make_polygon(pts, close=True)), Vector(x1 - x0, 0, 0))


def block_with_seven():
    """An 80 × 50 × 20 block carrying seven thin places of different kinds."""
    s = Box(80, 50, 20, align=MIN)
    s += Pos(5, 5, 20) * Box(0.5, 15, 8, align=MIN)                                 # fin, 0.5 mm
    s -= Pos(20, 5, 0) * Box(15, 15, 19.6, align=MIN)                               # pocket from below: 0.4 mm skin
    s -= Pos(45, 3.6, 0) * Cylinder(3, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))   # hole 0.6 mm from y = 0
    s -= Pos(55, 47.3, 0) * Box(10, 2, 20, align=MIN)                               # slot: 0.7 mm wall to y = 50
    s += _prism([(80, 20), (95, 20), (80, 16)], 30, 45)                             # lip tapering to a knife edge at x = 95
    s += _ridge_yz(10, 40, 35, 20, 5.0, 0.4, 10.0)                                  # ridge, flanks 26° apart, 0.4 mm top
    s += Pos(70, 10, 20) * Box(0.3, 0.5, 0.5, align=MIN)                            # a speck: 0.3 × 0.5 × 0.5
    lip_x = 95 - 1.2 * 15 / 4                                                       # where the lip gets under 1.2 mm
    ridge_z = 20 + 10 * (1 - (1.2 - 0.4) / 4.6)
    planted = [
        {"name": "fin", "kind": "wall", "t": 0.5, "box": ((5, 5, 20), (5.5, 20, 28))},
        {"name": "skin", "kind": "wall", "t": 0.4, "box": ((20, 5, 19.6), (35, 20, 20))},
        {"name": "web", "kind": "wall", "t": 0.6, "box": ((42, 0, 0), (48, 0.6, 20))},
        {"name": "slot wall", "kind": "wall", "t": 0.7, "box": ((55, 49.3, 0), (65, 50, 20))},
        {"name": "lip", "kind": "knife_edge", "t": 0.05, "box": ((lip_x, 30, 16), (95, 45, 20))},
        {"name": "ridge", "kind": "crest", "t": 0.4, "box": ((10, 35 - 0.6, ridge_z), (40, 35 + 0.6, 30))},
        {"name": "speck", "kind": "sliver", "t": 0.3, "box": ((70, 10, 20), (70.3, 10.5, 20.5))},
    ]
    return s, planted


def tube_and_plate():
    """Two parts 2 mm apart: a tube with a 0.6 mm wall and a plate with a 0.45 mm web between two pockets."""
    tube = Pos(-30, 0, 0) * (Cylinder(10, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
                             - Cylinder(9.4, 30, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    plate = Box(40, 30, 6, align=MIN)
    plate -= Pos(5, 5, 1) * Box(10, 20, 5, align=MIN)
    plate -= Pos(15.45, 5, 1) * Box(10, 20, 5, align=MIN)                           # web 15.0 to 15.45
    parts = Compound([tube, plate])
    planted = [
        {"name": "tube wall", "kind": "wall", "t": 0.6, "box": ((-40, -10, 0), (-20, 10, 30))},
        {"name": "web", "kind": "wall", "t": 0.45, "box": ((15, 5, 1), (15.45, 25, 6))},
    ]
    return parts, planted


def touching_parts():
    """A 5 mm plate with a 5 mm block resting on it: two parts, neither thin where they touch."""
    return Compound([Box(40, 30, 5, align=MIN), Pos(10, 5, 5) * Box(20, 20, 5, align=MIN)]), []


FIXTURES = {"block_with_seven": block_with_seven, "tube_and_plate": tube_and_plate, "touching_parts": touching_parts}


def found(region, planted, slack=0.5) -> bool:
    """A reported region is the planted one when its box meets the planted box and its minimum is the planted wall."""
    (lo, hi), (plo, phi) = region["bbox"], planted["box"]
    meets = all(lo[i] <= phi[i] + slack and hi[i] >= plo[i] - slack for i in range(3))
    thin = region["min_mm"] <= planted["t"] + 0.05 and (planted["kind"] == "knife_edge" or region["min_mm"] >= planted["t"] - 0.05)
    return meets and thin


def recall(regions, planted) -> tuple[int, list]:
    hit = [p["name"] for p in planted if any(found(r, p) for r in regions)]
    return len(hit), hit


def point_in(p, planted, slack=0.5) -> bool:
    lo, hi = planted["box"]
    return all(lo[i] - slack <= p[i] <= hi[i] + slack for i in range(3))

