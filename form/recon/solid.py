"""Layer 0: the mesh as an exact B-rep solid. Kernel worker only (imports OCCT).

One planar face per triangle, sewn (BRepBuilderAPI_Sewing), made a solid and checked (ShapeFix_Solid), then coplanar
neighbours merged into one face each (ShapeUpgrade_UnifySameDomain). Every surface of the result is a plane through
triangles of the input, so it is the mesh, exactly, as a solid a CAD program can open. It is not parametric: a round
hole is still a ring of flat facets.
"""
from __future__ import annotations

import time

import numpy as np


def _faces_from_triangles(V, F, progress=None):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pnt
    pts = [gp_Pnt(*map(float, p)) for p in V]
    out, skipped = [], 0
    n = len(F)
    step = max(1, n // 20)
    for i, (a, b, c) in enumerate(F):
        if progress and i % step == 0:
            progress({"stage": "layer0", "text": f"Facets {i:,} of {n:,}", "fraction": i / n * 0.4})
        poly = BRepBuilderAPI_MakePolygon(pts[a], pts[b], pts[c], True)
        if poly.IsDone():
            f = BRepBuilderAPI_MakeFace(poly.Wire(), True)
            if f.IsDone():
                out.append(f.Face())
                continue
        skipped += 1
    return out, skipped


def shape_from_faces(faces, tol, progress=None, stage="layer0", base=0.4, keep=None):
    """Sew faces and close them into a solid. Returns (TopoDS_Shape, info)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRep import BRep_Builder
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    sew = BRepBuilderAPI_Sewing(tol)
    for f in faces:
        sew.Add(f)
    if progress:
        progress({"stage": stage, "text": f"Sewing {len(faces):,} faces", "fraction": base})
    sew.Perform()
    if keep is not None:
        keep["sew"] = sew
    sewn = sew.SewedShape()
    info = {"free_edges": sew.NbFreeEdges(), "multiple_edges": sew.NbMultipleEdges(), "degenerated": sew.NbDegeneratedShapes()}
    shells = []
    ex = TopExp_Explorer(sewn, TopAbs_SHELL)
    while ex.More():
        shells.append(TopoDS.Shell(ex.Current()))
        ex.Next()
    info["shells"] = len(shells)
    if not shells or info["free_edges"]:
        return sewn, {**info, "solid": False}
    solids = []
    for sh in shells:
        ms = BRepBuilderAPI_MakeSolid()
        ms.Add(sh)
        fix = ShapeFix_Solid(ms.Solid())
        fix.Perform()
        solids.append(fix.Solid())
    if len(solids) == 1:
        return solids[0], {**info, "solid": True}
    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for s in solids:
        b.Add(comp, s)
    return comp, {**info, "solid": True}


def unify(shape, linear_tol: float, angular_tol: float = 1e-6):
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    u.SetLinearTolerance(linear_tol)
    u.SetAngularTolerance(angular_tol)
    u.AllowInternalEdges(False)
    u.Build()
    return u.Shape()


def check(shape) -> dict:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)

    def count(kind):
        n, ex = 0, TopExp_Explorer(shape, kind)
        while ex.More():
            n += 1
            ex.Next()
        return n
    return {"valid": bool(BRepCheck_Analyzer(shape).IsValid()), "volume_mm3": float(g.Mass()),
            "faces": count(TopAbs_FACE), "solids": count(TopAbs_SOLID)}


def layer0(V: np.ndarray, F: np.ndarray, progress=None, merge: bool = True) -> tuple[object, dict]:
    """The mesh as a solid, with coplanar facets merged. Returns (TopoDS_Shape, info)."""
    t0 = time.perf_counter()
    size = float(np.ptp(V, axis=0).max()) or 1.0
    faces, skipped = _faces_from_triangles(V, F, progress)
    shape, info = shape_from_faces(faces, tol=max(1e-6, 1e-7 * size), progress=progress)
    info["skipped_triangles"] = skipped
    if not info["solid"]:
        return shape, {**info, "seconds": round(time.perf_counter() - t0, 2)}
    if merge:
        if progress:
            progress({"stage": "layer0", "text": "Merging coplanar facets", "fraction": 0.7})
        merged = unify(shape, linear_tol=max(1e-6, 1e-7 * size), angular_tol=1e-7)
        ck = check(merged)
        if ck["valid"]:
            shape = merged
        else:
            info["merge_note"] = "Merging coplanar facets gave an invalid solid; the facets were kept separate."
    info.update(check(shape))
    info["seconds"] = round(time.perf_counter() - t0, 2)
    return shape, info


def tessellate(shape, tol: float, levels: int = 4, faces_out: list | None = None):
    """(V, F) of a shape's faces, outward-wound, within about `tol` of the surfaces.

    The kernel's mesher keeps its nodes on the surfaces, but on B-spline faces the middles of its triangles can be
    several times `tol` away. So every triangle whose middle is farther than `tol` from the surface (evaluated at the
    middle of its parameters) is cut in four, the new corners evaluated on the surface, up to `levels` times. Cut
    triangles may leave cracks narrower than `tol` against uncut neighbours: this mesh is for measuring, not export."""
    from build123d import Shape
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    sh = Shape.cast(shape) if not hasattr(shape, "wrapped") else shape
    BRepMesh_IncrementalMesh(sh.wrapped, tol, False, 0.35, True)
    Ps, Ts, off = [], [], 0
    ex = TopExp_Explorer(sh.wrapped, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face(ex.Current())
        ex.Next()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is None or tri.NbTriangles() == 0:
            continue
        trsf = loc.Transformation()
        n = tri.NbNodes()
        P = np.empty((n, 3))
        for i in range(1, n + 1):
            q = tri.Node(i).Transformed(trsf)
            P[i - 1] = (q.X(), q.Y(), q.Z())
        T = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.int64) - 1
        if tri.HasUVNodes():
            UV = np.array([(tri.UVNode(i).X(), tri.UVNode(i).Y()) for i in range(1, n + 1)])
            P, T = _refine(BRepAdaptor_Surface(face), P, UV, T, tol, levels)
        if face.Orientation() == TopAbs_REVERSED:
            T = T[:, [0, 2, 1]]
        Ps.append(P)
        Ts.append(T + off)
        off += len(P)
        if faces_out is not None:                     # which face each triangle is on, for whoever asks
            faces_out.append((face, len(T)))
    if not Ps:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    return np.concatenate(Ps), np.concatenate(Ts)


def _refine(surf, P, UV, T, tol, levels):
    """Cut triangles whose middle is farther than tol from the surface into four, corners on the surface."""
    def at(uv):
        out = np.empty((len(uv), 3))
        for k, (u, v) in enumerate(uv):
            q = surf.Value(float(u), float(v))
            out[k] = (q.X(), q.Y(), q.Z())
        return out
    P, UV = list(P), list(UV)
    T = np.asarray(T)
    for _ in range(levels):
        Pa, UVa = np.array(P), np.array(UV)
        cen = at(UVa[T].mean(axis=1))
        dev = np.linalg.norm(cen - Pa[T].mean(axis=1), axis=1)
        bad = dev > tol
        if not bad.any():
            break
        mids = {}
        new = [T[~bad]]
        for a, b, c in T[bad].tolist():
            m = []
            for i, j in ((a, b), (b, c), (c, a)):
                k = (min(i, j), max(i, j))
                if k not in mids:
                    mids[k] = len(UV)
                    UV.append(0.5 * (UVa[i] + UVa[j]))
                    P.append(None)
                m.append(mids[k])
            ab, bc, ca = m
            new.append(np.array([[a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]]))
        idx = list(mids.values())
        pts = at(np.array([UV[i] for i in idx]))
        for i, q in zip(idx, pts):
            P[i] = q
        T = np.concatenate(new)
    return np.array(P), T
