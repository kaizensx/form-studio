"""The design language of the built-in library: one set of proportions, edges and print rules.

Every built-in recipe uses these so the library reads as one family: soft vertical corners, a 45° chamfer where the
part meets the plate (it hides the first-layer flare, the "elephant foot", and never needs support), rounded top
edges, and holes that print without support whichever way they face.

Print rules the helpers keep:
  - nothing faces down more steeply than 45° except the plate face and short bridges;
  - walls are whole multiples of a 0.4 mm line (two lines at the very least, three by default);
  - horizontal holes are teardrops (their roof is two 45° flanks), so they print in any wall.
"""
from __future__ import annotations

import math

from build123d import (Align, Axis, Box, Cylinder, Plane, Polygon, Pos, Rot, chamfer, extrude, fillet)

A = (Align.CENTER, Align.CENTER, Align.MIN)        # centred in plan, sitting on z = 0

LINE = 0.4          # extrusion width the walls are designed around (0.4 mm nozzle)
WALL = 1.6          # default wall: four lines
FOOT = 0.4          # 45° chamfer where a part meets the plate
SOFT = 1.0          # top-edge radius on small parts
CORNER = 4.0        # plan-view corner radius on hand-sized parts


def rbox(w: float, d: float, h: float, r: float = CORNER, z: float = 0.0, foot: float = FOOT, top: float = 0.0):
    """A box, centred in plan, from z to z + h, with plan corners of radius r, a 45° foot chamfer and a rounded top edge.

    foot  45° chamfer around the bottom edge (0 = none). Only on parts that sit on the plate.
    top   radius on the top outer edge (0 = sharp)."""
    r = max(0.0, min(r, w / 2 - 0.05, d / 2 - 0.05))
    b = Box(w, d, h, align=A)
    if r > 0.05:
        b = fillet(b.edges().filter_by(Axis.Z), r)
    if top > 0.05:
        try:
            b = fillet(b.edges().group_by(Axis.Z)[-1], min(top, h / 2 - 0.05, r - 0.05 if r > 0.1 else top))
        except Exception:
            pass
    if foot > 0.05:
        try:
            b = chamfer(b.edges().group_by(Axis.Z)[0], min(foot, h / 3))
        except Exception:
            pass
    return Pos(0, 0, z) * b


def soften_top(shape, r: float = SOFT, z: float | None = None):
    """Round every edge lying in the topmost plane (or the plane at height z). Leaves the shape as it was if OCCT refuses."""
    try:
        groups = shape.edges().group_by(Axis.Z)
        es = groups[-1] if z is None else [e for e in shape.edges() if abs(e.center().Z - z) < 1e-4
                                            and abs(e.bounding_box().size.Z) < 1e-4]
        return fillet(es, r) if es else shape
    except Exception:
        return shape


def foot_chamfer(shape, c: float = FOOT):
    """45° chamfer on every edge lying on the plate (z = min)."""
    try:
        return chamfer(shape.edges().group_by(Axis.Z)[0], c)
    except Exception:
        return shape


def teardrop(d: float, length: float, plane: Plane = Plane.XZ, centered: bool = True):
    """A hole of diameter d, `length` long, whose roof rises at 45° to a point: prints across a vertical wall.

    The profile is drawn in `plane` (its Y is "up" in the print) and extruded along the plane's normal.
    Plane.XZ: a hole along -Y with up = +Z.  Plane.YZ: a hole along +X with up = +Z."""
    from build123d import Circle
    r = d / 2
    q = r / math.sqrt(2)
    # a true circle (so the hole measures d) plus a 45° roof: the square on the radius to the tangent points
    face = plane * (Circle(r) + Polygon((0, 0), (q, q), (0, 2 * q), (-q, q), align=None))
    return extrude(face, length / 2 if centered else length, both=centered)


def countersink(head_d: float, hole_d: float, depth_extra: float = 0.2):
    """A 90° countersink cone (point down) whose top, at z = 0, is head_d wide; plus the clearance hole below it.

    Place it with its top on the face the screw head sits in, pointing into the part."""
    from build123d import Cone
    h = (head_d - hole_d) / 2 + depth_extra
    cone = Pos(0, 0, -h) * Cone(hole_d / 2, head_d / 2 + depth_extra, h, align=A)
    return cone + Pos(0, 0, -60) * Cylinder(hole_d / 2, 60.01, align=A)


def screw_for(d: float) -> dict:
    """Wood or drywall screw sizes by shank: clearance hole and flat-head diameter (assumed, typical catalogue values)."""
    return {"hole": d + 0.5, "head": round(d * 2.0, 1)}
