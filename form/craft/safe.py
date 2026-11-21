"""Kernel operations that degrade gracefully: each tries the plain operation, then the repairs OCCT needs in practice,
and records which one worked (form.craft.notes()), so a design builds instead of failing on "BRep_API: command not
done", and the person can see what was given up.

    from form import craft
    body = craft.safe_union(base, boss, rib)              # the boolean engine (form.craft.boolean): verified fuse, then
                                                          # the measured cause's rewrites; a gap under 0.05 mm closed
    body = craft.safe_cut(body, pocket)                   # the same for a cut; checks that material really went (a cut
                                                          # that removes nothing, or too little, is a failure)
    skin = craft.safe_loft([s0, s1, s2])                  # smooth loft, re-seamed and resampled sections, ruled, pairwise
    body = craft.safe_fillet(body, edges, 2.0)            # 75 %, 50 %, 25 %, then edge by edge
    body = craft.safe_chamfer(body, edges, 1.0)
    cup = craft.safe_shell(body, 2.0, openings=craft.faces_at(body, "top"))
    body = craft.repair(body)                             # ShapeFix + unify same-domain faces, kept only if valid
    craft.inspect(body)                                   # {"valid", "solids", "faults", "shortest_edge_mm", ...}

Every helper raises a RecipeError naming the operation, what each attempt did, and what to change when nothing works.
The fallbacks are honest: a gap is closed only when it is under `bridge` mm (default 0.05) and the note says how big
it was; a fillet is made smaller, never silently dropped without a note.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from ._common import attempt, fail, need, note, num, ok, one

BRIDGE = 0.05            # mm: the largest gap safe_union closes on its own (fuzzy boolean), and says so


# ---- repair and inspection -----------------------------------------------------------------------------------------

def repair(shape, unify: bool = True):
    """ShapeFix the shape (tolerances, small edges, orientation) and merge same-domain faces; the repaired shape is
    returned only when it is valid, otherwise the original is. Notes when it changed something."""
    from build123d import Shape
    try:
        from OCP.ShapeFix import ShapeFix_Shape
        fx = ShapeFix_Shape(shape.wrapped)
        fx.Perform()
        out = Shape.cast(fx.Shape())
        if unify:
            from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
            u = ShapeUpgrade_UnifySameDomain(out.wrapped, True, True, True)
            u.Build()
            out = Shape.cast(u.Shape())
        if _usable(out) and (not shape.is_valid or len(out.faces()) != len(shape.faces())):
            note("repair: ShapeFix and face merge applied")
            return one(out)
    except Exception:
        pass
    return shape


def inspect(shape) -> dict:
    """What the kernel thinks of a shape: valid, solids, faces, volume, shortest edge, and BRepCheck faults."""
    from ..build_diag import _shape_info
    return _shape_info("shape", shape)


def _usable(r) -> bool:
    return ok(r)


def _bool(a, b, op: str, fuzzy: float = 0.0):
    from .surfaces import _occt_bool
    return _occt_bool(a, b, op, fuzzy)


def _gap(a, b) -> float:
    """Distance between two shapes (0 when they touch or overlap)."""
    try:
        return float(a.distance_to(b))
    except Exception:
        try:
            from OCP.BRepExtrema import BRepExtrema_DistShapeShape
            d = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
            d.Perform()
            return float(d.Value()) if d.IsDone() else math.inf
        except Exception:
            return math.inf


# ---- booleans ------------------------------------------------------------------------------------------------------

def safe_union(*shapes, bridge: float = BRIDGE, expect: int | None = None):
    """Fuse shapes into one body through the boolean engine (form.craft.boolean), one added shape at a time: the plain
    fuse, verified; when it fails, the cause is measured (overlap, gap, coincident faces, operand validity) and only
    that cause's rewrites are tried (repaired operands, closed faces split, fuzzy at the measured gap or deviation, a
    tool grown past a coincident face, glued faces). A gap under `bridge` mm is closed and noted with its size.
    expect: the solid count the result should have (default: the first shape's count, so every added shape must join
    it). A shape that stays separate raises a RecipeError with what was measured (it is 3 mm apart, it touches...)."""
    from .boolean import run
    parts = [s for s in shapes if s is not None]
    if len(parts) == 1 and isinstance(parts[0], (list, tuple)):
        parts = list(parts[0])
    need(len(parts) >= 1, "safe_union needs at least one shape", "Pass the shapes to fuse.", ["shapes"])
    body = parts[0]
    for k, other in enumerate(parts[1:], 1):
        body = run(body, other, "fuse", max_solids=max(1, len(body.solids())), bridge=bridge,
                   what=f"safe_union: shape {k + 1}", names=("the body", f"shape {k + 1}"), params=["shapes"])
    if expect is not None and len(body.solids()) != expect:
        raise fail(f"safe_union: the result is {len(body.solids())} solids, not {expect}",
                   "A shape does not reach the body: overlap it by 0.2 mm or more.", ["shapes"])
    return body


def safe_cut(body, *tools, min_solids: int = 1, must_remove: bool = True):
    """body minus each tool through the boolean engine (form.craft.boolean): the plain cut, verified, then the
    measured cause's rewrites (repaired operands, seams split, fuzzy at the measured deviation, the tool grown past a
    face it grazes). A cut whose tool overlaps the body but removes nothing (OCCT sometimes returns the body
    unchanged) counts as a failure unless must_remove=False."""
    from .boolean import run
    need(bool(tools), "safe_cut needs a tool", "Pass the shape to cut away.", ["tools"])
    for k, tool in enumerate(tools, 1):
        body = run(body, tool, "cut", min_solids=min_solids, must_remove=must_remove,
                   what="safe_cut" if len(tools) == 1 else f"safe_cut: tool {k}", names=("the body", "the tool"),
                   params=["tools"])
    return body


def safe_intersect(a, b):
    """The common part of a and b through the boolean engine (verified, measured rewrites)."""
    from .boolean import run
    return run(a, b, "common", what="safe_intersect", names=("a", "b"), params=["a", "b"])


# ---- fillets and chamfers --------------------------------------------------------------------------------------------

def safe_fillet(shape, edges, radius: float, min_fraction: float = 0.25):
    """craft.surfaces.safe_fillet: the radius, 75 %, 50 %, min_fraction of it, then edge by edge; each reduction noted."""
    from .surfaces import safe_fillet as _sf
    return _sf(shape, edges, radius, min_fraction)


def safe_chamfer(shape, edges, length: float, min_fraction: float = 0.25):
    """Chamfer edges; when it does not fit, 75 %, 50 % and min_fraction of the length, then edge by edge, then leave
    them sharp. Every reduction is noted."""
    d = num(length, "length", positive=True)
    E = list(edges)
    if not E:
        return shape
    fr = [1.0, 0.75, 0.5, min_fraction]
    for i, f in enumerate(fr):
        try:
            out = shape.chamfer(d * f, None, E)
            if ok(out):
                if i:
                    note(f"safe_chamfer: {d:g} mm did not fit; used {d * f:.2g} mm")
                return out
        except Exception:
            continue
    out, done = shape, 0
    for c in [e.center() for e in E]:
        try:
            cur = min(out.edges(), key=lambda e: (e.center() - c).length)
        except ValueError:
            break
        for f in fr:
            try:
                o = out.chamfer(d * f, None, [cur])
                if ok(o):
                    out, done = o, done + 1
                    break
            except Exception:
                continue
    note(f"safe_chamfer: {d:g} mm on {len(E)} edge(s) at once did not fit; chamfered {done} edge by edge"
         + (f", {len(E) - done} left sharp" if done < len(E) else ""))
    return out


# ---- lofts and shells --------------------------------------------------------------------------------------------------

def _section_points(face, n: int):
    """n points evenly along a section's outer wire, plus its centre and normal."""
    w = face.outer_wire() if hasattr(face, "outer_wire") else face
    pts = [w.position_at(i / n) for i in range(n)]
    c = sum(pts[1:], pts[0]) * (1.0 / n)
    try:
        nrm = face.normal_at()
    except Exception:
        nrm = None
    return pts, c, nrm


def reseam(sections: Sequence, n: int = 48, spline: bool = True) -> list:
    """Sections rebuilt with the same number of points (n), the same winding and the seam at the same angle: the
    usual reasons a loft twists or fails. Vertices (a pointed tip) pass through. A section with holes is refused
    (resampling its outline would fill them)."""
    from build123d import Spline, Vector, Vertex, Wire, make_face
    out, ref, wind = [], None, None
    for s in sections:
        if isinstance(s, Vertex):
            out.append(s)
            continue
        f = make_face(s).faces()[0] if isinstance(s, Wire) else (s.faces()[0] if hasattr(s, "faces") and not hasattr(s, "outer_wire") else s)
        if hasattr(f, "inner_wires") and f.inner_wires():
            raise ValueError("a section has holes: re-seaming would drop them")   # never silently fill a hole
        pts, c, nrm = _section_points(f, n)
        axis = nrm if nrm is not None else Vector(0, 0, 1)
        area = sum(((pts[i] - c).cross(pts[(i + 1) % n] - c)).dot(axis) for i in range(n))
        if wind is None:
            wind = area >= 0
        elif (area >= 0) != wind:
            pts = pts[::-1]
        if ref is None:                                      # seam: the point furthest along a fixed direction
            ref = (pts[0] - c).normalized() if (pts[0] - c).length > 1e-9 else Vector(1, 0, 0)
        k = max(range(n), key=lambda i: (pts[i] - c).normalized().dot(ref) if (pts[i] - c).length > 1e-9 else -2)
        pts = pts[k:] + pts[:k]
        if spline:
            w = Wire([Spline(*pts, periodic=True)])
        else:
            w = Wire.make_polygon(pts, close=True)
        out.append(make_face(w).faces()[0])
    return out


def safe_loft(sections: Sequence, ruled: bool = False, n: int = 48):
    """A solid through the sections, in order. Tries: the smooth loft as given; the sections re-seamed and resampled to
    n points (craft.reseam: same count, winding and seam angle); a ruled loft; and a chain of ruled lofts between
    neighbours fused together. Each fallback is noted."""
    from build123d import Vertex, Wire, loft, make_face
    secs = list(sections)
    need(len(secs) >= 2, f"safe_loft needs at least 2 sections (got {len(secs)})", "Add sections.", ["sections"])
    secs = [make_face(s).faces()[0] if isinstance(s, Wire) else s for s in secs]

    def resampled(spline=True):
        return reseam(secs, n, spline)

    def chain():
        rs = resampled(False)
        pieces = [one(loft([rs[i], rs[i + 1]], ruled=True)) for i in range(len(rs) - 1)]
        return safe_union(*pieces) if len(pieces) > 1 else pieces[0]

    tries = []
    if not ruled:
        tries += [("smooth loft", lambda: one(loft(secs, ruled=False))),
                  ("smooth loft of re-seamed sections", lambda: one(loft(resampled(True), ruled=False)))]
    tries += [("ruled loft", lambda: one(loft(secs, ruled=True))),
              ("ruled loft of re-seamed sections", lambda: one(loft(resampled(False), ruled=True)))]
    if len(secs) > 2 and not any(isinstance(s, Vertex) for s in secs):
        tries.append(("ruled lofts between neighbours, fused", chain))
    return attempt("safe_loft", tries, "Keep sections in order along the loft, apart by 0.5 mm or more, each a closed "
                   "outline that does not cross itself; a section that crosses the next one cannot be lofted.",
                   ["sections"])


def safe_shell(solid, thickness: float, openings: Iterable | None = None, inward: bool = True,
               min_fraction: float = 0.5):
    """craft.shell (arc offset, then intersection offset), then thinner walls down to min_fraction of thickness
    (noted with the wall it used)."""
    from .surfaces import shell
    t = num(thickness, "thickness", positive=True)
    op = list(openings or [])
    last = None
    for f in (1.0, 0.75, min_fraction):
        try:
            r = shell(solid, t * f, op, inward)
            if f < 1.0:
                note(f"safe_shell: a {t:g} mm wall did not fit; used {t * f:.2g} mm")
            return r
        except Exception as e:                          # RecipeError from shell, or the kernel's own
            last = e
    raise fail(f"safe_shell: no wall from {t:g} down to {t * min_fraction:.2g} mm could be offset ({last})",
               "Round the body's tight corners first, or hollow it by lofting inset sections (craft.section_shell).",
               ["thickness"])


def safe_sweep(profile, path, frenet: bool = False):
    """Sweep a profile Face along a path (Wire or Edge). Tries: the sweep, the other frame mode, a right-corner and a
    round-corner transition."""
    from build123d import Transition, Wire, sweep
    p = path if isinstance(path, Wire) else Wire([path]) if hasattr(path, "position_at") and not hasattr(path, "edges") else path
    tries = [("sweep", lambda: one(sweep(profile, p, is_frenet=frenet))),
             ("sweep with the other frame", lambda: one(sweep(profile, p, is_frenet=not frenet))),
             ("right-corner sweep", lambda: one(sweep(profile, p, transition=Transition.RIGHT))),
             ("round-corner sweep", lambda: one(sweep(profile, p, transition=Transition.ROUND)))]
    return attempt("safe_sweep", tries, "Make the path's tightest bend larger than the profile's half-width, and place "
                   "the profile at the path's start, normal to it.", ["profile", "path"])
