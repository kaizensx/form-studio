"""Small build123d helpers that reconstructed recipes call. Kernel worker only (imports build123d).

A recipe written by the reconstruction (features.py, tree.py, gears.py) is plain build123d plus these few calls, so
it stays readable and every number in it is a Param or a coordinate read off the mesh:

    edges_near(shape, points)              the edge nearest each point (where a fillet or chamfer goes)
    vertices_near(shape, points)           the corner nearest each point (a profile corner to round)
    hole(origin, direction, steps)         a drilled hole: plain, counterbored, countersunk, blind or through
    spur_gear_profile(...)                 an involute spur gear outline (tip and root as the mesh has them)
    profile(plane, nodes, edges)           a sketch: corners (with corner radii) joined by lines and arcs, as a face
    disc(plane, x, y, d)                   a circle of diameter d as a face
    turn(plane, x, y, nodes, edges)        a half-section revolved about the axis through (x, y): a turned body
    rect(plane, x, y, w, h)              a w x h rectangle centred at (x, y) as a face
    outline(plane, start, segments)        lines and three-point arcs from `start`, closed, as a face
    polar(x, y, pcd, n, phase)             the n centres of a polar pattern on a pitch circle
    grid(x0, y0, nx, ny, px, py)           the centres of a linear pattern
    slab(face, z0, z1, top=None)           the solid between two levels: an extrusion, or a ruled loft to `top`
"""
from __future__ import annotations

import math


def _vec(p):
    from build123d import Vector
    return Vector(*p) if not hasattr(p, "X") else p


def edges_near(shape, points, within: float | None = None):
    """For each point, the edge of `shape` nearest to it (each edge once). With `within`, an edge farther than that
    from its point is an error: the shape has changed too much for the feature to find its edge."""
    from build123d import ShapeList, Vertex
    edges = shape.edges()
    out = []
    for p in points:
        v = Vertex(*p)
        best = min(edges, key=lambda e: e.distance_to(v))
        if within is not None and best.distance_to(v) > within:
            raise ValueError(f"no edge within {within:g} mm of {tuple(round(x, 3) for x in p)}")
        if best not in out:
            out.append(best)
    return ShapeList(out)


def vertices_near(shape, points, within: float | None = None):
    """For each point, the vertex of `shape` nearest to it (each vertex once): corners of a profile to round."""
    from build123d import ShapeList, Vector
    verts = shape.vertices()
    out = []
    for p in points:
        q = Vector(*p)
        best = min(verts, key=lambda v: (Vector(v) - q).length)
        if within is not None and (Vector(best) - q).length > within:
            raise ValueError(f"no corner within {within:g} mm of {tuple(round(x, 3) for x in p)}")
        if best not in out:
            out.append(best)
    return ShapeList(out)


def hole(origin, direction, steps, through: bool = False, overshoot: float = 1.0, tip_angle: float | None = None,
         beyond: float | None = None):
    """A hole tool: a solid to subtract. `origin` is where the hole enters the part and `direction` points into the
    material. `steps` go from the entry inwards: (diameter, length) for a cylinder, ("cone", d_start, d_end, length)
    for a countersink or a taper. The tool starts `overshoot` before the entry; a through hole also goes `beyond`
    (default: overshoot) past its far end, so it stays through when the part gets thicker. A blind hole ends flat, or
    in a drill point of `tip_angle` degrees."""
    beyond = overshoot if beyond is None else beyond
    from build123d import Axis, Plane, Polyline, Vector, make_face, revolve
    pts = [(0.0, -overshoot)]
    s, r1 = 0.0, 0.0
    for k, st in enumerate(steps):
        if st[0] == "cone":
            _, d0, d1, L = st
            r0, r1 = d0 / 2, d1 / 2
        else:
            d, L = st
            r0 = r1 = d / 2
        pts.append((r0, -overshoot if k == 0 else s))
        s += L + (beyond if through and k == len(steps) - 1 else 0.0)
        pts.append((r1, s))
    pts.append((0.0, s + (r1 / math.tan(math.radians(tip_angle) / 2) if tip_angle else 0.0)))
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 1e-12 or abs(p[1] - clean[-1][1]) > 1e-12:
            clean.append(p)
    tool = revolve(make_face(Plane.XZ * Polyline(*[(r, -z) for r, z in clean], close=True)), Axis.Z)
    org = origin if hasattr(origin, "X") else Vector(*origin)
    return Plane(origin=org, z_dir=-Vector(*direction).normalized()) * tool


def involute_points(rb: float, r0: float, r1: float, n: int = 24):
    """(radius, polar angle) along an involute of the base circle rb from radius r0 to r1."""
    out = []
    for i in range(n):
        r = r0 + (r1 - r0) * i / (n - 1)
        a = math.acos(min(1.0, rb / max(r, rb)))
        out.append((r, math.tan(a) - a))
    return out


def spur_gear_profile(teeth: int, module: float, pressure_angle: float, tip_d: float, root_d: float,
                      thickness_angle: float, tip: str = "chord", root: str = "chord", phase: float = 0.0):
    """Outline of an involute spur gear as a build123d Wire on the XY plane, centred on the origin.

    thickness_angle: half the angular tooth thickness at the base circle (radians); with a standard tooth it is
    pi / (2 z) + inv(pressure angle). tip: "chord" (straight across) or "arc" (on the tip circle). root: "chord"
    (straight between the flanks where they start) or "arc" (radial down to the root circle, then along it)."""
    from build123d import Line, Spline, ThreePointArc, Wire
    z, m = int(teeth), module
    rb = z * m / 2 * math.cos(math.radians(pressure_angle))
    ra, rf = tip_d / 2, root_d / 2
    r_start = max(rb, rf)
    fl = involute_points(rb, r_start, ra)
    half = thickness_angle
    edges = []
    teeth_pts = []
    for k in range(z):
        c = phase + 2 * math.pi * k / z
        left = [(r * math.cos(c - half + t), r * math.sin(c - half + t), 0) for r, t in fl]
        right = [(r * math.cos(c + half - t), r * math.sin(c + half - t), 0) for r, t in reversed(fl)]
        teeth_pts.append((c, left, right))
    for k in range(z):
        c, left, right = teeth_pts[k]
        c2, nl, _ = teeth_pts[(k + 1) % z]
        edges.append(Spline(*left))
        if tip == "arc":
            edges.append(ThreePointArc(left[-1], (ra * math.cos(c), ra * math.sin(c), 0), right[0]))
        else:
            edges.append(Line(left[-1], right[0]))
        edges.append(Spline(*right))
        if root == "arc" and rf < r_start - 1e-9:
            a0 = math.atan2(right[-1][1], right[-1][0])
            a1 = math.atan2(nl[0][1], nl[0][0])
            if a1 < a0:
                a1 += 2 * math.pi
            p0 = (rf * math.cos(a0), rf * math.sin(a0), 0)
            p1 = (rf * math.cos(a1), rf * math.sin(a1), 0)
            am = 0.5 * (a0 + a1)
            edges += [Line(right[-1], p0), ThreePointArc(p0, (rf * math.cos(am), rf * math.sin(am), 0), p1), Line(p1, nl[0])]
        else:
            edges.append(Line(right[-1], nl[0]))
    return Wire(edges)


def profile(plane, nodes, edges=None):
    """A face on `plane` from a sketch: nodes [(x, y, corner_radius)] in the plane's coordinates, joined in order by
    edges [None for a line | (R, ccw, large) for an arc of radius R], edges[i] from nodes[i] to nodes[i + 1]. A corner
    radius rounds the corner between two lines. Raises ValueError when a radius does not fit (a Param too large)."""
    from build123d import Face, Line, ThreePointArc, Wire
    from .sketch import path
    edges = edges or [None] * len(nodes)
    q = lambda p: plane.from_local_coords((float(p[0]), float(p[1])))
    out = []
    for pc in path(nodes, edges):
        out.append(Line(q(pc[1]), q(pc[2])) if pc[0] == "line" else ThreePointArc(q(pc[1]), q(pc[2]), q(pc[3])))
    face = Face(Wire(out))
    if face.area < 1e-12:
        raise ValueError("the sketch encloses no area")
    return face


def disc(plane, x, y, d):
    """A circle of diameter d centred at (x, y) on `plane`, as a face."""
    from build123d import Edge, Face, Plane, Wire
    c = plane.from_local_coords((float(x), float(y)))
    return Face(Wire([Edge.make_circle(float(d) / 2, Plane(origin=c, x_dir=plane.x_dir, z_dir=plane.z_dir))]))


def slab(face, z0, z1, top=None):
    """The solid a sketch makes between levels z0 and z1 (along the sketch plane's normal; `face` lies at z0): an
    extrusion, or with `top` (the same sketch at z1, other sizes) a ruled loft from one to the other (a chamfer or a
    draft along the walls)."""
    from build123d import extrude, loft
    if z1 <= z0:
        raise ValueError(f"a slab from {z0:g} to {z1:g} has no height")
    if top is None:
        return extrude(face, amount=float(z1 - z0))
    return loft([face, top], ruled=True)


def rect(plane, x, y, w, h):
    """A w x h rectangle centred at (x, y) on `plane`, as a face."""
    from build123d import Face, Polyline, Wire
    if w <= 0 or h <= 0:
        raise ValueError(f"a {w:g} x {h:g} rectangle has no area")
    q = lambda a, b: plane.from_local_coords((float(a), float(b)))
    pts = [q(x - w / 2, y - h / 2), q(x + w / 2, y - h / 2), q(x + w / 2, y + h / 2), q(x - w / 2, y + h / 2)]
    return Face(Wire(Polyline(*pts, close=True).edges()))


def outline(plane, start, segments):
    """A face from a closed outline on `plane`: from `start` (x, y), each segment ("line", (x1, y1)) or
    ("arc", (xm, ym), (x1, y1)) (a three-point arc through the middle point); closed back to `start` by a line when
    the last segment does not end there."""
    from build123d import Face, Line, ThreePointArc, Wire
    q = lambda p: plane.from_local_coords((float(p[0]), float(p[1])))
    edges, cur = [], tuple(start)                       # (from, middle or None, to)
    for sg in segments:
        if sg[0] == "line":
            edges.append((cur, None, tuple(sg[1])))
            cur = tuple(sg[1])
        else:
            edges.append((cur, tuple(sg[1]), tuple(sg[2])))
            cur = tuple(sg[2])
    edges.append((cur, None, tuple(start)))
    edges = [e for e in edges if e[1] is not None or abs(e[0][0] - e[2][0]) + abs(e[0][1] - e[2][1]) > 1e-9]
    ring = [p for a, m, _ in edges for p in ((a,) if m is None else (a, m))]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))
    if area < 0:                                        # clockwise: drawn the other way, so the face faces +z
        edges = [(b, m, a) for a, m, b in reversed(edges)]
    out = [Line(q(a), q(b)) if m is None else ThreePointArc(q(a), q(m), q(b)) for a, m, b in edges]
    face = Face(Wire(out))
    if face.area < 1e-12:
        raise ValueError("the outline encloses no area")
    return face


def turn(plane, x, y, nodes, edges=None):
    """A turned body: the half-section sketch nodes [(radius, level, corner_radius)] (edges as in `profile`) revolved
    about the axis through (x, y) on `plane`, along the plane's normal. Radius is measured from the axis, level along
    the normal from the plane."""
    from build123d import Axis, Plane, revolve
    o = plane.from_local_coords((float(x), float(y)))
    half = Plane(origin=o, x_dir=plane.x_dir, z_dir=plane.x_dir.cross(plane.z_dir))
    return revolve(profile(half, nodes, edges), Axis(o, plane.z_dir))


def polar(x, y, pcd, n, phase_deg=0.0):
    """The n centres of a polar pattern: on a pitch circle of diameter pcd about (x, y), the first at phase_deg."""
    n = int(round(n))
    if n < 1 or pcd <= 0:
        raise ValueError(f"a polar pattern of {n} on a Ø{pcd:g} pitch circle")
    return [(x + pcd / 2 * math.cos(math.radians(phase_deg) + 2 * math.pi * k / n),
             y + pcd / 2 * math.sin(math.radians(phase_deg) + 2 * math.pi * k / n)) for k in range(n)]


def grid(x0, y0, nx, ny, px, py):
    """The centres of a linear pattern: nx by ny, pitch px along the first axis and py along the second, from
    (x0, y0)."""
    nx, ny = int(round(nx)), int(round(ny))
    if nx < 1 or ny < 1:
        raise ValueError("a pattern needs at least one item")
    return [(x0 + i * px, y0 + j * py) for j in range(ny) for i in range(nx)]
