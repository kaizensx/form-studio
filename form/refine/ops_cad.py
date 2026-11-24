"""CAD refinement operators: the industrial-design finish a functional build123d solid usually lacks, each one a
named feature the refinement engine (form/refine/engine.py) inserts and keeps only when the function gates hold.

    fillet_hierarchy   three radius tiers on the sharp edges: large on the long silhouette edges, medium on the
                       secondary ones, small on the rest (radii from the style, scaled down to the part)
    edge_break         a 0.3 mm round on the sharp edges that are left (a chamfer where a round does not fit)
    parting_line       a 0.5 x 0.4 mm shadow groove around the body on a horizontal split plane
    draft              a 1.5 degree draft on the vertical faces (only for a moulded or cast brief)
    knurl_zone         a diamond knurl band on a cylindrical grip, or raised diamond cells on a flat grip face
    recessed_panel     a shallow pocket with rounded corners inset in the largest open flat face
    button_pads        raised rounded pads in a row on the top face (only for a device with buttons)
    rib_lightening     a pocket with a rib grid under a thick flat floor; kept only when the checks hold

How an operator works: apply() returns a short feature method that calls the kernel-side function of the same name
in this module with literal arguments (the frozen boxes, the style's radii):

    def fillet_hierarchy(self, v, body):
        from form.refine import ops_cad
        return ops_cad.fillet_hierarchy(body, frozen=[((-4.0, -4.0, 0.0), (4.0, 4.0, 25.0))], tiers=(0.4, 1.5, 5.0))

The kernel-side functions run in the kernel worker (they import build123d and OCP inside the function, never at
module level, so the engine imports this module without a kernel). Every one of them:
  * never touches frozen geometry: an edge is left alone when its centre or an end lies in a frozen feature's box
    (grown by the radius); material is added or removed only when that material misses every frozen box;
  * never drops a rounding after a failure: a fillet that does not fit is tried on halves of the edge set, then at
    smaller radii, down to 0.2 mm, then as a chamfer (edge_break);
  * gives up quietly when nothing fits: it returns the body as it was (the candidate then gains nothing and the
    engine does not keep it), and writes why to the craft notes (form.craft.notes());
  * stops early, keeping what it made, when the feature's time budget is nearly spent (featureprog.time_left()).
Multi-part bodies (craft.parts()) are refined solid by solid and keep their part names.

Evidence class: the operators make geometry (computed); what they are for (the deficits they target) is a heuristic
of form/refine/analyze.py.
"""
from __future__ import annotations

import math
import re

from . import Operator, Patch

DEG_SHARP = 25.0            # a crease sharper than this is an edge to round (critique.sharp_edge_fraction's rule)
R_FLOOR = 0.2               # mm: the smallest round the ladder goes down to
TEXTURE_FACES = 150         # a solid with more faces than this carries a texture: edges between small faces stay
TIER_RATIO = 1.8            # critique.radius_tiers: a new tier starts at 1.8x the one below
MAX_EDGES = 120             # per tier; the longest first


def _lit(x) -> str:
    return repr(x)


# =====================================================================================================================
# kernel side (runs in the kernel worker; build123d and OCP are imported inside the functions)
# =====================================================================================================================

_RUN = {"stop": False, "tries": 0, "frozen": (), "sig": None}
MAX_TRIES = 160             # fillet or chamfer calls per operator run: past it, keep what is made and stop


def _time_low(s: float = 1.0) -> bool:
    """True when the operator must stop: the feature's budget is nearly spent, its alarm already rang, or it has
    made MAX_TRIES kernel calls."""
    if _RUN["stop"] or _RUN["tries"] >= MAX_TRIES:
        return True
    try:
        from ..featureprog import time_left
        t = time_left()
    except Exception:                                              # noqa: BLE001
        return False
    return t is not None and t < s


def _note(text: str) -> None:
    try:
        from ..craft._common import note
        note(text)
    except Exception:                                              # noqa: BLE001
        pass


def _ok(shape) -> bool:
    from ..craft._common import ok
    return ok(shape)


def _solids(body) -> list:
    try:
        return list(body.solids())
    except Exception:                                              # noqa: BLE001
        return []


def _rebuild(body, outs: list):
    """The body with its solids replaced by outs (same order), keeping a craft.parts() result's names and gaps."""
    from build123d import Compound
    names = getattr(body, "part_names", None)
    if len(outs) == 1 and not names:
        return outs[0]
    for i, (o, s) in enumerate(zip(outs, _solids(body))):
        try:
            o.label = names[i] if names and i < len(names) else s.label
        except Exception:                                          # noqa: BLE001
            pass
    out = Compound(outs)
    out.label = getattr(body, "label", "") or ""
    if names:
        out.part_names = list(names)
        out.part_gaps = dict(getattr(body, "part_gaps", {}) or {})
    return out


def _per_solid(body, fn, main_only: bool = False):
    """fn(solid) -> solid applied to each solid (main_only: the largest one). A solid fn breaks stays as it was."""
    _RUN.update(stop=False, tries=0, frozen=(), sig=None)
    sols = _solids(body)
    if not sols:
        return body
    targets = range(len(sols))
    if main_only:
        targets = [max(range(len(sols)), key=lambda i: sols[i].volume)]
    outs, changed = list(sols), False
    for i in targets:
        _RUN["sig"] = None                         # the frozen faces' signature is per solid
        try:
            r = fn(sols[i])
        except Exception as e:                                     # noqa: BLE001 - a refinement never breaks a build
            _note(f"refine: {getattr(fn, '__name__', 'operator')} left a solid as it was ({type(e).__name__}: {e})"[:200])
            r = None
        if r is not None and r is not sols[i] and _ok(r) and len(_solids(r)) == 1:
            outs[i] = _solids(r)[0]
            changed = True
    if not changed:
        return body
    if len(sols) == 1 and not getattr(body, "part_names", None):
        return outs[0]
    return _rebuild(body, outs)


def _in_box(p, boxes, margin: float) -> bool:
    for lo, hi in boxes or ():
        if all(lo[i] - margin <= p[i] <= hi[i] + margin for i in range(3)):
            return True
    return False


def _bb(shape):
    b = shape.bounding_box()
    return (b.min.X, b.min.Y, b.min.Z), (b.max.X, b.max.Y, b.max.Z)


def _hits_frozen(shape, boxes, margin: float = 0.3) -> bool:
    """True when material `shape` (what an operator adds or removes) reaches into a frozen box grown by margin."""
    from build123d import Box, Pos
    if shape is None or not boxes:
        return False
    (a0, a1, a2), (b0, b1, b2) = _bb(shape)
    for lo, hi in boxes:
        lo = [lo[i] - margin for i in range(3)]
        hi = [hi[i] + margin for i in range(3)]
        if b0 < lo[0] or a0 > hi[0] or b1 < lo[1] or a1 > hi[1] or b2 < lo[2] or a2 > hi[2]:
            continue
        size = [max(hi[i] - lo[i], 1e-3) for i in range(3)]
        box = Pos(*[(lo[i] + hi[i]) / 2 for i in range(3)]) * Box(*size)
        try:
            got = shape & box                                      # None when nothing is in common
            if got is not None and got.volume > 1e-4:
                return True
        except Exception:                                          # noqa: BLE001 - cannot tell: count it as a hit
            return True
    return False


FREE = ("BSPLINE", "BEZIER", "OFFSET", "OTHER", "EXTRUSION", "REVOLUTION")


def _inside_box(lo, hi, boxes, margin: float) -> bool:
    for a, b in boxes or ():
        if all(a[i] - margin <= lo[i] and hi[i] <= b[i] + margin for i in range(3)):
            return True
    return False


def _blend(face, cache: dict) -> bool:
    """True for a face that is a blend already: a torus, a small sphere, or a part of a small cylinder (a fillet)."""
    k = ("blend", hash(face.wrapped))
    if k in cache:
        return cache[k]
    t = face.geom_type.name
    out = False
    if t == "TORUS":
        out = True
    elif t in ("CYLINDER", "SPHERE"):
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            ad = BRepAdaptor_Surface(face.wrapped)
            if t == "SPHERE":
                out = ad.Sphere().Radius() <= 8.0
            else:
                R = ad.Cylinder().Radius()
                du = abs(ad.LastUParameter() - ad.FirstUParameter())
                out = R <= 8.0 and du < 0.75 * math.pi              # a quarter or half round, not a boss or bore
        except Exception:                                          # noqa: BLE001
            out = False
    cache[k] = out
    return out


def sharp_edges(solid, frozen=(), deg: float = DEG_SHARP, margin: float = 0.5, free: bool = False) -> list:
    """[(edge, crease degrees, length, larger and smaller adjacent face area)] of the solid's edges between two faces that meet
    at more than deg. Left out: edges near a frozen box (a point along them within margin), edges of a face that
    lies inside a frozen box (grown by margin + 0.5: a chamfer on a bore's mouth belongs to the bore), edges of a
    blend (_blend: a fillet that is there already), and, unless
    free, edges between two free-form faces (OCCT's fillet between two splines can hang the kernel)."""
    from build123d import Edge, Face, Vector
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    try:
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape as EdgeFaceMap
    except ImportError:                                            # newer OCP names the template instance
        from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EdgeFaceMap
    from OCP.BRep import BRep_Tool
    m = EdgeFaceMap()
    TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    areas: dict = {}
    out = []
    for i in range(1, m.Extent() + 1):
        te = TopoDS.Edge_s(m.FindKey(i)) if hasattr(TopoDS, "Edge_s") else TopoDS.Edge(m.FindKey(i))
        if BRep_Tool.Degenerated_s(te):
            continue
        uniq = []
        for f in m.FindFromIndex(i):
            if not any(f.IsSame(g) for g in uniq):
                uniq.append(f)
        if len(uniq) != 2:
            continue
        e = Edge(te)
        try:
            pts = [e.position_at(t) for t in (0.5, 0.0, 0.125, 0.25, 0.375, 0.625, 0.75, 0.875, 1.0)]   # on the curve
        except Exception:                                          # noqa: BLE001
            continue
        c = pts[0]
        if any(_in_box((p.X, p.Y, p.Z), frozen, margin) for p in pts):
            continue
        faces = [Face(TopoDS.Face_s(f) if hasattr(TopoDS, "Face_s") else TopoDS.Face(f)) for f in uniq]
        if not free and all(f.geom_type.name in FREE for f in faces):
            continue
        if any(_blend(f, areas) for f in faces):
            continue                       # a crease along a blend: rounding it again is how OCCT's fillet crashes
        if frozen:
            near = False
            for f in faces:
                k = ("bb", hash(f.wrapped))
                if k not in areas:
                    areas[k] = _bb(f)
                if _inside_box(*areas[k], frozen, margin + 0.5):
                    near = True
                    break
            if near:
                continue
        try:
            n = [f.normal_at(Vector(c)) for f in faces]
        except Exception:                                          # noqa: BLE001
            continue
        ang = math.degrees(math.acos(max(-1.0, min(1.0, n[0].dot(n[1])))))
        if ang <= deg:
            continue
        fa = []
        for f in faces:
            k = hash(f.wrapped)
            if k not in areas:
                areas[k] = f.area
            fa.append(areas[k])
        out.append((e, ang, e.length, max(fa), min(fa)))
    return out


def _edge_cap(solid) -> int:
    """Edges per tier: MAX_EDGES, or 20 on a heavy solid (over 2000 faces), where every fillet try costs seconds."""
    try:
        return MAX_EDGES if len(solid.faces()) <= 2000 else 20
    except Exception:                                              # noqa: BLE001
        return 20


def _texture_filter(solid, rows: list) -> list:
    """Edges of a textured solid (many faces) are kept only when they border a large face: a knurl's or a relief's
    facets are sharp on purpose and must stay crisp."""
    try:
        nf = len(solid.faces())
        total = sum(f.area for f in solid.faces())
    except Exception:                                              # noqa: BLE001
        return rows
    if nf <= TEXTURE_FACES:
        return rows
    return [r for r in rows if r[3] >= 0.01 * total]


def _pt(e):
    """How an edge is found again after other edges were rounded: (the middle of the curve, its kind). A fillet
    trims an edge but keeps it on its curve; an edge of another kind through the point (a new blend's arc) is not
    it, and rounding that one is how OCCT's fillet crashes."""
    return e.position_at(0.5), e.geom_type.name


def _nearest(edges, ref, tol: float):
    """(index, distance) of the edge of ref's kind passing within tol of ref's point, or None."""
    p, kind = ref if isinstance(ref, tuple) else (ref, None)
    best = None
    for i, (e, (lo, hi)) in enumerate(edges):
        if not all(lo[k] - tol <= (p.X, p.Y, p.Z)[k] <= hi[k] + tol for k in range(3)):
            continue
        if kind is not None and e.geom_type.name != kind:
            continue
        try:
            d = e.distance_to(p)
        except Exception:                                          # noqa: BLE001
            continue
        if d <= tol and (best is None or d < best[1]):
            best = (i, d)
    return best


def _with_bb(edges) -> list:
    return [(e, _bb(e)) for e in edges]


def _match(solid, points, tol: float) -> list:
    """The solid's edges passing within tol of the points (one each)."""
    es = _with_bb(solid.edges())
    out, seen = [], set()
    for p in points:
        hit = _nearest(es, p, tol)
        if hit is not None and hit[0] not in seen:
            seen.add(hit[0])
            out.append(es[hit[0]][0])
    return out


CHUNK = 12                  # edges per fillet call at most
TOL = 0.02                  # mm: an edge is found again by a point on it (fillets trim edges, never move them)


def frozen_signature(solid, boxes) -> list:
    """(area, kind, bounding box) of every face lying inside a frozen box: what must not change. A round that runs on along a
    tangent chain (OCCT propagates a fillet over tangent edges) can reach a frozen face from an edge far from it;
    comparing this before and after each round catches that."""
    if not boxes:
        return []
    out = []
    for f in solid.faces():
        lo, hi = _bb(f)
        if _inside_box(lo, hi, boxes, 0.3):      # the boxes come from a tessellation: a curved face pokes out
            out.append((round(f.area, 2), f.geom_type.name, tuple(round(x, 2) for x in lo + hi)))
    return sorted(out)


def _attempt(solid, E, r: float, chamfer: bool):
    """One fillet (or chamfer) call: the new solid, or None (also when it changed a face inside a frozen box). The
    feature's time alarm (FeatureTimeout) stops the whole operator, keeping what it made."""
    import copy
    _RUN["tries"] += 1
    try:
        # on a copy: a fillet that fails can leave raised tolerances on the shape it was given (OCCT shares
        # sub-shapes), and the solid that is kept must be the one that was checked
        work = copy.deepcopy(solid)
        pts = [_pt(e) for e in E]
        WE = _match(work, pts, TOL)
        if len(WE) != len(E):
            return None
        out = work.chamfer(r, None, WE) if chamfer else work.fillet(r, WE)
        if _ok(out) and len(_solids(out)) == 1:
            out = _solids(out)[0]
            if _RUN["frozen"]:
                if _RUN["sig"] is None:
                    _RUN["sig"] = frozen_signature(solid, _RUN["frozen"])
                if frozen_signature(out, _RUN["frozen"]) != _RUN["sig"]:
                    return None
            return out
    except Exception as e:                                         # noqa: BLE001
        if type(e).__name__ == "FeatureTimeout":
            _RUN["stop"] = True
    return None


def _round(solid, points, radii, made: dict, chamfer_last: float | None = None):
    """(solid, edges rounded): the edges through the points rounded with radii[0], all at once (CHUNK at most per
    call); a set that fails is halved down to single edges, and a single edge goes down the rest of the radii, then
    (chamfer_last) takes a chamfer. made counts edges per radius."""
    if not points or _time_low():
        return solid, 0
    if len(points) > CHUNK:                       # OCCT's fillet can crash the kernel on one large set: chunks
        h = len(points) // 2
        s1, n1 = _round(solid, points[:h], radii, made, chamfer_last)
        s2, n2 = _round(s1, points[h:], radii, made, chamfer_last)
        return s2, n1 + n2
    E = _match(solid, points, TOL)
    if not E:
        return solid, 0
    out = _attempt(solid, E, radii[0], False)
    if out is not None:
        made[round(radii[0], 2)] = made.get(round(radii[0], 2), 0) + len(E)
        return out, len(E)
    if len(points) > 1:
        h = len(points) // 2
        s1, n1 = _round(solid, points[:h], radii, made, chamfer_last)
        s2, n2 = _round(s1, points[h:], radii, made, chamfer_last)
        return s2, n1 + n2
    for r in radii[1:]:                            # one edge: a smaller radius, never no rounding at all
        if _time_low():
            return solid, 0
        out = _attempt(solid, E, r, False)
        if out is not None:
            made[round(r, 2)] = made.get(round(r, 2), 0) + 1
            return out, 1
    if chamfer_last and not _time_low():
        out = _attempt(solid, E, chamfer_last, True)
        if out is not None:
            k = f"chamfer {chamfer_last:g}"
            made[k] = made.get(k, 0) + 1
            return out, 1
    return solid, 0


def _ladder(solid, points, radii, frozen, deg: float, chamfer_last: float | None = None):
    """Round the edges through the points with the first radius that fits each of them, never dropping one: radii
    in descending order, then (chamfer_last) a chamfer. Returns (solid, {radius: edges made}, edges left sharp)."""
    made: dict = {}
    if _RUN["frozen"] != tuple(map(tuple, frozen or ())):
        _RUN.update(frozen=tuple(map(tuple, frozen or ())), sig=None)
    solid, n = _round(solid, list(points), list(radii), made, chamfer_last)
    return solid, made, len(points) - n


def _steps(r: float, floor: float = R_FLOOR) -> list:
    out = [r * f for f in (1.0, 0.5, 0.25) if r * f >= floor]
    return (out or [floor]) + ([floor] if out and out[-1] > floor * 1.05 else [])


def tier_radii(tiers, min_dim: float, plan_dim: float | None = None) -> list:
    """The three radii (small, medium, large) scaled down to the part: the large one at most 12 % of the plan's
    narrower side (it rounds the plan corners), the others at most 12 % of the thinnest dimension, each at least
    1.8x the one below while that stays above the 0.2 mm floor."""
    t = sorted(float(x) for x in tiers)[:3]
    while len(t) < 3:
        t.append(t[-1] * 3 if t else 1.0)
    cap = max(R_FLOOR, 0.12 * float(min_dim))
    big = min(t[2], max(cap, 0.12 * float(plan_dim if plan_dim is not None else min_dim)))
    mid = min(t[1], cap, big / TIER_RATIO)
    small = min(t[0], mid / TIER_RATIO)
    return [round(max(R_FLOOR, x), 2) for x in (small, mid, big)]


def edge_tiers(solid, rows, radii=None, frozen=()) -> dict:
    """{0: small, 1: medium, 2: large: [edge points]} by the edge's part in the form (the industrial-design rule):
    long vertical edges are the plan corners and take the large radius; the other long edges (the top and side
    perimeters) the medium one; the edges on the bottom (the footprint) and the short details the small one. A part
    with no vertical corner gives the large radius to its longest edges (30 % of the diagonal or more).
    With radii, an edge moves down a tier while its radius is more than 45 % of the narrower face it joins (a 5 mm
    round on a 2 mm rib cannot fit and only costs the kernel time), or while an end of the edge comes within that
    radius (+0.5 mm) of a frozen box (the round would trim the frozen face at the corner); an edge that fits no tier
    is left alone."""
    lo, hi = _bb(solid)
    dims = [hi[i] - lo[i] for i in range(3)]
    diag = math.sqrt(sum(d * d for d in dims)) or 1.0
    role = []
    for row in sorted(rows, key=lambda r: -r[2]):
        e, L = row[0], row[2]
        a, b = e.position_at(0), e.position_at(1)
        bottom = abs(a.Z - lo[2]) < 0.05 and abs(b.Z - lo[2]) < 0.05
        vertical = e.geom_type.name == "LINE" and abs(e.tangent_at(0.5).Z) > 0.95
        if bottom:
            k = 0
        elif vertical and L >= 0.25 * max(dims[2], 1e-6):
            k = 2
        elif L >= 0.08 * diag:
            k = 3 if L >= 0.3 * diag else 1            # 3: a long edge, large if the part has no vertical corner
        else:
            k = 0
        role.append([row, k])
    corners = any(k == 2 for _r, k in role)
    for x in role:
        if x[1] == 3:
            x[1] = 1 if corners else 2
    groups = {2: [], 1: [], 0: []}
    cap = _edge_cap(solid)
    for row, k in role:
        e, L = row[0], max(row[2], 1e-6)
        if radii is not None:
            fit = 0.45 * (row[4] if len(row) > 4 else row[3]) / L
            ends = [e.position_at(0), e.position_at(1)]
            while k >= 0 and (radii[k] > fit and k > 0 or
                              any(_in_box((p.X, p.Y, p.Z), frozen, radii[k] + 0.5) for p in ends)):
                k -= 1
            if k < 0:
                continue
        if len(groups[k]) < cap:
            groups[k].append(_pt(e))
    return groups


def fillet_hierarchy(body, frozen=(), tiers=(0.4, 1.5, 5.0), deg: float = DEG_SHARP):
    """Three radius tiers on the sharp edges (edge_tiers: plan corners large, perimeters medium, footprint and
    details small), the largest first, each tier down its own ladder of radii."""
    def one(solid):
        lo, hi = _bb(solid)
        dims = [hi[i] - lo[i] for i in range(3)]
        radii = tier_radii(tiers, min(dims), min(dims[0], dims[1]))
        rows = _texture_filter(solid, sharp_edges(solid, frozen, deg, margin=0.5))
        if not rows:
            return None
        groups = edge_tiers(solid, rows, radii, frozen)
        made_all, left_all = {}, 0
        for k in (2, 1, 0):
            if not groups[k]:
                continue
            solid, made, left = _ladder(solid, groups[k], _steps(radii[k]), frozen, deg)
            for r, n in made.items():
                made_all[r] = made_all.get(r, 0) + n
            left_all += left
        if not made_all:
            return None
        _note("refine fillet_hierarchy: " + ", ".join(f"{n} edge(s) at {r} mm" for r, n in sorted(made_all.items()))
              + (f"; {left_all} left sharp (no radius down to {R_FLOOR} mm fitted)" if left_all else ""))
        return solid
    one.__name__ = "fillet_hierarchy"
    return _per_solid(body, one)


def edge_break(body, frozen=(), r: float = 0.3, deg: float = DEG_SHARP, max_edges: int = 250):
    """A small round on every sharp edge that is left (a chamfer of the same size where a round does not fit)."""
    def one(solid):
        rows = _texture_filter(solid, sharp_edges(solid, frozen, deg, margin=0.5))
        if not rows:
            return None
        centers = [_pt(r[0]) for r in sorted(rows, key=lambda x: -x[2])[:min(max_edges, 2 * _edge_cap(solid))]]
        solid, made, left = _ladder(solid, centers, _steps(r, min(R_FLOOR, r)), frozen, deg, chamfer_last=r)
        if not made:
            return None
        _note(f"refine edge_break: {sum(made.values())} edge(s) broken" + (f", {left} left sharp" if left else ""))
        return solid
    one.__name__ = "edge_break"
    return _per_solid(body, one)


def _sections(solid, z: float):
    """The faces of the solid's cross-section at height z (the top faces of a 0.02 mm slab)."""
    from build123d import Align, Box, Pos
    lo, hi = _bb(solid)
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    sl = solid & Pos(cx, cy, z) * Box(hi[0] - lo[0] + 4, hi[1] - lo[1] + 4, 0.02, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return [f for f in sl.faces() if f.normal_at().Z > 0.99 and abs(f.center().Z - (z + 0.02)) < 1e-3]


def parting_line(body, frozen=(), width: float = 0.5, depth: float = 0.4, at=(0.42, 0.5, 0.36, 0.58, 0.3, 0.66)):
    """A shadow groove width x depth around the main body on a horizontal plane, the first height (fraction of the
    body's height, in order) where the groove misses every frozen box and follows the surface (a sloped or
    stepped wall there would cut a shelf, not a line)."""
    from build123d import Align, Box, Face, Kind, Pos, extrude, offset
    bottom = (Align.CENTER, Align.CENTER, Align.MIN)

    def one(solid):
        lo, hi = _bb(solid)
        H = hi[2] - lo[2]
        if H < 6 * width:
            return None
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        for frac in at:
            if _time_low():
                return None
            z0 = lo[2] + frac * H
            secs = _sections(solid, z0)
            if not secs or sum(len(f.outer_wire().edges()) for f in secs) > 16:
                continue                                           # a fluted or ribbed section: a groove reads as a crack
            try:
                inner = [offset(Face(f.outer_wire()), -depth, kind=Kind.ARC) for f in secs]
            except Exception:                                      # noqa: BLE001 - this plane does not offset
                continue
            perim = sum(f.outer_wire().length for f in secs)
            z = z0 - width / 2
            tool = Pos(cx, cy, z) * Box(hi[0] - lo[0] + 6, hi[1] - lo[1] + 6, width, align=bottom)
            for f in inner:                                        # the section sits at z0 + 0.02 (the slab's top)
                tool = tool - Pos(0, 0, z - 0.01 - f.center().Z) * extrude(f, width + 0.02)
            removed = solid & tool
            v = removed.volume if removed is not None else 0.0
            if v < 0.2 * perim * width * depth or v > 1.6 * perim * width * depth:
                continue                                           # nothing cut, or a shelf rather than a line
            if _hits_frozen(removed, frozen):
                continue
            out = solid - tool
            if _ok(out) and len(_solids(out)) == 1:
                _note(f"refine parting_line: {width:g} x {depth:g} mm groove at z = {z0:.1f} mm")
                return out
        return None
    one.__name__ = "parting_line"
    return _per_solid(body, one, main_only=True)


def draft(body, frozen=(), angle: float = 1.5):
    """A draft on the main body's vertical flat faces, neutral plane at the bottom (a moulded part's release)."""
    from build123d import Plane

    def one(solid):
        lo, _hi = _bb(solid)
        faces = [f for f in solid.faces() if f.geom_type.name == "PLANE" and abs(f.normal_at().Z) < 1e-3
                 and not _in_box(tuple(f.center()), frozen, 0.5)]
        if not faces:
            return None
        try:
            out = solid.draft(faces, Plane.XY.offset(lo[2]), angle)
        except Exception:                                          # noqa: BLE001
            return None
        return out if _ok(out) else None
    one.__name__ = "draft"
    return _per_solid(body, one, main_only=True)


def _cyl_grip(solid, frozen, min_r: float = 3.0, min_h: float = 6.0):
    """(axis x, axis y, radius, z0, z1) of the largest outer cylindrical face with a vertical axis, or None."""
    from build123d import Vector
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    best = None
    for f in solid.faces():
        if f.geom_type.name != "CYLINDER":
            continue
        try:
            cy = BRepAdaptor_Surface(f.wrapped).Cylinder()
        except Exception:                                          # noqa: BLE001
            continue
        d, loc, R = cy.Axis().Direction(), cy.Axis().Location(), cy.Radius()
        if abs(d.Z()) < 0.999 or R < min_r:
            continue
        lo, hi = _bb(f)
        h = hi[2] - lo[2]
        if h < min_h or f.area < 0.9 * 2 * math.pi * R * h:
            continue
        c = f.center()
        radial = Vector(c.X - loc.X(), c.Y - loc.Y(), 0)
        if radial.length < 1e-6 or f.normal_at(c).dot(radial.normalized()) <= 0:
            continue                                               # a bore, not a grip
        if best is None or f.area > best[0]:
            best = (f.area, (loc.X(), loc.Y(), R, lo[2], hi[2]))
    return best[1] if best else None


def _flat_grip(solid, frozen, band, min_w: float = 14.0, min_h: float = 10.0):
    """The largest vertical flat face inside the grip band, or None."""
    lo, hi = _bb(solid)
    H = hi[2] - lo[2]
    best = None
    for f in solid.faces():
        if f.geom_type.name != "PLANE" or abs(f.normal_at().Z) > 0.05:
            continue
        flo, fhi = _bb(f)
        z0, z1 = max(flo[2], lo[2] + band[0] * H), min(fhi[2], lo[2] + band[1] * H)
        w = math.hypot(fhi[0] - flo[0], fhi[1] - flo[1])
        if z1 - z0 < min_h or w < min_w:
            continue
        if best is None or f.area > best[0]:
            best = (f.area, f, z0, z1, w)
    return best[1:] if best else None


def knurl_zone(body, frozen=(), pitch: float = 1.6, depth: float = 0.5, band=(0.2, 0.8), kind: str = "diamond"):
    """A knurled band on the main body's largest outer vertical cylinder, between band fractions of its height (the
    grip). Without such a cylinder: raised diamond cells on the largest vertical flat face in the band."""
    from build123d import Align, Box, Cylinder, Plane, Pos, Vector
    from .. import craft
    bottom = (Align.CENTER, Align.CENTER, Align.MIN)

    def one(solid):
        g = _cyl_grip(solid, frozen)
        if g is not None:
            x, y, R, z0, z1 = g
            h = z1 - z0
            zb, hb = z0 + band[0] * h, (band[1] - band[0]) * h
            if hb < 4 or depth >= R / 6:
                return None
            ring = Pos(x, y, zb) * (Cylinder(R + 2, hb, align=bottom) - Cylinder(R - depth, hb, align=bottom))
            removed = solid & ring
            if removed is None or removed.volume < 1e-3 or _hits_frozen(removed, frozen):
                return None
            k = craft.knurl(2 * R, hb, pitch=pitch, depth=1.5 * depth, kind=kind, chamfer=min(0.6, hb / 4))
            core = craft.safe_cut(solid, ring)
            out = craft.safe_union(core, Pos(x, y, zb) * k)
            _note(f"refine knurl_zone: {kind} knurl, pitch {pitch:g} mm, on a {2 * R:.1f} mm grip over {hb:.1f} mm")
            return out
        fg = _flat_grip(solid, frozen, band)
        if fg is None:
            return None
        f, z0, z1, w = fg
        n = f.normal_at()
        c = f.center()
        x_dir = Vector(-n.Y, n.X, 0).normalized()
        zc = (z0 + z1) / 2
        origin = Vector(c.X, c.Y, zc)
        W, D = 0.7 * w, 0.7 * (z1 - z0)
        pad = craft.emboss_cells(W, D, cell=max(2.4, 2 * pitch), height=depth, kind="diamond", gap=0.6,
                                 plane=Plane(origin=origin - n * 0.05, x_dir=x_dir, z_dir=n))
        if _hits_frozen(pad, frozen):
            return None
        # the cells must sit on this face, not hang past its edge: solid all the way under the pad
        probe = Plane(origin=origin - n * 0.3, x_dir=x_dir, z_dir=n) * Box(W, D, 0.2)
        inside = solid & probe
        if inside is None or inside.volume < 0.98 * probe.volume:
            return None                                           # the face does not hold the whole pad
        out = craft.safe_union(solid, pad)
        _note(f"refine knurl_zone: diamond cells {W:.0f} x {D:.0f} mm on a flat grip face")
        return out
    one.__name__ = "knurl_zone"
    return _per_solid(body, one, main_only=True)


def _open_flats(solid, frozen, up_only: bool = False, skip_bottom: bool = True):
    """Flat faces of the solid, largest first, that are not the bottom (the bed or the table) and not frozen."""
    lo, _hi = _bb(solid)
    out = []
    for f in solid.faces():
        if f.geom_type.name != "PLANE":
            continue
        n = f.normal_at()
        if skip_bottom and n.Z < -0.99 and abs(f.center().Z - lo[2]) < 0.05:
            continue
        if up_only and n.Z < 0.99:
            continue
        out.append(f)                    # frozen geometry is kept out by testing the material an operator moves
    return sorted(out, key=lambda f: -f.area)


def _inset(face, m: float, rc: float):
    """The face's region inset by m from its outer edge and from its holes, with corners rounded rc."""
    from build123d import Face, Kind, offset
    region = offset(offset(Face(face.outer_wire()), -(m + rc), kind=Kind.INTERSECTION), rc, kind=Kind.ARC)
    for w in face.inner_wires():
        region = region - offset(Face(w), m, kind=Kind.ARC)
    return region


def _plane_dims(face) -> tuple[float, float]:
    """The face's extent along its two in-plane axes (its bounding box seen square-on)."""
    from build123d import Plane
    pl = Plane(origin=face.center(), z_dir=face.normal_at())
    loc = pl.to_local_coords(face)
    lo, hi = _bb(loc)
    d = sorted([hi[0] - lo[0], hi[1] - lo[1]])
    return d[0], d[1]


def recessed_panel(body, frozen=(), depth: float = 0.6, inset: float = 0.12, min_size: float = 15.0):
    """A pocket depth deep in the largest open flat face, inset from its edges and holes, corners rounded: the
    face reads as a panel in a frame instead of one large slab."""
    from build123d import extrude

    def one(solid):
        for f in _open_flats(solid, frozen)[:3]:
            if _time_low():
                return None
            a, b = _plane_dims(f)
            if a < min_size:
                continue
            m = max(2.0, inset * a)
            try:
                region = _inset(f, m, max(1.0, 0.5 * m))
            except Exception:                                      # noqa: BLE001
                continue
            if region is None or region.area < 0.25 * f.area:
                continue
            tool = extrude(region, depth, dir=-f.normal_at())
            removed = solid & tool
            if removed is None or removed.volume < 0.9 * tool.volume or _hits_frozen(removed, frozen):
                continue                                           # not all solid under the panel, or frozen
            out = solid - tool
            if _ok(out) and len(_solids(out)) == 1:
                _note(f"refine recessed_panel: {depth:g} mm panel inset {m:.1f} mm in a {a:.0f} x {b:.0f} mm face")
                return out
        return None
    one.__name__ = "recessed_panel"
    return _per_solid(body, one, main_only=True)


def button_pads(body, frozen=(), height: float = 0.6, count: int = 3, r_edge: float = 0.3):
    """count raised rounded pads in a row along the long axis of the top face, in its upper half."""
    from build123d import Plane, RectangleRounded, Vector, extrude
    from .. import craft

    def one(solid):
        tops = _open_flats(solid, frozen, up_only=True)
        if not tops:
            return None
        f = tops[0]
        flo, fhi = _bb(f)
        wx, wy = fhi[0] - flo[0], fhi[1] - flo[1]
        along = Vector(1, 0, 0) if wx >= wy else Vector(0, 1, 0)
        across = Vector(-along.Y, along.X, 0)
        L, S = max(wx, wy), min(wx, wy)
        if S < 12 or L < 30:
            return None
        pw, pl = 0.34 * S, min(0.13 * L, 0.5 * S)
        c = f.center()
        step = 1.7 * pl
        start = 0.5 * L - 0.18 * L - (count - 1) * step                # the row ends 18 % from the far end
        pads = None
        for shift, side in ((0, 0), (-0.1, 0), (0.1, 0), (0, 0.22), (0, -0.22), (-0.2, 0)):
            row = []
            for i in range(count):
                p = Vector(c.X, c.Y, c.Z) + along * (start + shift * L + i * step) + across * (side * S)
                foot = Plane(origin=p, x_dir=across, z_dir=(0, 0, 1)) * RectangleRounded(pw, pl, min(pw, pl) * 0.3)
                try:
                    inside = foot & f
                    if inside is None or inside.area < 0.99 * foot.area:
                        break                                      # hangs past the face or over a hole: move the row
                except Exception:                                  # noqa: BLE001
                    break
                row.append(extrude(foot, height))
            if len(row) == count:
                pads = row[0]
                for x in row[1:]:
                    pads = pads + x
                if not _hits_frozen(pads, frozen):
                    break
                pads = None
        if pads is None:
            return None
        out = craft.safe_union(solid, pads)
        top = [e for e in out.edges() if abs(e.center().Z - (c.Z + height)) < 1e-3]
        if top:
            out = craft.safe_fillet(out, top, r_edge, min_fraction=0.5)
        _note(f"refine button_pads: {count} pads {pw:.1f} x {pl:.1f} x {height:g} mm on the top face")
        return out
    one.__name__ = "button_pads"
    return _per_solid(body, one, main_only=True)


def rib_lightening(body, frozen=(), pitch: float = 10.0, t: float = 1.6, skin: float = 1.6, side: str = "bottom",
                   max_share: float = 0.3):
    """A pocket under (side="bottom") or over (side="top") the main body's largest floor face, left with a rib grid:
    only where the body is solid at least pocket depth + skin, and never more than max_share of its volume."""
    from build123d import Pos, Rot, extrude
    from .. import craft

    def one(solid):
        lo, hi = _bb(solid)
        want = -1 if side == "bottom" else 1
        cand = [f for f in solid.faces() if f.geom_type.name == "PLANE" and f.normal_at().Z * want > 0.99]
        cand = [f for f in cand if abs(f.center().Z - (lo[2] if want < 0 else hi[2])) < 0.05] or cand
        for f in sorted(cand, key=lambda f: -f.area)[:2]:
            a, b = _plane_dims(f)
            if a < 3 * pitch:
                continue
            try:
                region = _inset(f, max(3.0, 2 * t), 1.0)
            except Exception:                                      # noqa: BLE001
                continue
            if region is None or region.area < 0.3 * f.area:
                continue
            inward = -f.normal_at()
            for d in (12.0, 8.0, 6.0, 4.0, 3.0):
                if _time_low():
                    return None
                probe = extrude(region, d + skin, dir=inward)
                got = solid & probe
                if got is None or got.volume < 0.995 * probe.volume:
                    continue
                pocket = extrude(region, d, dir=inward)
                if pocket.volume > max_share * solid.volume or _hits_frozen(pocket, frozen):
                    continue
                rlo, rhi = _bb(region)
                grid = craft.rib_grid(rhi[0] - rlo[0] + 2 * t, rhi[1] - rlo[1] + 2 * t, height=d, pitch=pitch, t=t,
                                      border=False)
                z = f.center().Z
                # rib_grid stands on z = 0 going up: right for a pocket under the floor, flipped for one from the top
                grid = Pos((rlo[0] + rhi[0]) / 2, (rlo[1] + rhi[1]) / 2, z) * (grid if want < 0 else Rot(180, 0, 0) * grid)
                tool = pocket - grid
                out = craft.safe_cut(solid, tool)
                if _ok(out) and len(_solids(out)) == 1:
                    _note(f"refine rib_lightening: {d:g} mm pocket with {pitch:g} mm ribs under a {a:.0f} x {b:.0f} mm floor")
                    return out
        return None
    one.__name__ = "rib_lightening"
    return _per_solid(body, one, main_only=True)


# =====================================================================================================================
# operators (engine side: no kernel)
# =====================================================================================================================

def _words(d) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9 ]+", " ", (d.brief or "").lower()).split()) + " "


def _has(d, words) -> bool:
    w = _words(d)
    return any(f" {x}" in w for x in words)


def _call(fn: str, design, **kw) -> str:
    # the frozen boxes are measured when the design builds (the faces the frozen features made in this build, so they
    # follow a parameter change); the literal, measured when the feature was written, is the fallback
    args = ", ".join([f"frozen=frozen_boxes(self, {design.frozen_boxes_literal()})"]
                     + [f"{k}={_lit(v)}" for k, v in kw.items()])
    return (f"def {fn}(self, v, body):\n"
            f"    from form.refine import frozen_boxes, ops_cad\n"
            f"    return ops_cad.{fn}(body, {args})\n")


CUT_SHELL = (0.75, 0.10)    # free-form share at least, plane share at least: a free-form shell cut by planes
CUT_SHELL_WHY = ("a free-form shell cut by planes (a crest, a rim, a visor opening): OCCT's rounds where the planes meet "
                 "the shell facet (measured on the hero helmet's crest) or crash the kernel (the twisted shade), so "
                 "the edge break rounds or chamfers its edges instead")


def cut_shell(analysis) -> bool:
    """True for a free-form shell cut by planes (analysis.measures["surface_mix"], critique's surface kinds)."""
    mix = (analysis.measures or {}).get("surface_mix") or {}
    return float(mix.get("free", 0)) >= CUT_SHELL[0] and float(mix.get("plane", 0)) >= CUT_SHELL[1]


class _CadOp(Operator):
    domain = "cad"

    def _common(self, design, analysis):
        if design.purpose == "game":
            return False, "a CAD operator has no meaning on a game cage"
        if any(f == f"refine_{self.name}" or f.startswith(f"refine_{self.name}_") for f in design.refined):
            return False, "already refined with this operator"
        return True, ""


class FilletHierarchy(_CadOp):
    name = "fillet_hierarchy"
    targets = ("edge_hierarchy", "touch_points", "detail_scales")
    cost = 1.0
    label = "Fillet hierarchy"
    params = {"tiers": [0.4, 1.5, 5.0]}

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        m = (analysis.measures or {}).get("edge_hierarchy") or {}
        if m.get("tiers", 0) >= 3 and analysis.deficits.get("edge_hierarchy", 0) < 0.15:
            return False, "the edges already have three radius tiers"
        if cut_shell(analysis):
            return False, CUT_SHELL_WHY
        return analysis.deficits.get("edge_hierarchy", 0) > 0.1, "the edges already have a hierarchy"

    def apply(self, design, analysis, params):
        tiers = tuple(round(float(x), 3) for x in sorted(params.get("tiers") or self.params["tiers"]))
        return Patch(code=_call("fillet_hierarchy", design, tiers=tiers),
                     reason=f"Round the sharp edges in three tiers ({' / '.join(f'{t:g}' for t in tiers)} mm at most, "
                            "scaled to the part): large on the long edges, small on the details.",
                     params={"tiers": list(tiers)})


class EdgeBreak(_CadOp):
    name = "edge_break"
    targets = ("edge_hierarchy", "touch_points")
    cost = 0.5
    label = "Edge break"
    params = {"r": 0.3}

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        m = (analysis.measures or {}).get("edge_hierarchy") or {}
        sharp = m.get("sharp_fraction", 1.0)
        if sharp <= 0.05 and analysis.deficits.get("touch_points", 0) < 0.1:
            return False, "no sharp edges are left"
        # the break is for the edges the hierarchy left: after fillet_hierarchy, or on a design that already has
        # its own three radius tiers, or when only a few sharp edges remain. Run first, it would round every edge at
        # 0.3 mm and leave the hierarchy nothing to shape.
        if not (any(f.startswith("refine_fillet_hierarchy") for f in design.refined) or m.get("tiers", 0) >= 3
                or sharp <= 0.3 or cut_shell(analysis)):
            return False, "the fillet hierarchy comes first"
        return True, ""

    def apply(self, design, analysis, params):
        r = round(float(params.get("r", 0.3)), 3)
        return Patch(code=_call("edge_break", design, r=r),
                     reason=f"Break the sharp edges that are left with a {r:g} mm round so they catch light and do "
                            "not cut the hand.", params={"r": r})


class PartingLine(_CadOp):
    name = "parting_line"
    targets = ("surface_breaks", "interior_read", "detail_scales")
    cost = 0.75
    label = "Parting line"
    params = {"width": 0.5, "depth": 0.4}

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        if design.style == "organic":
            return False, "an organic form has no split line; a groove would read as a crack"
        sz = design.size()
        if sz is not None and sz[2] < 8:
            return False, "too thin for a parting line"
        return analysis.deficits.get("surface_breaks", 0) > 0.1 or analysis.deficits.get("interior_read", 0) > 0.3, \
            "the surfaces are already broken up"

    def apply(self, design, analysis, params):
        w = min(0.6, max(0.4, float(params.get("width", 0.5))))
        d = min(0.6, max(0.3, float(params.get("depth", 0.4))))
        return Patch(code=_call("parting_line", design, width=round(w, 3), depth=round(d, 3)),
                     reason=f"A {w:g} mm shadow line around the body on a split plane breaks the tall side surface "
                            "into two and reads as a parting line.", params={"width": w, "depth": d})


class Draft(_CadOp):
    name = "draft"
    targets = ("proportion",)
    cost = 0.5
    label = "Draft"
    params = {"angle": 1.5}
    WORDS = ("mould", "mold", "moulded", "molded", "injection", "cast", "casting", "draft")

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        if not _has(design, self.WORDS):
            return False, "draft is a moulding requirement and the brief names no moulding or casting"
        return True, ""

    def apply(self, design, analysis, params):
        a = round(float(params.get("angle", 1.5)), 3)
        return Patch(code=_call("draft", design, angle=a),
                     reason=f"A {a:g} degree draft on the vertical faces so the moulded part releases.",
                     params={"angle": a})


class KnurlZone(_CadOp):
    name = "knurl_zone"
    targets = ("detail_scales", "interior_read", "surface_breaks")
    cost = 1.5
    label = "Grip texture"
    params = {"pitch": 1.6, "depth": 0.5}
    WORDS = ("grip", "grips", "handle", "knob", "hand", "held", "handheld", "textured", "texture", "knurl", "knurled",
             "thumb", "twist", "dial")

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        from .analyze import GRIP
        if not (_has(design, self.WORDS) or GRIP.get(design.product_class or "")):
            return False, "no grip zone: the brief names no handle, knob or grip and the class has none"
        if any("knurl" in k or "textur" in k or "grip" in k or "flute" in k for k in design.features):
            return False, "the design already has a grip texture"
        return True, ""

    def apply(self, design, analysis, params):
        from .analyze import GRIP
        band = GRIP.get(design.product_class or "") or (0.2, 0.8)
        p, d = round(float(params.get("pitch", 1.6)), 3), round(float(params.get("depth", 0.5)), 3)
        return Patch(code=_call("knurl_zone", design, pitch=p, depth=d, band=tuple(band)),
                     reason=f"A knurled grip band ({p:g} mm pitch, {d:g} mm deep) where the hand holds the part.",
                     params={"pitch": p, "depth": d, "band": list(band)})


class RecessedPanel(_CadOp):
    name = "recessed_panel"
    targets = ("surface_breaks", "interior_read", "detail_scales")
    cost = 1.0
    label = "Recessed panel"
    params = {"depth": 0.6, "inset": 0.12}

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        share = ((analysis.measures or {}).get("surface_breaks") or {}).get("largest_share", 1.0)
        if share < 0.2:
            return False, "no flat face dominates the surface"
        return True, ""

    def apply(self, design, analysis, params):
        d, i = round(float(params.get("depth", 0.6)), 3), round(float(params.get("inset", 0.12)), 3)
        return Patch(code=_call("recessed_panel", design, depth=d, inset=i),
                     reason=f"A {d:g} mm recessed panel in the largest flat face, so it reads as a framed panel and "
                            "not as one slab.", params={"depth": d, "inset": i})


class ButtonPads(_CadOp):
    name = "button_pads"
    targets = ("detail_scales", "interior_read", "surface_breaks")
    cost = 1.0
    label = "Button pads"
    params = {"height": 0.6, "count": 3}
    WORDS = ("remote", "controller", "keypad", "button", "buttons", "console", "gamepad", "device", "panel")

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        if not _has(design, self.WORDS):
            return False, "the brief names no device with buttons"
        if any("button" in k or "key" in k for k in design.features):
            return False, "the design already has its buttons"
        return True, ""

    def apply(self, design, analysis, params):
        h, n = round(float(params.get("height", 0.6)), 3), int(params.get("count", 3))
        return Patch(code=_call("button_pads", design, height=h, count=n),
                     reason=f"{n} raised button pads ({h:g} mm) on the top face, in a row where the thumb reaches.",
                     params={"height": h, "count": n})


class RibLightening(_CadOp):
    name = "rib_lightening"
    targets = ("detail_scales", "interior_read")
    cost = 1.5
    label = "Ribbed lightening"
    params = {"pitch": 10.0, "t": 1.6, "skin": 1.6}

    def preconditions(self, design, analysis):
        ok, why = self._common(design, analysis)
        if not ok:
            return ok, why
        sz = design.size()
        if sz is not None and min(sz[0], sz[1]) < 30:
            return False, "too small a floor for a rib grid"
        # material comes out of the part: only where a strength or load check (the design's statics model) is there
        # to say it still holds; a wall-thickness gate alone does not show the part still carries its load
        if not design.has_check("statics."):
            return False, "no statics check on this design to show the lightened part still holds its load"
        return analysis.deficits.get("detail_scales", 0) > 0 or analysis.deficits.get("interior_read", 0) > 0.3, \
            "the design already reads at three scales"

    def apply(self, design, analysis, params):
        side = "top" if design.purpose == "print" else "bottom"     # a print pocket opens upward: no bridge
        p, t, s = (round(float(params.get(k, self.params[k])), 3) for k in ("pitch", "t", "skin"))
        return Patch(code=_call("rib_lightening", design, pitch=p, t=t, skin=s, side=side),
                     reason=f"Lighten the thick floor with a pocket and a {p:g} mm rib grid ({t:g} mm ribs), keeping a "
                            f"{s:g} mm skin; kept only when the checks still hold.",
                     params={"pitch": p, "t": t, "skin": s, "side": side})


OPERATORS = [FilletHierarchy(), EdgeBreak(), PartingLine(), Draft(), KnurlZone(), RecessedPanel(), ButtonPads(),
             RibLightening()]

__all__ = ["OPERATORS", "button_pads", "draft", "edge_break", "fillet_hierarchy", "knurl_zone", "parting_line",
           "recessed_panel", "rib_lightening", "sharp_edges", "tier_radii"]
