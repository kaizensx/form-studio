"""What a reconstructed topology feature calls in the kernel: one lightening pocket cut along the pull direction.

A design that topology optimisation wrote has one feature per pocket (form/topo/emit.py):

    @feature("Lightening pocket 1", role="structure")
    def topo_pocket_1(self, v, body):
        from form.topo import cad
        return cad.pocket(body, FRAME, OUTLINE, v["topo_inset"], v["topo_fillet"], v["topo_web"])

OUTLINE is the pocket's corners in the frame's own plane, in millimetres: the pocket is straight lines between
them. The three parameters are what a person changes afterwards:

    topo_inset    every pocket's outline moved inward by this much, so every rib is wider by twice this
    topo_fillet   the radius of the arc at each corner, tangent to both sides (a smaller one where two corners are
                  too close for it); 0 leaves the corners sharp, which a strength study names as singular
    topo_web      the thickness of a floor left under the pockets; 0 cuts through

Lines and arcs, not a spline: the kernel's volume of a solid cut along one long spline was several per cent off
the tessellated solid's (measured), so its mass would have been wrong, and the mesher of the strength study did
not get through such faces. Lines and arcs are exact in both.

An inset that splits a pocket in two cuts both parts; one that leaves no room for it, or pinches its outline into
something that is not a valid cut, cuts nothing (the feature returns the body as it was), so a wide range of the
parameters builds and the result is always a valid solid.
"""
from __future__ import annotations

import math

ARC_SHARE = 0.5              # an arc takes at most this share of the shorter side at its corner (two then just meet)
ARC_MIN = 0.3                # mm: a corner with less room than this keeps its corner (no sliver of an arc)


def shoelace(pts: list) -> float:
    """The signed area of a polygon (positive when its corners run counter-clockwise)."""
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def rounded_corners(outline, radius: float) -> list:
    """Per corner: (start of its arc, a point on the arc, end of its arc), or (corner, None, corner) where the
    sides are in line or too short for an arc. Pure geometry: the arc is tangent to both sides."""
    pts = [(float(x), float(y)) for x, y in outline]
    n = len(pts)
    out = []
    for i in range(n):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]
        l1, l2 = math.hypot(ax - bx, ay - by), math.hypot(cx - bx, cy - by)
        sharp = ((bx, by), None, (bx, by))
        if radius <= 0 or l1 < 1e-9 or l2 < 1e-9:
            out.append(sharp)
            continue
        u1, u2 = ((ax - bx) / l1, (ay - by) / l1), ((cx - bx) / l2, (cy - by) / l2)
        half = 0.5 * math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))       # half the angle between the sides
        if half < 1e-3 or half > math.pi / 2 - 1e-3:
            out.append(sharp)
            continue
        t = min(radius / math.tan(half), ARC_SHARE * min(l1, l2))
        if t < ARC_MIN:
            out.append(sharp)
            continue
        r = t * math.tan(half)
        sx, sy = u1[0] + u2[0], u1[1] + u2[1]
        s = math.hypot(sx, sy)
        k = r / math.sin(half) - r                       # from the corner to the arc, along the bisector
        out.append(((bx + u1[0] * t, by + u1[1] * t), (bx + sx / s * k, by + sy / s * k), (bx + u2[0] * t, by + u2[1] * t)))
    return out


def outline_area(outline, radius: float) -> float:
    """The area of the outline with its corners rounded (no kernel): what the pocket removes per millimetre of depth
    at inset 0. At each arc the corner's triangle goes and the arc's segment comes back (or the reverse, at a corner
    that points into the pocket)."""
    pts = [(float(x), float(y)) for x, y in outline]
    turn = 1.0 if shoelace(pts) > 0 else -1.0
    area = abs(shoelace(pts))
    for (p1, mid, p2), b in zip(rounded_corners(pts, radius), pts):
        if mid is None:
            continue
        tri = 0.5 * ((p1[0] - b[0]) * (p2[1] - b[1]) - (p2[0] - b[0]) * (p1[1] - b[1]))
        chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        sag = math.hypot(mid[0] - (p1[0] + p2[0]) / 2, mid[1] - (p1[1] + p2[1]) / 2)
        r = (chord * chord / 4 + sag * sag) / (2 * sag)
        ang = 2 * math.asin(min(1.0, chord / (2 * r)))
        cap = abs(tri) - 0.5 * r * r * (ang - math.sin(ang))       # between the corner and its arc
        area += -cap if (-tri * turn) > 0 else cap                 # a corner that points out of the pocket loses it
    return area


def _base_face(outline, fillet: float):
    from build123d import Face, Line, ThreePointArc, Wire
    corners = rounded_corners(outline, fillet)
    edges = []
    for i, (p1, mid, p2) in enumerate(corners):
        if mid is not None:
            edges.append(ThreePointArc(p1, mid, p2))
        q = corners[(i + 1) % len(corners)][0]
        if math.hypot(q[0] - p2[0], q[1] - p2[1]) > 1e-6:
            edges.append(Line(p2, q))
    return Face(Wire(edges))


def _inset(face, d: float) -> list:
    """The face moved inward by d: no face, one, or several when it splits."""
    from build123d import Face, Shape
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    mk = BRepOffsetAPI_MakeOffset(face.wrapped, GeomAbs_Arc)
    mk.Perform(-float(d))
    if not mk.IsDone() or mk.Shape().IsNull():
        return []
    out = []
    for w in Shape.cast(mk.Shape()).wires():
        try:
            f = Face(w)
        except Exception:                                # noqa: BLE001 - a wire that closes nothing
            continue
        if 1e-6 < f.area < face.area:
            out.append(f)
    return out


def outline_faces(outline, inset: float, fillet: float) -> list:
    """The pocket's faces in the XY plane after the corner arcs and the inset: none when nothing is left."""
    r, d = max(0.0, float(fillet)), max(0.0, float(inset))
    try:
        face = _base_face(outline, r)
        if face.area <= 1e-6:
            return []
        return _inset(face, d) if d > 0 else [face]
    except Exception:                                    # noqa: BLE001 - the outline left nothing that is a face
        return []


def pocket(body, frame: dict, outline, inset: float = 0.0, fillet: float = 0.0, web: float = 0.0):
    """body with the pocket cut. frame: {"origin", "x", "z" (the pull direction), "lo", "hi"}: the outline's plane,
    and the part's extent along the pull direction measured from the origin."""
    from build123d import Plane, extrude
    lo, hi = float(frame["lo"]), float(frame["hi"])
    web = max(0.0, float(web))
    start = lo + web if web > 0 else lo - 1.0
    depth = hi + 1.0 - start
    if depth <= 0:
        return body
    z = tuple(float(c) for c in frame["z"])
    o = tuple(float(c) + start * zc for c, zc in zip(frame["origin"], z))
    plane = Plane(origin=o, x_dir=tuple(float(c) for c in frame["x"]), z_dir=z)
    for face in outline_faces(outline, inset, fillet):
        cut = body - extrude(plane * face, amount=depth, dir=z)
        if cut.is_valid and cut.volume < body.volume:    # an inset that pinches the outline can give a bad tool: not cut
            body = cut
    return body
