"""Layer 1, step two: one trimmed face per region, on its analytic surface, sewn into a solid. Kernel worker only.

Each region of `segment` becomes one face. Its surface is the fitted plane, cylinder, cone, sphere or torus (a frozen
facet keeps the plane of its triangles). Its boundary is where it meets the neighbouring regions, followed along the
mesh edges, so neighbouring faces share the same edges:

- a boundary between two fitted surfaces that is straight becomes one line, one that lies on a circle becomes that
  circle or an arc of it (holes, bosses, turned parts), anything else a chain of straight segments;
- a boundary with a frozen facet stays the facet's own straight edges, so the facet keeps its exact shape.

The vertices of every boundary are the mesh's own vertices, so the result can be compared with the mesh directly.
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
    def __init__(self, V, F, regions: list[Region], tol: float):
        self.V, self.F, self.regions, self.tol = V, F, regions, tol
        self.size = float(np.ptp(V, axis=0).max()) or 1.0
        self.tri_region = np.empty(len(F), dtype=np.int64)
        for r in regions:
            self.tri_region[r.tris] = r.id
        self._vtx = {}
        self._chains = {}
        self.stats = {"edges_line": 0, "edges_circle": 0, "edges_arc": 0, "edges_segment": 0}

    def vertex(self, i):
        v = self._vtx.get(i)
        if v is None:
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
            from OCP.gp import gp_Pnt
            v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, self.V[i]))).Vertex()
            self._vtx[i] = v
        return v

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
        P = self.V[vs]
        both = self.regions[r].parametric and self.regions[q].parametric
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
        o, a = gp_Pnt(*map(float, p["o"])), gp_Dir(*map(float, p["a"]))
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


def build(V, F, regions: list[Region], tol: float, progress=None):
    """A solid with one face per region. Returns (TopoDS_Shape or None, info)."""
    from .solid import check, shape_from_faces, unify
    t0 = time.perf_counter()
    b = Builder(V, F, regions, tol)
    loops = _loops(F, b.tri_region)
    faces, failed = [], []
    for i, reg in enumerate(regions):
        if progress and i % 50 == 0:
            progress({"stage": "layer1", "text": f"Faces {i:,} of {len(regions):,}", "fraction": 0.5 + 0.3 * i / max(len(regions), 1)})
        try:
            faces.append(b.face(reg, loops.get(reg.id, [])))
        except Exception as e:                     # noqa: BLE001  (OCCT raises many kinds)
            failed.append({"region": reg.id, "kind": reg.kind, "error": f"{type(e).__name__}: {e}"[:200]})
    info = {"faces_built": len(faces), "face_failures": failed, **b.stats}
    if failed:
        return None, info
    shape, si = shape_from_faces(faces, tol=max(1e-6, 1e-6 * b.size), progress=progress, stage="layer1", base=0.85)
    info.update(si)
    if not si["solid"]:
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
