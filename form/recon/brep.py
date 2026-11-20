"""Layer 1, step two: one trimmed face per region, on its analytic surface, sewn into a solid. Kernel worker only.

Each region of `segment` becomes one face. Its surface is the fitted plane, cylinder, cone, sphere or torus (a frozen
facet keeps the plane of its triangles). Its boundary is where it meets the neighbouring regions, followed along the
mesh edges, so neighbouring faces share the same edges:

- a boundary between two fitted surfaces is their exact intersection curve (plane-plane a line, plane-cylinder a
  circle, an ellipse or a line, any other pair the curve OCCT's surface intersection gives), trimmed at the corners,
  when that curve passes within the tolerance of the mesh's boundary; otherwise a line or circle through the mesh's
  boundary points, else a chain of straight segments;
- a corner where only fitted surfaces meet is moved onto all of them (the point nearest every surface, found by
  Gauss-Newton from the mesh vertex), so the edges meeting there end exactly where the surfaces cross;
- a boundary with a frozen facet stays the facet's own straight edges, so the facet keeps its exact shape (its
  corners stay the mesh's own vertices).
"""
from __future__ import annotations

import math
import time

import numpy as np

from .segment import Region


def _loops(F, tri_region):
    """Boundary loops of each region: {region: [[(a, b, neighbour_region), ...], ...]} in triangle winding order."""
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    tri = np.tile(np.arange(len(F)), 3)
    twin = {}
    for i, (a, b) in enumerate(he.tolist()):
        twin[(a, b)] = i
    out = {}
    nxt = {}
    for i, (a, b) in enumerate(he.tolist()):
        j = twin.get((b, a))
        if j is None:
            raise ValueError("The mesh is not closed; Layer 1 needs a closed, manifold mesh.")
        r, q = int(tri_region[tri[i]]), int(tri_region[tri[j]])
        if r != q:
            nxt.setdefault(r, {}).setdefault(a, []).append((a, b, q))
    for r, starts in nxt.items():
        loops = []
        while any(starts.values()):
            a0 = next(k for k, v in starts.items() if v)
            loop = []
            a = a0
            while True:
                lst = starts.get(a)
                if not lst:
                    break
                h = lst.pop(0)
                loop.append(h)
                a = h[1]
                if a == a0:
                    break
            loops.append(loop)
        out[r] = loops
    return out


def _runs(loop):
    """Split a loop into runs along one neighbour. A loop along a single neighbour is one closed run that starts at
    its smallest vertex, so both regions that share it start in the same place."""
    nb = [h[2] for h in loop]
    k = len(loop)
    corners = [i for i in range(k) if nb[i] != nb[i - 1]]
    if not corners:
        verts = [h[0] for h in loop]
        s = int(np.argmin(verts))
        return [(nb[0], verts[s:] + verts[:s] + [verts[s]], True)]
    s = corners[0]
    loop = loop[s:] + loop[:s]
    runs, cur = [], [loop[0]]
    for h in loop[1:]:
        if h[2] == cur[-1][2]:
            cur.append(h)
        else:
            runs.append(cur)
            cur = [h]
    runs.append(cur)
    return [(run[0][2], [h[0] for h in run] + [run[-1][1]], False) for run in runs]


def _circle(P):
    """Plane and circle through 3-D points: (centre, normal, radius, max deviation)."""
    m = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - m, full_matrices=False)
    n, u, v = vt[2], vt[0], vt[1]
    x, y = (P - m) @ u, (P - m) @ v
    A = np.c_[2 * x, 2 * y, np.ones_like(x)]
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    r = math.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 0.0))
    c = m + sol[0] * u + sol[1] * v
    d = P - c
    off = d @ n
    dev = np.hypot(np.linalg.norm(d - off[:, None] * n, axis=1) - r, off)
    return c, n, r, float(dev.max())


class Builder:
    def __init__(self, V, F, regions: list[Region], tol: float, exact: bool = True):
        self.V, self.F, self.regions, self.tol = V, F, regions, tol
        self.exact = exact and EXACT_EDGES
        self.size = float(np.ptp(V, axis=0).max()) or 1.0
        self.tri_region = np.empty(len(F), dtype=np.int64)
        for r in regions:
            self.tri_region[r.tris] = r.id
        self._vtx = {}
        self._pos = {}
        self._chains = {}
        self._surf = {}
        self.stats = {"edges_line": 0, "edges_circle": 0, "edges_arc": 0, "edges_curve": 0, "edges_segment": 0,
                      "edges_exact": 0, "corners_moved": 0}
        # the regions round each vertex (to put a corner where its surfaces cross)
        vr = np.c_[self.F.ravel(), np.repeat(self.tri_region, 3)]
        vr = np.unique(vr, axis=0)
        self._vreg = {}
        for vi, ri in vr.tolist():
            self._vreg.setdefault(vi, []).append(ri)

    def position(self, i):
        """Where mesh vertex i goes: onto every fitted surface round it when only fitted surfaces meet there."""
        p = self._pos.get(i)
        if not self.exact:
            return self.V[i]
        if p is not None:
            return p
        p = self.V[i]
        regs = [self.regions[r] for r in self._vreg.get(i, [])]
        if len(regs) >= 2 and all(r.parametric and r.kind != "bspline" and r.prim is not None and
                                  (EXACT_CURVED or r.kind == "plane") for r in regs):
            q = p.copy()
            for _ in range(8):
                J = np.array([r.prim.normal(q[None])[0] for r in regs])
                f = np.array([float(r.prim.dist(q[None])[0]) for r in regs])
                # least squares step, damped toward the mesh vertex (an under-determined corner keeps its place)
                A = J.T @ J + 1e-6 * np.eye(3)
                step = np.linalg.solve(A, -J.T @ f)
                q = q + step
                if np.linalg.norm(step) < 1e-10 * self.size:
                    break
            res = max(abs(float(r.prim.dist(q[None])[0])) for r in regs)
            if res < 1e-7 * self.size + 1e-9 and np.linalg.norm(q - p) <= self.tol:
                if np.linalg.norm(q - p) > 1e-9:
                    self.stats["corners_moved"] += 1
                p = q
        self._pos[i] = p
        return p

    def vertex(self, i):
        v = self._vtx.get(i)
        if v is None:
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
            from OCP.gp import gp_Pnt
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, self.position(i)))).Vertex()
            self._vtx[i] = v
        return v

    def _geom(self, rid):
        g = self._surf.get(rid)
        if g is None:
            g = self.surface(self.regions[rid])
            self._surf[rid] = g
        return g

    def _exact(self, r, q, vs, closed):
        """The edge along the intersection of regions r and q's surfaces, trimmed at the run's corners, when it passes
        within the tolerance of the run's mesh points. None otherwise."""
        from OCP.BRep import BRep_Tool
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.GeomAdaptor import GeomAdaptor_Curve
        from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Ellipse, GeomAbs_Line
        from OCP.GeomAPI import GeomAPI_IntSS, GeomAPI_ProjectPointOnCurve
        from OCP.gp import gp_Pnt
        kinds = {self.regions[k].kind for k in (r, q)}
        if "bspline" in kinds or "facet" in kinds or (not EXACT_CURVED and kinds != {"plane"}):
            return None
        P = self.V[vs]
        if not closed:
            P = np.vstack([self.position(vs[0]), P[1:-1], self.position(vs[-1])])
        try:
            inter = GeomAPI_IntSS(self._geom(r), self._geom(q), 1e-7)
        except Exception:                              # noqa: BLE001
            return None
        if not inter.IsDone() or inter.NbLines() == 0:
            return None
        pick = P[np.linspace(0, len(P) - 1, min(len(P), 24)).astype(int)]
        best = None
        for k in range(1, inter.NbLines() + 1):
            c = inter.Line(k)
            dmax, prm = 0.0, []
            for x in pick:
                pr = GeomAPI_ProjectPointOnCurve(gp_Pnt(*map(float, x)), c)
                if pr.NbPoints() == 0:
                    dmax = np.inf
                    break
                dmax = max(dmax, pr.LowerDistance())
                prm.append(pr.LowerDistanceParameter())
            if best is None or dmax < best[0]:
                best = (dmax, c, prm)
        dmax, c, prm = best
        if dmax > self.tol:
            return None
        ad = GeomAdaptor_Curve(c)
        kind = ad.GetType()
        try:
            if closed:
                if not ad.IsClosed() and not ad.IsPeriodic():
                    return None
                e = BRepBuilderAPI_MakeEdge(c).Edge()
                stat = "edges_circle" if kind == GeomAbs_Circle else "edges_curve"
            else:
                u0, u1 = prm[0], prm[-1]
                if ad.IsPeriodic():
                    T = ad.Period()
                    um = prm[len(prm) // 2]
                    # go from u0 to u1 the way that passes the middle of the run
                    a1 = (u1 - u0) % T
                    am = (um - u0) % T
                    u1 = u0 + a1 if am <= a1 else u0 + a1 - T
                    if u1 < u0:
                        u0, u1 = u1, u0
                        v0, v1 = self.vertex(vs[-1]), self.vertex(vs[0])
                        flip = True
                    else:
                        v0, v1 = self.vertex(vs[0]), self.vertex(vs[-1])
                        flip = False
                else:
                    flip = u1 < u0
                    if flip:
                        u0, u1 = u1, u0
                    v0, v1 = (self.vertex(vs[-1]), self.vertex(vs[0])) if flip else (self.vertex(vs[0]), self.vertex(vs[-1]))
                if abs(u1 - u0) < 1e-12:
                    return None
                mk = BRepBuilderAPI_MakeEdge(c, v0, v1, u0, u1)
                if not mk.IsDone():
                    return None
                e = mk.Edge()
                if flip:
                    e = e.Reversed()
                stat = {GeomAbs_Line: "edges_line", GeomAbs_Circle: "edges_arc"}.get(kind, "edges_curve")
                del BRep_Tool
        except Exception:                              # noqa: BLE001
            return None
        self.stats[stat] += 1
        self.stats["edges_exact"] += 1
        del GeomAbs_Ellipse
        return [e]

    def _segments(self, vs):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        out = []
        for a, b in zip(vs, vs[1:]):
            out.append(BRepBuilderAPI_MakeEdge(self.vertex(a), self.vertex(b)).Edge())
            self.stats["edges_segment"] += 1
        return out

    def _make_chain(self, r, q, vs, closed):
        """Edges along a run of vertices vs (in region r's direction)."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.GC import GC_MakeArcOfCircle
        from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
        P = np.array([self.position(v) for v in vs])
        both = all(self.regions[k].parametric and self.regions[k].kind != "bspline" for k in (r, q))
        if both and self.exact:
            got = self._exact(r, q, vs, closed)
            if got is not None:
                return got
        if not both or len(vs) == 2:
            return self._segments(vs)
        a, b = P[0], P[-1]
        if not closed:
            d = b - a
            L = np.linalg.norm(d)
            if L > 0:
                off = np.linalg.norm(np.cross(P - a, d / L), axis=1).max()
                if off <= 1e-6 * self.size:
                    self.stats["edges_line"] += 1
                    return [BRepBuilderAPI_MakeEdge(self.vertex(vs[0]), self.vertex(vs[-1])).Edge()]
        if len(vs) >= 4:
            c, n, rad, dev = _circle(P[:-1] if closed else P)
            if dev <= min(0.25 * self.tol, 0.01 * rad) and rad < 10 * self.size:
                if closed:
                    # orient the circle the way the run goes
                    t = np.cross(P[1] - c, P[2] - c)
                    if t @ n < 0:
                        n = -n
                    x = P[0] - c
                    x = x - (x @ n) * n
                    circ = gp_Circ(gp_Ax2(gp_Pnt(*c), gp_Dir(*n), gp_Dir(*(x / np.linalg.norm(x)))), rad)
                    e = BRepBuilderAPI_MakeEdge(circ).Edge()     # a closed run touches no other edge
                    self.stats["edges_circle"] += 1
                    return [e]
                mid = P[len(P) // 2]
                arc = GC_MakeArcOfCircle(gp_Pnt(*a), gp_Pnt(*mid), gp_Pnt(*b))
                if arc.IsDone():
                    self.stats["edges_arc"] += 1
                    return [BRepBuilderAPI_MakeEdge(arc.Value(), self.vertex(vs[0]), self.vertex(vs[-1])).Edge()]
        return self._segments(vs)

    def chain(self, r, q, vs, closed):
        """The edges of a run, made once and shared: the second region to ask gets them reversed."""
        key = (min(r, q), max(r, q), frozenset(vs))
        got = self._chains.get(key)
        if got is None:
            edges = self._make_chain(r, q, vs, closed)
            self._chains[key] = (r, edges)
            return edges
        owner, edges = got
        if owner == r:
            return edges
        return [e.Reversed() for e in reversed(edges)]

    def surface(self, reg: Region):
        from OCP.Geom import (Geom_ConicalSurface, Geom_CylindricalSurface, Geom_Plane, Geom_SphericalSurface,
                              Geom_ToroidalSurface)
        from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt
        from . import fit as fitmod
        pr = reg.prim
        if reg.kind == "facet" or pr is None:
            vid = np.unique(self.F[reg.tris])
            n = np.cross(self.V[self.F[reg.tris[0], 1]] - self.V[self.F[reg.tris[0], 0]],
                         self.V[self.F[reg.tris[0], 2]] - self.V[self.F[reg.tris[0], 0]])
            pr = fitmod.Prim("plane", {"o": self.V[vid].mean(axis=0), "a": n / np.linalg.norm(n)})
        p = pr.p
        if pr.kind == "bspline":
            if "_geom" not in pr.p:
                pr.p["_geom"] = pr.surface()
            return pr.p["_geom"]
        o, a = gp_Pnt(*map(float, p["o"])), gp_Dir(*map(float, p.get("a", (0.0, 0.0, 1.0))))   # a sphere has no axis
        x = reg.info.get("xdir")
        if x is not None and pr.kind != "plane":                 # the seam where the face has no material
            ax = gp_Ax3(o, a, gp_Dir(*map(float, x)))
        else:
            ax = gp_Ax3(o, a)
        k = pr.kind
        if k == "plane":
            return Geom_Plane(ax)
        if k == "cylinder":
            return Geom_CylindricalSurface(ax, float(p["r"]))
        if k == "cone":
            ang, r0 = float(p["half_angle"]), float(p["r"])
            if r0 < 0:
                raise ValueError("cone reference radius below zero")
            return Geom_ConicalSurface(ax, ang, r0)
        if k == "sphere":
            return Geom_SphericalSurface(gp_Ax3(o, gp_Dir(0, 0, 1)), float(p["r"]))
        if k == "torus":
            return Geom_ToroidalSurface(ax, float(p["R"]), float(p["r"]))
        raise ValueError(k)

    def _agrees(self, surf, reg: Region) -> bool:
        """Does the surface's own normal point the same way as the region's triangles (outward)?"""
        from OCP.gp import gp_Pnt, gp_Vec
        from OCP.ShapeAnalysis import ShapeAnalysis_Surface
        V, F = self.V, self.F
        t = reg.tris
        a, b, c = V[F[t, 0]], V[F[t, 1]], V[F[t, 2]]
        n = np.cross(b - a, c - a)
        k = int(np.argmax(np.linalg.norm(n, axis=1)))
        cen = (a[k] + b[k] + c[k]) / 3
        sas = ShapeAnalysis_Surface(surf)
        uv = sas.ValueOfUV(gp_Pnt(*cen), 1e-7)
        P, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        surf.D1(uv.X(), uv.Y(), P, du, dv)
        sn = du.Crossed(dv)
        return float(sn.X() * n[k, 0] + sn.Y() * n[k, 1] + sn.Z() * n[k, 2]) > 0

    def face(self, reg: Region, loops):
        from OCP.BRep import BRep_Builder
        from OCP.ShapeFix import ShapeFix_Face
        from OCP.TopoDS import TopoDS_Face, TopoDS_Wire
        surf = self.surface(reg)
        agree = self._agrees(surf, reg)
        bb = BRep_Builder()
        f = TopoDS_Face()
        bb.MakeFace(f, surf, 1e-7)
        for loop in loops:
            edges = []
            for q, vs, closed in _runs(loop):
                edges += self.chain(reg.id, q, vs, closed)
            if not agree:
                edges = [e.Reversed() for e in reversed(edges)]
            w = TopoDS_Wire()
            bb.MakeWire(w)
            for e in edges:
                bb.Add(w, e)
            bb.Add(f, w)
        fix = ShapeFix_Face(f)
        fix.SetPrecision(1e-7)
        fix.SetMaxTolerance(max(self.tol, 1e-4))
        fix.Perform()
        f = fix.Face()
        return f if agree else f.Reversed()


PERIODIC = ("cylinder", "cone", "torus")
EXACT_EDGES = True         # boundaries between two fitted surfaces follow their intersection curve (else the mesh)
EXACT_CURVED = False       # ... also between curved surfaces (off: the feature tree reads turned bases less well)


def _circles_only(V, loops, tol) -> bool:
    """Every boundary loop is one closed run on a circle (a plain hole or boss): a seam across it is harmless."""
    for loop in loops:
        runs = _runs(loop)
        if len(runs) != 1 or not runs[0][2] or len(runs[0][1]) < 5:
            return False
        _, _, rad, dev = _circle(V[runs[0][1][:-1]])
        if dev > min(0.25 * tol, 0.01 * rad):
            return False
    return True


def _seam_between_loops(V, loops, o, u, w, tol):
    """For a face that goes all the way round: True if its default seam is harmless (every boundary is a circle round
    the axis), an angle for the seam that misses every other boundary (holes through the face), or None if there is
    no such angle (a boundary that goes round the axis without being a circle)."""
    spans = []
    for loop in loops:
        vs = [h[0] for h in loop]
        P = V[vs] - o
        ang = np.sort(np.arctan2(P @ w, P @ u))
        gaps = np.diff(np.r_[ang, ang[0] + 2 * np.pi])
        k = int(np.argmax(gaps))
        if gaps[k] < math.radians(30):                   # goes round the axis: must be one closed circle
            if not _circles_only(V, [loop], tol):
                return None
            continue
        spans.append((ang[(k + 1) % len(ang)], ang[k]))  # from the end of the gap round to its start
    if not spans:
        return True
    # free angles: not inside any span
    test = np.linspace(-np.pi, np.pi, 720, endpoint=False)
    free = np.ones(len(test), dtype=bool)
    for a0, a1 in spans:
        rel = (test - a0) % (2 * np.pi)
        free &= rel > ((a1 - a0) % (2 * np.pi)) + math.radians(2)
        free &= rel < 2 * np.pi - math.radians(2)
    if not free.any():
        return None
    # the middle of the longest run of free angles
    idx = np.flatnonzero(free)
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == len(test) - 1:
        runs = [np.r_[runs[-1], runs[0] + len(test)]] + runs[1:-1]
    best = max(runs, key=len)
    return float(test[best[len(best) // 2] % len(test)])


def split_periodic(V, F, regions: list[Region], loops=None, tol=0.02, turn=0.0):
    """Faces on periodic surfaces (cylinder, cone, torus) get their seam where they have no material, so no boundary
    crosses it. A region that goes all the way round has no such place: it is split in two halves, each with its
    seam in the middle of the other half. Returns (regions, origin) with origin[i] the input region of region i."""
    out, origin = [], []
    for r in regions:
        if r.kind not in PERIODIC or r.prim is None:
            out.append(r)
            origin.append(r.id)
            continue
        o, a = r.prim.p["o"], r.prim.p["a"]
        t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        u = np.cross(a, t)
        u /= np.linalg.norm(u)
        w = np.cross(a, u)
        P = V[np.unique(F[r.tris])] - o
        ang = np.sort(np.arctan2(P @ w, P @ u))
        gaps = np.diff(np.r_[ang, ang[0] + 2 * np.pi])
        k = int(np.argmax(gaps))
        if gaps[k] > math.radians(30):
            mid = ang[k] + 0.5 * gaps[k]
            r.info["xdir"] = math.cos(mid) * u + math.sin(mid) * w
            out.append(r)
            origin.append(r.id)
            continue
        if loops is not None:
            seam = _seam_between_loops(V, loops.get(r.id, []), o, u, w, tol)
            if seam is not None:
                if seam is not True:
                    r.info["xdir"] = math.cos(seam) * u + math.sin(seam) * w
                out.append(r)
                origin.append(r.id)
                continue
        C = V[F[r.tris]].mean(axis=1) - o
        th = (np.arctan2(C @ w, C @ u) - turn + np.pi) % (2 * np.pi) - np.pi
        halves = [r.tris[th >= 0], r.tris[th < 0]]
        if min(len(h) for h in halves) < 2:
            out.append(r)
            origin.append(r.id)
            continue
        _, A = _areas(V, F)
        sw = math.cos(turn + np.pi / 2) * u + math.sin(turn + np.pi / 2) * w
        for h, seam in zip(halves, (-sw, sw)):
            q = Region(0, r.kind, h, r.prim, float(A[h].sum()), {"xdir": seam, "half_of": r.id})
            out.append(q)
            origin.append(r.id)
    for i, r in enumerate(out):
        if r is regions[origin[i]] and r.id != i:
            r = Region(i, r.kind, r.tris, r.prim, r.area, dict(r.info))
            out[i] = r
        r.id = i
    return out, origin


def _areas(V, F):
    from .mesh import tri_normals
    return tri_normals(V, F)


def _free_edge_regions(sew, V, F, tri_region, regions, origin):
    """Input regions next to the edges sewing could not join (matched by the mesh vertices at the edge's ends)."""
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp
    from scipy.spatial import cKDTree
    tree = cKDTree(V)
    out = set()
    for i in range(1, sew.NbFreeEdges() + 1):
        e = sew.FreeEdge(i)
        for vx in (TopExp.FirstVertex_s(e), TopExp.LastVertex_s(e)):
            p = BRep_Tool.Pnt_s(vx)
            _, vi = tree.query([p.X(), p.Y(), p.Z()])
            for t in np.flatnonzero((F == vi).any(axis=1)).tolist():
                r = regions[int(tri_region[t])]
                if r.parametric:
                    out.add(origin[r.id])
    return sorted(out)


def build(V, F, regions: list[Region], tol: float, progress=None):
    """A solid with one face per region. Returns (TopoDS_Shape or None, info). Region ids in the info are those of
    the input list (a region split for its seam is reported as itself)."""
    lab = np.empty(len(F), dtype=np.int64)
    for r in regions:
        lab[r.tris] = r.id
    rloops = _loops(F, lab)
    tries = [(rloops, 0.0), (rloops, np.pi / 2), (None, 0.0)]    # seams between holes; halves split two ways
    for exact in ((True, False) if EXACT_EDGES else (False,)):
        for k, (lp, turn) in enumerate(tries):
            shape, info = _build(V, F, [_copy(r) for r in regions], tol, progress, lp, turn, exact)
            info["seam_strategy"] = k
            if shape is not None or info.get("face_failures"):
                break
        info["exact_edges"] = exact
        if shape is not None and info.get("valid"):
            break
        if exact:                                       # exact edges that do not close into a valid solid: the mesh's
            info_exact = {k: info.get(k) for k in ("valid", "free_edges", "faces")}    # own boundaries instead
    if shape is not None and not info.get("exact_edges") and EXACT_EDGES:
        info["exact_edges_failed"] = info_exact
    return shape, info


def _copy(r):
    return Region(r.id, r.kind, r.tris, r.prim, r.area, dict(r.info))


def _build(V, F, regions, tol, progress, rloops, turn, exact=True):
    from .solid import check, shape_from_faces, unify
    t0 = time.perf_counter()
    regions, origin = split_periodic(V, F, regions, rloops, tol, turn)
    b = Builder(V, F, regions, tol, exact)
    loops = _loops(F, b.tri_region)
    faces, failed = [], []
    for i, reg in enumerate(regions):
        if progress and i % 50 == 0:
            progress({"stage": "layer1", "text": f"Faces {i:,} of {len(regions):,}", "fraction": 0.5 + 0.3 * i / max(len(regions), 1)})
        try:
            faces.append(b.face(reg, loops.get(reg.id, [])))
        except Exception as e:                     # noqa: BLE001  (OCCT raises many kinds)
            failed.append({"region": origin[reg.id], "kind": reg.kind, "error": f"{type(e).__name__}: {e}"[:200]})
    info = {"faces_built": len(faces), "face_failures": failed, "split_for_seam": len(regions) - len(set(origin)), **b.stats}
    if failed:
        return None, info
    sew_out = {}
    shape, si = shape_from_faces(faces, tol=max(1e-6, 1e-6 * b.size), progress=progress, stage="layer1", base=0.85,
                                 keep=sew_out)
    info.update(si)
    if not si["solid"]:
        if si.get("free_edges") and "sew" in sew_out:
            info["free_edge_regions"] = _free_edge_regions(sew_out["sew"], V, F, b.tri_region, regions, origin)
        return None, info
    ck = check(shape)
    if ck["valid"]:
        merged = unify(shape, linear_tol=1e-6 * b.size, angular_tol=1e-6)
        ck2 = check(merged)
        if ck2["valid"] and ck2["solids"] == ck["solids"]:
            shape, ck = merged, ck2
    info.update(ck)
    info["seconds"] = round(time.perf_counter() - t0, 2)
    return shape, info


def bad_regions(shape, regions: list[Region], V, F) -> list[int]:
    """Regions whose faces the checker rejects (matched by the face nearest each region's largest triangle)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    bad = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = ex.Current()
        if not BRepCheck_Analyzer(f).IsValid():
            bad.append(f)
        ex.Next()
    out = set()
    for f in bad:
        for r in regions:
            if not r.parametric:
                continue
            t = r.tris[0]
            c = V[F[t]].mean(axis=0)
            d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*c)).Vertex(), f)
            if d.IsDone() and d.Value() < 1e-3:
                out.add(r.id)
    return sorted(out)
