"""The wall a decorative finish may leave behind, and the measurement that enforces it.

A finish (flutes, grooves, knurls, grip textures, a parting line, a recessed panel, ribbed lightening) is there for
looks or feel. It must never thin a wall below what the part needs to print and hold: a 0.5 mm flute cut into a
1.3 mm corbel wall leaves 0.8 mm, two perimeters, under the load the corbel was added to carry. So:

  floor_for(purpose, nozzle, process)  the print minimum: for a print, max(2 x line width, the Thinnest-wall check's
                                       "fine" value of three nozzle widths); for a model, its process' minimum
                                       feature (none when no process is stated, as the Thinnest-feature check
                                       has none then); a game asset has none.
  current_floor()                      the floor of the build running now (Studio sends it with each kernel call,
                                       form/studio.py _k; 0, no guard, for a build outside Studio).
  cut_walls(before, after)             the thinnest wall left under the faces a step made (kernel side).

form/featureprog.py runs cut_walls after every feature whose role is decorative (GUARDED_ROLES) and leaves the
feature out, with the measured wall and where, when it goes under the floor. craft.finish_cut clamps each cut of a
texture to the wall it has instead. Pure Python here; cut_walls imports build123d only when it runs (in the worker).
"""
from __future__ import annotations

DEFAULT_FLOOR = 1.2          # mm: a 0.4 mm nozzle, the common case (three lines; two 0.45 mm lines are 0.9)
LINE_FACTOR = 1.125          # a slicer's default line width is about 1.125 x the nozzle (0.45 mm on a 0.4 mm nozzle)
GUARDED_ROLES = frozenset({"finish", "texture", "detail", "decor", "decoration", "grip", "trim", "accent", "refine"})
SAMPLES = 400                # rays per measured step (spread over the new faces by area, at least 3 per face)
MAX_FACES = 3000             # a step that made more new faces than this (a mesh texture) is not measured
TIME_BUDGET = 4.0            # seconds of sampling per measured step (then the descent, at most DESCENT_BUDGET more)
DESCENT_BUDGET = 2.0
THINNED = 0.02              # mm: a wall counts as thinned by the step when it lost more than this
REFINE_FACES = 6             # the faces with the thinnest samples get a local search for the true minimum


def line_width(nozzle: float) -> float:
    return round(LINE_FACTOR * float(nozzle), 4)


def floor_for(purpose: str | None = "print", nozzle: float | None = 0.4, process: str | None = "") -> float:
    """The thinnest wall a finish may leave, in mm."""
    p = (purpose or "print").lower()
    if p == "game":
        return 0.0
    if p == "model":
        from . import purpose as purpose_mod
        lim = (purpose_mod.PROCESSES.get(process or "") or {}).get("min_feature_mm")
        return float(lim) if lim else 0.0
    nz = float(nozzle or 0.4)
    return round(max(2 * line_width(nz), 3 * nz), 3)


def current_floor() -> float:
    """The floor of the build in progress (sent by Studio as `wall_floor` in the kernel call's context)."""
    try:
        from . import marks
        f = marks.context().get("wall_floor")
        return float(f) if f is not None else 0.0
    except Exception:
        return 0.0


def guarded(role: str | None) -> bool:
    return (role or "") in GUARDED_ROLES


def cut_walls(before, after, n: int = SAMPLES, ignore_below: float = 0.0) -> dict | None:
    """The thinnest wall of `after` under the faces it has that `before` did not (a cut's floor and sides, a
    groove's bottom), measured with the ray the Thinnest-wall check casts (form/analysis.py wall_hit), only where the
    step removed material (a rib or pad the step added is new material, not a thinned wall). {"t", "at", "to", "samples", "faces"}, or None when nothing new was found or nothing could be
    measured. Kernel side."""
    import numpy as np
    from build123d import Face, Vector
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    from . import analysis
    from .kernel import _Skin
    if before is None or after is None or not hasattr(after, "faces") or not hasattr(before, "faces"):
        return None
    try:
        faces = after.faces()
        if len(faces) > MAX_FACES or len(before.faces()) > MAX_FACES:
            return None
        skin = _Skin(before)
        from build123d import Vertex
        new = []
        for f in faces:
            if hash(f) in skin.ids:
                continue
            c = f.center()
            if skin.holds(f, (c.X, c.Y, c.Z), Vertex(c.X, c.Y, c.Z), 0.01):
                continue
            new.append(f)
        if not new or len(new) > MAX_FACES:
            return None
        import time
        deadline = time.monotonic() + TIME_BUDGET
        inter = analysis.intersector(after)
        inter_b = analysis.intersector(before)
        cls = BRepClass3d_SolidClassifier(before.wrapped)
        total = sum(f.area for f in new) or 1.0
        rng = np.random.default_rng(0)
        count = [0]

        def measure(f, p):
            """(wall, hit point) at surface point p of face f, or None (added material, nothing opposite, a wedge)."""
            try:
                nv = f.normal_at(Vector(*p))
            except Exception:
                return None
            nn = (nv.X, nv.Y, nv.Z)
            # a thinned wall: the step removed material in front of this point (just outside the new surface was
            # inside the solid before) and the material behind it was there already. A rib, a pad or a fused band is
            # new material, and the seam where it meets a curved skin is not a wall the step thinned.
            for d in (-0.05, 0.02):
                cls.Perform(gp_Pnt(p[0] + nn[0] * d, p[1] + nn[1] * d, p[2] + nn[2] * d), 1e-6)
                if cls.State() != TopAbs_IN:
                    return None
            hit = analysis.wall_hit(inter, p, nn, want_face=True)
            if hit is None:
                return None
            # a thinned wall has the step's new surface on one side and the wall that was already there on the
            # other: a ray that meets another face this step made (a seam where a band feathers into a skin, faces
            # meeting at a shallow angle) or a face sharing an edge with this one measures a wedge, not a wall
            hf = Face(hit[2])
            if edges_of(f) & edges_of(hf):
                return None
            # and the step thinned it: the wall along the same line in the solid before was thicker (a seam or a
            # sliver that was already there, on a skin the step re-made, is not this step's doing)
            was = _wall_before(inter_b, p, nn)
            if was is not None and was <= hit[0] + THINNED:
                return None
            count[0] += 1
            return None if hit[0] <= ignore_below else (hit[0], hit[1])

        _edges: dict = {}

        def edges_of(face):
            k = _key(face)
            if k not in _edges:
                _edges[k] = {_key(e) for e in face.edges()}
            return _edges[k]

        per_face = []                                  # (wall, face, point, hit point): each face's thinnest sample
        for f in new:
            if time.monotonic() > deadline:            # a guard has a time budget: a large B-spline skin is slow
                break
            k = max(16, int(round(n * f.area / total)))
            try:
                verts, tris = f.tessellate(0.05, 0.3)
            except Exception:
                continue
            if not tris:
                continue
            P = np.array([[v.X, v.Y, v.Z] for v in verts], dtype=np.float64)
            T = np.array(tris, dtype=np.int64)
            a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
            areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
            if areas.sum() <= 0:
                continue
            pick = rng.choice(len(T), size=k, p=areas / areas.sum())
            u, w = rng.random(k), rng.random(k)
            flip = u + w > 1
            u[flip], w[flip] = 1 - u[flip], 1 - w[flip]
            pts = a[pick] + (b[pick] - a[pick]) * u[:, None] + (c[pick] - a[pick]) * w[:, None]
            fb = None
            for p in pts:
                h = measure(f, p)
                if h is not None and (fb is None or h[0] < fb[0]):
                    fb = (h[0], f, tuple(float(x) for x in p), h[1])
            if fb is not None:
                per_face.append(fb)
        if not per_face:
            return None
        # random points only come near a groove's thinnest line (its bottom): walk each of the thinnest faces' best
        # sample downhill on the surface (its u, v) until the step is a few microns
        per_face.sort(key=lambda x: x[0])
        best = per_face[0]
        for fb in per_face[:REFINE_FACES]:
            if time.monotonic() > deadline + DESCENT_BUDGET:
                break
            r = _descend(fb, measure)
            if r[0] < best[0]:
                best = r
        return {"t": float(best[0]), "at": [round(float(x), 3) for x in best[2]],
                "to": [round(float(x), 3) for x in best[3]], "samples": count[0], "faces": len(new)}
    except Exception:                                 # a measurement is a guard, never a build failure of its own
        return None


def _key(shape) -> tuple:
    """A shape's identity by geometry (centre and size): the same face or edge reached through an intersector and
    through faces() can carry a different orientation or location, so its hash differs."""
    c = shape.center()
    size = shape.area if hasattr(shape, "area") and shape.area else getattr(shape, "length", 0.0)
    return (round(c.X, 3), round(c.Y, 3), round(c.Z, 3), round(float(size or 0.0), 3))


def _wall_before(inter_b, p, n, reach: float = 6.0):
    """The wall the solid before the step had along the line through p (normal n): entering from outside within
    `reach` of p, to where that material ends. None when the line meets nothing."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    o = (p[0] + n[0] * reach, p[1] + n[1] * reach, p[2] + n[2] * reach)
    inter_b.Perform(gp_Lin(gp_Pnt(*o), gp_Dir(-n[0], -n[1], -n[2])), 0.0, 1e4)
    ws = sorted(inter_b.WParameter(j) for j in range(1, inter_b.NbPnt() + 1))
    ws = [w for i, w in enumerate(ws) if i == 0 or w - ws[i - 1] > 1e-6]
    if len(ws) < 2:
        return None
    return ws[1] - ws[0]


def _descend(fb, measure, rounds: int = 40):
    """Local search on the face's (u, v) from a sample (wall, face, point, hit): the thinnest wall near it."""
    t0, f, p0, q0 = fb
    try:
        from OCP.BRep import BRep_Tool
        from OCP.BRepClass import BRepClass_FaceClassifier
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        from OCP.TopAbs import TopAbs_IN
        from OCP.gp import gp_Pnt, gp_Pnt2d
        surf = BRep_Tool.Surface_s(f.wrapped)
        uv = ShapeAnalysis_Surface(surf).ValueOfUV(gp_Pnt(*p0), 1e-7)
        fw = f.wrapped
        u0, u1, v0, v1 = f._uv_bounds()
    except Exception:
        return fb

    class _Trim:
        @staticmethod
        def Perform(p2):
            return BRepClass_FaceClassifier(fw, p2, 1e-7).State()
    trim = _Trim()
    u, v = uv.X(), uv.Y()
    du, dv = 0.05 * (u1 - u0), 0.05 * (v1 - v0)
    best = fb
    for _ in range(rounds):
        moved = False
        for su, sv in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            uu, vv = u + su * du, v + sv * dv
            if trim.Perform(gp_Pnt2d(uu, vv)) != TopAbs_IN:
                continue
            pt = surf.Value(uu, vv)
            p = (pt.X(), pt.Y(), pt.Z())
            h = measure(f, p)
            if h is not None and h[0] < best[0] - 1e-9:
                best, u, v, moved = (h[0], f, p, h[1]), uu, vv, True
        if not moved:
            du, dv = du / 2, dv / 2
            if du < 1e-6 * max(1.0, abs(u1 - u0)) and dv < 1e-6 * max(1.0, abs(v1 - v0)):
                break
    return best


def where(pt) -> str:
    return "(" + ", ".join(f"{float(x):.1f}" for x in pt) + ")"
