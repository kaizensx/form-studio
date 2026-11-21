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


def stepped_bracket():
    """A plate with a raised block at one end, a blind pocket, holes on two axes (one counterbored), rounded corners,
    a rounded inner step and a bevelled edge: what a machined bracket looks like."""
    from build123d import Align, Axis, Box, Cylinder, Pos, Rot, chamfer, fillet
    A = (Align.MIN, Align.MIN, Align.MIN)
    body = Box(80, 50, 8, align=A) + Pos(55, 0, 0) * Box(25, 50, 22, align=A)            # plate and block
    vert = body.edges().filter_by(Axis.Z)
    corners = [e for e in vert if min(abs(e.center().X), abs(e.center().X - 80)) < 1e-6
               and min(abs(e.center().Y), abs(e.center().Y - 50)) < 1e-6]
    body = fillet(corners, 5.0)                                                          # rounded plate corners
    step = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X - 55) < 1e-6 and abs(e.center().Z - 8) < 1e-6]
    body = fillet(step, 3.0)                                                             # rounded inner step
    top = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X - 55) < 1e-6 and abs(e.center().Z - 22) < 1e-6]
    body = chamfer(top, 1.5)                                                             # bevelled block edge
    body = body - Pos(20, 25, 4) * Box(24, 16, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))   # blind pocket 4 deep
    B = (Align.CENTER, Align.CENTER, Align.MIN)
    for y in (12.0, 38.0):                                                               # Ø6.6 through the plate
        body = body - Pos(42, y, -1) * Cylinder(3.3, 10, align=B)
    body = body - Pos(67.5, 14, -1) * Cylinder(3.3, 24, align=B)                          # Ø6.6 through the block ...
    body = body - Pos(67.5, 14, 22 - 6.4) * Cylinder(5.5, 7, align=B)                      # ... counterbored Ø11 x 6.4
    body = body - Pos(54, 36, 16) * Rot(0, 90, 0) * Cylinder(4.0, 28, align=B)             # Ø8 cross hole along X
    return body, {"holes": sorted([6.6, 6.6, 6.6, 8.0]), "prismatic": True, "fillets": [3.0, 5.0], "counterbores": [11.0],
                  "chamfers": [1.5]}


def flanged_shaft():
    """A turned part: flange, shaft, bore, a fillet and a chamfer, four bolt holes in the flange and a cross hole."""
    from build123d import Align, Axis, Cylinder, Plane, Polyline, Pos, Rot, chamfer, fillet, make_face, revolve
    pts = [(5, 0), (25, 0), (25, 8), (12, 8), (12, 48), (5, 48)]                        # r, z: Ø50 flange, Ø24 shaft, Ø10 bore
    part = revolve(make_face(Plane.XZ * Polyline(*pts, close=True)), Axis.Z)
    circ = lambda r, z: [e for e in part.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - r) < 1e-6
                         and abs(e.center().Z - z) < 1e-6]
    part = fillet(circ(12, 8), 2.5)                                                       # shaft into the flange
    part = chamfer(circ(12, 48), 1.0)                                                     # shaft end
    B = (Align.CENTER, Align.CENTER, Align.MIN)
    for k in range(4):
        a = math.radians(45 + 90 * k)
        part = part - Pos(19 * math.cos(a), 19 * math.sin(a), -1) * Cylinder(2.75, 10, align=B)   # 4x Ø5.5 on PCD 38
    part = part - Pos(-13, 0, 34) * Rot(0, 90, 0) * Cylinder(3.0, 26, align=B)            # Ø6 cross hole
    return part, {"holes": sorted([5.5] * 4 + [6.0]), "bores": [10.0], "prismatic": False, "fillets": [2.5]}


def spur_gear_part():
    """A spur gear made the way Form Studio makes gears (form.parts, py_gearworks): m 2, 18 teeth, 8 thick, Ø8 bore."""
    from form.parts import spur_gear
    g = spur_gear(module=2.0, teeth=18, thickness=8.0, bore=8.0, backlash=0.0)
    return g.shape, {"holes": [8.0], "prismatic": True, "teeth": 18, "module": 2.0, "pressure_angle": 20.0}


def organic_blob():
    """A smooth blob (an ellipsoid: no plane, cylinder, cone, sphere or torus fits it) with a Ø6 hole through it."""
    from build123d import Align, Cylinder, Pos, Sphere, scale
    blob = scale(Sphere(10), (3.0, 2.0, 1.4))                                              # 60 x 40 x 28
    blob = blob - Pos(0, 0, -20) * Cylinder(3.0, 40, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return blob, {"holes": [6.0], "prismatic": False, "freeform": True}


def wallet_plate():
    """A card-holder plate modelled the way a person models a 2.5D part: a rounded plate with a chamfered bottom edge,
    two rails with rounded ends standing on it (mirrored about the centre), a pin, a shallow pocket and a clearance
    hole. Every feature is a sketch extruded between levels."""
    from build123d import Align, Cylinder, Pos, RectangleRounded, chamfer, extrude
    plate = extrude(RectangleRounded(60, 100, 5), 2.5)
    bottom = [e for e in plate.edges() if abs(e.center().Z) < 1e-6]
    plate = chamfer(bottom, 0.5)                                                      # a ruled band all round
    for x in (-26.0, 26.0):
        plate = plate + Pos(x, 0, 2.5) * extrude(RectangleRounded(2.0, 80, 0.9), 6.5)  # rails 2 wide, 6.5 tall
    A = (Align.CENTER, Align.CENTER, Align.MIN)
    plate = plate + Pos(-18, -40, 2.5) * Cylinder(3.0, 3.5, align=A)                    # Ø6 pin
    plate = plate - Pos(0, 10, 1.5) * extrude(RectangleRounded(30, 20, 2.0), 2.0)       # pocket 1 deep
    plate = plate - Pos(18, -40, -1) * Cylinder(1.7, 5, align=A)                        # Ø3.4: M3 clearance
    return plate, {"holes": [3.4], "prismatic": True, "pins": [6.0]}


def bolt_flange():
    """A bolted flange: a Ø80 disc with a raised hub, a Ø20 bore, six Ø9 bolt holes on a Ø60 pitch circle and a
    bevelled rim."""
    from build123d import Align, Cylinder, Pos, chamfer
    A = (Align.CENTER, Align.CENTER, Align.MIN)
    part = Cylinder(40, 10, align=A) + Pos(0, 0, 10) * Cylinder(20, 15, align=A)
    rim = [e for e in part.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - 40) < 1e-6
           and abs(e.center().Z - 10) < 1e-6]
    part = chamfer(rim, 1.0)
    part = part - Pos(0, 0, -1) * Cylinder(10, 27, align=A)
    for k in range(6):
        a = math.radians(60 * k)
        part = part - Pos(30 * math.cos(a), 30 * math.sin(a), -1) * Cylinder(4.5, 12, align=A)
    return part, {"holes": sorted([9.0] * 6 + [20.0]), "prismatic": True, "pattern": {"count": 6, "pcd": 60.0}}


def turned_shaft():
    """A stepped shaft as a lathe makes it: Ø16, Ø25 and Ø20 steps, chamfered ends and a fillet at the shoulder."""
    from build123d import Axis, Plane, Polyline, chamfer, fillet, make_face, revolve
    pts = [(0, 0), (8, 0), (8, 25), (12.5, 25), (12.5, 65), (10, 65), (10, 95), (0, 95)]     # r, z
    part = revolve(make_face(Plane.XZ * Polyline(*pts, close=True)), Axis.Z)
    circ = lambda r, z: [e for e in part.edges() if e.geom_type.name == "CIRCLE" and abs(e.radius - r) < 1e-6
                         and abs(e.center().Z - z) < 1e-6]
    part = fillet(circ(8, 25), 1.0)
    part = chamfer(circ(8, 0) + circ(10, 95), 1.0)
    return part, {"diameters": [16.0, 25.0, 20.0], "prismatic": False, "chamfers": [1.0], "fillets": [1.0]}


def enclosure_with_holes():
    """An open enclosure: 80 x 60 x 40 with 2 mm walls and rounded vertical corners, four Ø3.4 holes in the floor,
    two Ø6 holes through one side wall and a rectangular cut-out in the front."""
    from build123d import Align, Axis, Box, Cylinder, Pos, Rot, fillet
    A = (Align.CENTER, Align.CENTER, Align.MIN)
    outer = Box(80, 60, 40, align=A)
    outer = fillet(outer.edges().filter_by(Axis.Z), 4.0)
    inner = Pos(0, 0, 2) * Box(76, 56, 40, align=A)
    inner = fillet(inner.edges().filter_by(Axis.Z), 2.0)
    body = outer - inner
    for x, y in ((-30, -20), (30, -20), (-30, 20), (30, 20)):
        body = body - Pos(x, y, -1) * Cylinder(1.7, 4, align=A)
    for y in (-12.0, 12.0):
        body = body - Pos(37, y, 20) * Rot(0, 90, 0) * Cylinder(3.0, 6, align=A)
    body = body - Pos(0, -30, 25) * Box(30, 6, 12, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return body, {"holes": sorted([3.4] * 4 + [6.0] * 2), "prismatic": True}


def filleted_block():
    """A block with rounded vertical edges, a rounded top edge all round and a Ø8 hole through it."""
    from build123d import Align, Axis, Box, Cylinder, Pos, fillet
    A = (Align.CENTER, Align.CENTER, Align.MIN)
    body = Box(50, 30, 20, align=A)
    body = fillet(body.edges().filter_by(Axis.Z), 5.0)
    top = [e for e in body.edges() if abs(e.center().Z - 20) < 1e-6]
    body = fillet(top, 2.0)
    body = body - Pos(0, 0, -1) * Cylinder(4.0, 22, align=A)
    return body, {"holes": [8.0], "prismatic": True, "fillets": [2.0, 5.0]}


FIXTURES = {"box_with_holes": box_with_holes, "turned_part": turned_part, "filleted_bracket": filleted_bracket, "gear": gear,
            "stepped_bracket": stepped_bracket, "flanged_shaft": flanged_shaft, "spur_gear": spur_gear_part,
            "organic_blob": organic_blob, "wallet_plate": wallet_plate,
            "bolt_flange": bolt_flange, "turned_shaft": turned_shaft, "enclosure_with_holes": enclosure_with_holes,
            "filleted_block": filleted_block}


# A smooth shape meshed finely, the way a scan or a careful export is: its facets are within 0.01 mm of the surface
# it was made from (meshed with the surface-deflection check on for every surface; the default STL export of a
# B-spline surface can be 0.03 mm off), so a smooth reconstruction can be within 0.02 mm of them.
MESHED = {"organic_blob": 0.01}


def export(name: str, folder: Path, tolerance: float = 0.01, angular: float = 0.1) -> tuple[Path, object, dict]:
    from build123d import export_stl
    solid, facts = FIXTURES[name]()
    out = Path(folder) / f"{name}.stl"
    if name in MESHED:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.IMeshTools import IMeshTools_Parameters
        from form.kernel import _tessellate
        from form.recon import mesh
        prm = IMeshTools_Parameters()
        prm.Deflection, prm.Angle = MESHED[name], 0.35
        prm.ControlSurfaceDeflection = prm.EnableControlSurfaceDeflectionAllSurfaces = True
        BRepMesh_IncrementalMesh(solid.wrapped, prm)
        P, T = _tessellate(solid, MESHED[name])
        V, F, _ = mesh.weld(P[T])
        mesh.write_stl(out, V, F)
    else:
        export_stl(solid, str(out), tolerance=tolerance, angular_tolerance=angular)
    return out, solid, facts
