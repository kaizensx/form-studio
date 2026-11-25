"""Surfacing: profiles, lofts, sweeps, revolves, shells, fillets and thickened faces.

All functions take mm and degrees and return build123d objects (algebra API, no builders):

    from form.craft import surfaces as sf
    sec = [sf.superellipse_face(40, 30, 2.6, z=0), sf.superellipse_face(36, 26, 2.4, z=30), sf.superellipse_face(20, 14, 2.2, z=55)]
    body = sf.loft_sections(sec)                       # smooth B-spline loft (ruled loft as the fallback)
    cup = sf.shell(body, 2.0, openings=sf.faces_at(body, "top"))

Profiles: superellipse(a, b, n) points (n = 2 is an ellipse, n -> large is a rounded rectangle), spline_profile(points)
and polygon_profile(points) as Faces on any Plane. Section helpers place a profile at a height or along a path.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from build123d import (Axis, Edge, Face, Kind, Plane, Polyline, Pos, Solid, Spline, Vector, Wire, loft,
                       make_face, offset, revolve, sweep)
from build123d import thicken as _thicken

from ._common import attempt, fail, need, note, num, ok, one, pts2


# ---- profiles ------------------------------------------------------------------------------------------------

def superellipse(a: float, b: float, n: float = 2.5, count: int = 72, rotate: float = 0.0,
                 squash_front: float = 0.0, seam: float = 0.0) -> list[tuple[float, float]]:
    """Points of |x/a|^n + |y/b|^n = 1 (a, b: half-widths in mm). n = 2 ellipse, 2.5-4 the soft-square of product
    design, >= 6 a rounded rectangle. squash_front (0-0.5) narrows the +x half to make an egg (a helmet's front).
    rotate turns the points (degrees). seam (degrees) is where the loop starts: a loft through such sections draws
    its seam line there, so put it where nobody looks (180 = the back, -X). Returned closed loop without repeating
    the first point."""
    a, b = num(a, "a", positive=True), num(b, "b", positive=True)
    n = num(n, "n", lo=0.5, hi=40)
    count = num(count, "count", lo=8, hi=720, integer=True)
    sq = num(squash_front, "squash_front", lo=0.0, hi=0.6)
    c, s = math.cos(math.radians(rotate)), math.sin(math.radians(rotate))
    out = []
    for i in range(count):
        t = 2 * math.pi * i / count + math.radians(seam)
        ct, st = math.cos(t), math.sin(t)
        x = a * math.copysign(abs(ct) ** (2 / n), ct)
        y = b * math.copysign(abs(st) ** (2 / n), st)
        if sq and x > 0:
            y *= 1 - sq * (x / a) ** 2
        out.append((x * c - y * s, x * s + y * c))
    return out


def _on(plane: Plane, pts2d, z: float = 0.0):
    return [plane.from_local_coords((x, y, z)) for x, y in pts2d]


def spline_profile(points, plane: Plane = Plane.XY, closed: bool = True, z: float = 0.0) -> Face | Wire:
    """A smooth (B-spline through the points) profile on plane. Closed: a Face; open: a Wire.
    A closed profile's normal is always the plane's normal, whichever way the points run, so extrude(face, d)
    always goes along the plane's z direction (use both=True to go both ways).
    Fallback: a polyline through the same points (noted)."""
    p = pts2(points, "points", 3 if closed else 2)
    P = _on(plane, p, z)

    def smooth():
        e = Spline(*P, periodic=closed) if closed else Spline(*P)
        return make_face(Wire([e])).faces()[0] if closed else Wire([e])

    def poly():
        w = Wire.make_polygon(P, close=closed) if closed else Polyline(*P)
        return make_face(w).faces()[0] if closed else (w if isinstance(w, Wire) else Wire(w.edges()))

    check = (lambda f: f is not None and (not closed or f.area > 1e-9))
    r = attempt("spline_profile", [("B-spline", smooth), ("polyline", poly)],
                "Check that the points do not cross each other and are not all on a line.", ["points"], check)
    return _facing(r, plane) if closed else r


def _facing(face: Face, plane: Plane) -> Face:
    """The face turned so its normal is the plane's z direction (points given clockwise would otherwise extrude
    the wrong way and miss the body they should cut)."""
    try:
        if face.normal_at().dot(plane.z_dir) < 0:
            return Face(face.wrapped.Reversed())
    except Exception:                      # a face without a usable normal is returned as built
        pass
    return face


def polygon_profile(points, plane: Plane = Plane.XY, z: float = 0.0) -> Face:
    p = pts2(points, "points", 3)
    w = Wire.make_polygon(_on(plane, p, z), close=True)
    f = make_face(w).faces()[0]
    need(f.area > 1e-9, "polygon_profile: the points enclose no area", "Order the points around the outline.", ["points"])
    return _facing(f, plane)


def superellipse_face(a: float, b: float, n: float = 2.5, z: float = 0.0, plane: Plane = Plane.XY,
                      center: tuple[float, float] = (0.0, 0.0), count: int = 72, rotate: float = 0.0,
                      squash_front: float = 0.0, seam: float = 0.0) -> Face:
    """A superellipse section as a Face on plane, at height z along the plane normal, centred at center."""
    cx, cy = float(center[0]), float(center[1])
    p = [(x + cx, y + cy) for x, y in superellipse(a, b, n, count, rotate, squash_front, seam)]
    return spline_profile(p, plane, True, z)


def section_at(face: Face, z: float) -> Face:
    return Pos(0, 0, z) * face


def plane_on_path(path: Edge | Wire, t: float = 0.0) -> Plane:
    """A Plane at parameter t (0-1) of the path, its normal along the path's tangent."""
    return Plane(origin=path.position_at(t), z_dir=path.tangent_at(t))


# ---- solids from sections -------------------------------------------------------------------------------------

def loft_sections(sections: Sequence, ruled: bool = False):
    """A solid through the sections in order (Faces, closed Wires, or a Vertex at either end for a pointed tip).
    Fallback: a ruled loft (straight between sections, noted). Sections must not cross each other."""
    secs = list(sections)
    need(len(secs) >= 2, f"loft_sections needs at least 2 sections (got {len(secs)})", "Add sections.", ["sections"])
    secs = [make_face(s).faces()[0] if isinstance(s, Wire) else s for s in secs]
    tries = [] if ruled else [("smooth loft", lambda: one(loft(secs, ruled=False)))]
    tries.append(("ruled loft", lambda: one(loft(secs, ruled=True))))
    return attempt("loft_sections", tries, "Keep sections in order along the loft with similar point counts and "
                   "starting points; a section that twists or crosses the next one cannot be lofted.", ["sections"])


def sweep_spline(profile: Face, path_points, is_frenet: bool = False, through: bool = True):
    """Sweep profile (a Face drawn on Plane.XY, centred on its origin) along a B-spline through path_points (3D).
    The profile is placed at the start of the path, normal to it. Fallbacks: Frenet frame, then a right-corner
    transition (each noted)."""
    try:
        P = [Vector(*map(float, p)) for p in path_points]
    except (TypeError, ValueError):
        raise fail("path_points must be (x, y, z) triples", "Pass the path as [(x, y, z), ...] in mm.", ["path_points"])
    need(len(P) >= 2, "sweep_spline needs at least 2 path points", "Add points to the path.", ["path_points"])
    path = Spline(*P) if len(P) > 2 and through else Edge.make_line(P[0], P[-1]) if len(P) == 2 else Polyline(*P)
    path = path if isinstance(path, Wire) else Wire([path]) if isinstance(path, Edge) else Wire(path.edges())
    pl = plane_on_path(path, 0)
    prof = pl * profile
    from build123d import Transition
    tries = [("sweep", lambda: one(sweep(prof, path, is_frenet=is_frenet))),
             ("Frenet sweep", lambda: one(sweep(prof, path, is_frenet=not is_frenet))),
             ("right-corner sweep", lambda: one(sweep(prof, path, transition=Transition.RIGHT)))]
    return attempt("sweep_spline", tries, "Make the path bend less sharply than the profile is wide, or make the "
                   "profile smaller.", ["path_points", "profile"])


def revolve_profile(points, angle: float = 360.0, spline: bool = False, axis: Axis = Axis.Z):
    """Revolve a profile given as (r, z) points (r >= 0) about the Z axis. Open profiles are closed along the axis.
    spline=True draws a B-spline through the points (a vase, a knob) instead of straight segments."""
    p = pts2(points, "points", 2)
    need(all(r >= -1e-9 for r, _ in p), "revolve_profile: every point needs r >= 0", "Keep the profile on one side "
         "of the axis.", ["points"])
    angle = num(angle, "angle", lo=0.1, hi=360)
    ring = list(p)
    if spline:
        e = Spline(*[Vector(r, 0, z) for r, z in p])
        segs = [e]
        a, b = p[-1], p[0]
        if a[0] > 1e-9:
            segs.append(Edge.make_line(Vector(a[0], 0, a[1]), Vector(0, 0, a[1])))
        if abs(a[1] - b[1]) > 1e-9:
            segs.append(Edge.make_line(Vector(0, 0, a[1]), Vector(0, 0, b[1])))
        if b[0] > 1e-9:
            segs.append(Edge.make_line(Vector(0, 0, b[1]), Vector(b[0], 0, b[1])))
        face = make_face(Wire(segs)).faces()[0]
    else:
        if ring[0][0] > 1e-9:
            ring.insert(0, (0.0, ring[0][1]))
        if ring[-1][0] > 1e-9:
            ring.append((0.0, ring[-1][1]))
        face = make_face(Wire.make_polygon([Vector(r, 0, z) for r, z in ring], close=True)).faces()[0]
    return attempt("revolve_profile", [("revolve", lambda: one(revolve(face, axis, angle)))],
                   "The profile must not cross itself or the axis.", ["points"])


# ---- robust booleans ---------------------------------------------------------------------------------------------

def _occt_bool(a, b, op: str, fuzzy: float):
    from build123d import Shape
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    try:
        from OCP.TopTools import TopTools_ListOfShape
    except ImportError:                                   # newer OCP names the template instance
        from OCP.collections import List_TopoDS_Shape as TopTools_ListOfShape
    mk = {"cut": BRepAlgoAPI_Cut, "fuse": BRepAlgoAPI_Fuse, "common": BRepAlgoAPI_Common}[op]()
    la, lb = TopTools_ListOfShape(), TopTools_ListOfShape()
    la.Append(a.wrapped)
    lb.Append(b.wrapped)
    mk.SetArguments(la)
    mk.SetTools(lb)
    if fuzzy:
        mk.SetFuzzyValue(fuzzy)
    mk.SetRunParallel(True)
    mk.Build()
    if not mk.IsDone():
        raise ValueError("boolean not done")
    r = Shape.cast(mk.Shape())
    from build123d import Part
    try:
        r.clean()
    except Exception:
        pass
    return r if r.solids() else Part()


def cut(body, tool, min_solids: int = 1):
    """body - tool through the boolean engine (form.craft.boolean): the plain cut, verified (valid, at least
    min_solids solids, a volume the cut can give, and a mesh oracle when it removed almost nothing, so a cut that
    silently removes nothing is caught); when it fails, the cause is measured and classified (grazing face, coincident
    faces, invalid operand, seam...) and only that cause's rewrites are tried, within a time bound. The rewrite taken
    is noted; a failure says what was measured."""
    from .boolean import run
    return run(body, tool, "cut", min_solids=min_solids, what="cut", names=("body", "tool"), params=["tool"])


def fuse(body, other, max_solids: int | None = None, min_solids: int = 1):
    """body + other through the boolean engine, like cut. max_solids: the count the result may have at most (default
    the body's own count: a pad that does not fuse leaves an extra solid). min_solids: at least (a separate part, such
    as a visor that must stay clear of the shell, is a second solid: fuse(body, visor, 2, 2) refuses a visor that
    touches or overlaps the body, and says which with the measured contact or overlap)."""
    from .boolean import run
    return run(body, other, "fuse", min_solids=min_solids, max_solids=max_solids, what="fuse",
               names=("body", "other"), params=["other"])


# ---- shells, fillets, thickening -------------------------------------------------------------------------------

def faces_at(shape, where: str = "top", tol: float = 0.05) -> list:
    """Planar faces at the extreme of the shape: "top", "bottom", "+x", "-x", "+y", "-y"."""
    bb = shape.bounding_box()
    key = {"top": ("Z", 1), "bottom": ("Z", -1), "+z": ("Z", 1), "-z": ("Z", -1), "+x": ("X", 1), "-x": ("X", -1),
           "+y": ("Y", 1), "-y": ("Y", -1)}.get(where)
    need(key is not None, f"faces_at: unknown side {where!r}", "Use top, bottom, +x, -x, +y or -y.", ["where"])
    ax, sgn = key
    lim = getattr(bb.max if sgn > 0 else bb.min, ax)
    out = []
    for f in shape.faces():
        fb = f.bounding_box()
        if abs(getattr(fb.max, ax) - lim) < tol and abs(getattr(fb.min, ax) - lim) < tol:
            out.append(f)
    return out


def shell(solid, thickness: float, openings: Iterable | None = None, inward: bool = True):
    """A hollow body with walls `thickness` thick, open at the given faces (none: a closed hollow). The outside
    stays where it is (inward=True). Fallback: an intersection-style offset (sharper inner corners, noted)."""
    t = num(thickness, "thickness", positive=True)
    op = list(openings or [])
    amt = -t if inward else t
    tries = [("arc offset", lambda: one(offset(solid, amount=amt, openings=op or None, kind=Kind.ARC))),
             ("intersection offset", lambda: one(offset(solid, amount=amt, openings=op or None, kind=Kind.INTERSECTION)))]
    r = attempt("shell", tries, f"Make the wall thinner than the smallest inside radius of the body, or round the "
                f"body's tight corners first (a {t:g} mm wall cannot follow a smaller radius). For a lofted dome with a "
                f"crown point use craft.section_shell (inset sections) instead.", ["thickness"])
    if not op:
        # with no openings OCCT returns the offset body itself (the inner solid when inward), not a hollow:
        # the closed hollow is the difference of the two bodies
        from . import boolean
        if r.volume < solid.volume - 1e-6:          # r is the inside: take it out of the body
            r = one(boolean.run(solid, r, "cut", what="hollow the body", max_solids=1))
        elif r.volume > solid.volume + 1e-6:        # outward: r is the grown body, the original is the cavity
            r = one(boolean.run(r, solid, "cut", what="hollow the body", max_solids=1))
        need(abs(r.volume) < abs(solid.volume) - 1e-6 or not inward, "shell: the offset did not hollow the body",
             "Give openings, or a thinner wall.", ["thickness"])
    return r


SINGULAR = 0.03          # a blend this close (relative) to the radius of an arc edge it runs along degenerates


def singular_edges(edges, size: float) -> list:
    """Edges a fillet of radius `size` (or a chamfer of that length) must not be asked to take at once: arcs whose own
    radius is within SINGULAR of it. The blend then shrinks the arc's face to nothing, and OCCT's BRepFilletAPI does
    not fail cleanly: it ends the process (r05 of a sofa-arm holder: a 1.2 mm fillet on the top edge of a 1.2 mm
    radius bead). Measured on the edge, nothing assumed."""
    out = []
    for e in edges:
        try:
            if e.geom_type.name == "CIRCLE" and abs(e.radius - size) <= SINGULAR * e.radius:
                out.append(e)
        except Exception:
            continue
    return out


def guarded_blend(shape, size: float, edges, chamfer: bool = False):
    """shape.fillet(size, edges) / shape.chamfer(size, None, edges), refusing (ValueError, which the safe_ helpers
    treat as "did not fit") a size that would crash the kernel on one of the edges (singular_edges)."""
    bad = singular_edges(edges, size)
    if bad:
        c = bad[0].center()
        note(f"{'chamfer' if chamfer else 'fillet'} {size:.2g} mm not tried on {len(bad)} arc edge(s) of that same "
             f"radius (at {c.X:.1f}, {c.Y:.1f}, {c.Z:.1f}): it degenerates and crashes the kernel")
        raise ValueError("blend size equals an arc edge's radius")
    return shape.chamfer(size, None, edges) if chamfer else shape.fillet(size, edges)


def safe_fillet(shape, edges, radius: float, min_fraction: float = 0.25):
    """Fillet edges with radius; when it does not fit, try 75 %, 50 % and min_fraction of it, then leave the edges
    sharp. Every reduction is noted (form.craft.notes()); the chosen radius is what the solid has."""
    r = num(radius, "radius", positive=True)
    E = list(edges)
    if not E:
        return shape
    fr = [1.0, 0.75, 0.5, min_fraction]
    for i, f in enumerate(fr):
        try:
            out = guarded_blend(shape, r * f, E)
            if ok(out):
                if i:
                    note(f"safe_fillet: {r:g} mm did not fit; used {r * f:.2g} mm")
                return out
        except Exception:
            continue
    if len(E) > 1:
        # one bad edge (a seam, a tangent corner) fails the whole set: fillet edge by edge, each as large as it takes
        out, done, sizes = shape, 0, set()
        for c in [e.center() for e in E]:
            cur = min(out.edges(), key=lambda e: (e.center() - c).length)
            if (cur.center() - c).length > 1e-3:
                continue
            for f in fr:
                try:
                    o = guarded_blend(out, r * f, [cur])
                    if ok(o):
                        out, done = o, done + 1
                        sizes.add(round(r * f, 2))
                        break
                except Exception:
                    continue
        if done:
            note(f"safe_fillet: {r:g} mm on all {len(E)} edges at once did not fit; filleted {done} edge by edge "
                 f"({', '.join(f'{x:g}' for x in sorted(sizes))} mm)" + (f", {len(E) - done} left sharp" if done < len(E) else ""))
            return out
    note(f"safe_fillet: {len(E)} edge(s) left sharp; even {r * min_fraction:.2g} mm did not fit")
    return shape


def variable_fillet(shape, edges, r_start: float, r_end: float):
    """A fillet whose radius runs from r_start to r_end along each edge (a swept blend, larger where the hand rests).
    Fallback: a constant fillet at the smaller radius (noted)."""
    a, b = num(r_start, "r_start", positive=True), num(r_end, "r_end", positive=True)
    E = list(edges)
    need(bool(E), "variable_fillet: no edges given", "Select edges with shape.edges().filter_by(...).", ["edges"])

    def var():
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        mk = BRepFilletAPI_MakeFillet(shape.wrapped)
        for e in E:
            mk.Add(a, b, e.wrapped)
        mk.Build()
        from build123d import Shape
        return one(Shape.cast(mk.Shape()))

    def const():
        return shape.fillet(min(a, b), E)

    return attempt("variable_fillet", [("variable radius", var), ("constant radius", const)],
                   "Use smaller radii; a fillet cannot be wider than the faces it joins.", ["r_start", "r_end"])


def thicken(face, thickness: float, both: bool = False):
    """A solid from a surface: face (or Shell) grown by thickness along its normal (both=True: half each side)."""
    t = num(thickness, "thickness", positive=True)
    return attempt("thicken", [("thicken", lambda: one(_thicken(face, t, both=both))),
                               ("solid thicken", lambda: one(Solid.thicken(face, t)))],
                   "Thicken less than the surface's smallest radius of curvature.", ["thickness"])
