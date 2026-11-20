"""Known parts for the mesh-reconstruction tests, built with build123d and exported as STL.

Each fixture returns (solid, facts): facts are the dimensions the reconstruction should find again.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def box_with_holes():
    from build123d import Align, Box, Cylinder, Pos
    A = (Align.CENTER, Align.CENTER, Align.MIN)
    body = Box(60, 40, 10, align=A)
    holes = [(-22, -12), (22, -12), (-22, 12), (22, 12)]
    for x, y in holes:
        body = body - Pos(x, y, -1) * Cylinder(2.75, 12, align=A)          # Ø5.5: M5 clearance
    body = body - Pos(0, 0, -1) * Cylinder(4.0, 12, align=A)               # Ø8 centre bore
    return body, {"holes": sorted([5.5] * 4 + [8.0]), "prismatic": True}


def turned_part():
    from build123d import Axis, Plane, Polyline, extrude, make_face, revolve, fillet, chamfer
    pts = [(4, 0), (15, 0), (15, 10), (10, 10), (10, 25), (4, 25)]          # r, z: Ø30 flange, Ø20 shaft, Ø8 bore
    face = make_face(Plane.XZ * Polyline(*pts, close=True))
    part = revolve(face, Axis.Z)
    def circle_at(r, z):
        return [e for e in part.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - r) < 1e-6 and abs(e.center().Z - z) < 1e-6]
    part = fillet(circle_at(10, 10), 2.0)                                     # torus where the shaft meets the flange
    part = chamfer([e for e in part.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - 15) < 1e-6
                    and abs(e.center().Z - 10) < 1e-6], 1.0)                  # cone on the flange's top edge
    return part, {"holes": [8.0], "prismatic": False}


def filleted_bracket():
    from build123d import Align, Axis, Cylinder, Plane, Polyline, Pos, Rot, extrude, fillet, make_face
    t, L, H, W = 5.0, 40.0, 30.0, 24.0
    prof = make_face(Plane.XZ * Polyline((0, 0), (L, 0), (L, t), (t, t), (t, H), (0, H), close=True))
    body = extrude(prof, -W)                                                # along +Y, 0..W
    inner = body.edges().filter_by(Axis.Y).sort_by_distance((t, W / 2, t))[0]
    body = fillet(inner, 4.0)
    outer = body.edges().filter_by(Axis.Y).sort_by_distance((0, W / 2, 0))[0]
    body = fillet(outer, 3.0)
    A = (Align.CENTER, Align.CENTER, Align.MIN)
    for x in (18.0, 32.0):                                                  # Ø6.6: M6 clearance through the base
        body = body - Pos(x, W / 2, -1) * Cylinder(3.3, t + 2, align=A)
    body = body - Pos(-1, W / 2, 20) * Rot(0, 90, 0) * Cylinder(3.3, t + 2, align=A)
    return body, {"holes": [6.6, 6.6, 6.6], "prismatic": True}


def gear(teeth: int = 18, module: float = 2.0, width: float = 8.0, bore: float = 10.0):
    """Spur gear with involute flanks (splines: not plane, cylinder, cone, sphere or torus)."""
    from build123d import Align, Cylinder, Line, Pos, Spline, Wire, extrude, make_face
    z, m = teeth, module
    rp, rb = z * m / 2, z * m / 2 * math.cos(math.radians(20))
    ra, rf = rp + m, rp - 1.25 * m
    inv = lambda a: math.tan(a) - a
    a_p = math.acos(rb / rp)
    half = math.pi / (2 * z) + inv(a_p)                       # half tooth angle at the base circle
    edges = []
    pts_all = []
    for k in range(z):
        c = 2 * math.pi * k / z
        flank = []
        for r in np.linspace(max(rb, rf), ra, 7):
            a = math.acos(rb / r)
            flank.append((r, inv(a)))
        left = [(r * math.cos(c - half + t), r * math.sin(c - half + t)) for r, t in flank]
        right = [(r * math.cos(c + half - t), r * math.sin(c + half - t)) for r, t in reversed(flank)]
        pts_all.append((left, right))
    for k in range(z):
        left, right = pts_all[k]
        nl, _ = pts_all[(k + 1) % z]
        edges.append(Spline(*[(x, y, 0) for x, y in left]))
        edges.append(Line((*left[-1], 0), (*right[0], 0)))
        edges.append(Spline(*[(x, y, 0) for x, y in right]))
        edges.append(Line((*right[-1], 0), (*nl[0], 0)))
    face = make_face(Wire(edges))
    body = extrude(face, width)
    body = body - Pos(0, 0, -1) * Cylinder(bore / 2, width + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return body, {"holes": [bore], "prismatic": True, "teeth": z}


FIXTURES = {"box_with_holes": box_with_holes, "turned_part": turned_part, "filleted_bracket": filleted_bracket, "gear": gear}


def export(name: str, folder: Path, tolerance: float = 0.01, angular: float = 0.1) -> tuple[Path, object, dict]:
    from build123d import export_stl
    solid, facts = FIXTURES[name]()
    out = Path(folder) / f"{name}.stl"
    export_stl(solid, str(out), tolerance=tolerance, angular_tolerance=angular)
    return out, solid, facts
