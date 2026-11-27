"""Triangle meshes as kernel shapes, and reference parts a design can use. Kernel worker only (imports OCCT).

A mesh brought into the kernel stays a mesh: every triangle becomes one planar face, sewn into a closed shell. That
lets volume, ray-cast wall thickness and the exported STL work on it, but it is not a boundary representation of the
intended surfaces, so FORM never writes it to STEP and never calls it a CAD solid.
"""
from __future__ import annotations

from pathlib import Path

MAX_TRIANGLES = 200_000


def solid_from_mesh(V, F):
    """A closed, consistently oriented triangle mesh (welded: V (n, 3), F (m, 3)) as a solid, one planar face per
    triangle, built directly: every vertex and edge is made once and shared, so nothing has to be searched for and
    sewn (a 100,000-triangle mesh takes about 2 s; sewing it takes a minute). One solid per connected piece.
    Raises ValueError when the mesh is not closed: the caller then sews (solid_from_triangles)."""
    import numpy as np
    from build123d import Compound, Solid
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopoDS import TopoDS, TopoDS_Shell, TopoDS_Solid, TopoDS_Wire
    from ..recon import mesh as meshmod
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    top = meshmod.topology(V, F)
    if not top["closed"] or top["flipped_edges"]:
        raise ValueError("The mesh is not closed and consistently oriented.")
    _E, _tri, eo, _he = meshmod.edges(F)
    E = _E.tolist()
    m = len(F)
    eo = np.stack([eo[:m], eo[m:2 * m], eo[2 * m:]], axis=1).tolist()
    fwd = np.stack([F[:, 0] < F[:, 1], F[:, 1] < F[:, 2], F[:, 2] < F[:, 0]], axis=1).tolist()
    N = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    L = np.linalg.norm(N, axis=1)
    N = (N / np.maximum(L, 1e-300)[:, None]).tolist()
    B = BRep_Builder()
    pts = [gp_Pnt(x, y, z) for x, y, z in V.tolist()]
    vs = [BRepBuilderAPI_MakeVertex(p).Vertex() for p in pts]
    es = [BRepBuilderAPI_MakeEdge(vs[a], vs[b]).Edge() for a, b in E]
    piece = top["_piece_of"]
    shells = []
    for _ in range(int(top["pieces"])):
        sh = TopoDS_Shell()
        B.MakeShell(sh)
        shells.append(sh)
    first = F[:, 0].tolist()
    for t in range(m):
        if L[t] <= 0:
            continue
        w = TopoDS_Wire()
        B.MakeWire(w)
        for k in range(3):
            e = es[eo[t][k]]
            B.Add(w, e if fwd[t][k] else TopoDS.Edge(e.Reversed()))
        w.Closed(True)
        f = BRepBuilderAPI_MakeFace(gp_Pln(pts[first[t]], gp_Dir(*N[t])), w, True)
        if f.IsDone():
            B.Add(shells[piece[t]], f.Face())
    solids = []
    for sh in shells:
        sh.Closed(True)
        so = TopoDS_Solid()
        B.MakeSolid(so)
        B.Add(so, sh)
        s = Solid(so)
        if s.volume < 0:
            s = Solid(s.wrapped.Reversed())
        solids.append(s)
    return solids[0] if len(solids) == 1 else Compound(solids)


def solid_from_triangles(tris, tol: float = 1e-4):
    """Triangles as a solid (one face per triangle): built directly when they weld into a closed mesh
    (solid_from_mesh), sewn otherwise. Raises ValueError if they do not close."""
    from build123d import Compound, Solid
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid,
                                    BRepBuilderAPI_Sewing)
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    if len(tris) > MAX_TRIANGLES:
        raise ValueError(f"The mesh has {len(tris):,} triangles; Form Studio handles up to {MAX_TRIANGLES:,}. Lower $fn or simplify.")
    try:
        import numpy as np
        from ..recon.mesh import weld
        V, F, _ = weld(np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3), 1e-6)
        return solid_from_mesh(V, F)
    except ValueError:
        pass
    sew = BRepBuilderAPI_Sewing(tol)
    added = 0
    for a, b, c in tris:
        poly = BRepBuilderAPI_MakePolygon(gp_Pnt(*a), gp_Pnt(*b), gp_Pnt(*c), True)
        if not poly.IsDone():
            continue                                   # degenerate triangle
        f = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        if f.IsDone():
            sew.Add(f.Face())
            added += 1
    if not added:
        raise ValueError("The mesh has no usable triangles.")
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    solids = []
    while ex.More():
        ms = BRepBuilderAPI_MakeSolid()
        ms.Add(TopoDS.Shell(ex.Current()))
        s = Solid(ms.Solid())
        if s.volume < 0:                              # inward-facing shell
            s = Solid(s.wrapped.Reversed())
        solids.append(s)
        ex.Next()
    if not solids:
        raise ValueError("The triangles do not form a closed shell.")
    return solids[0] if len(solids) == 1 else Compound(solids)


def read_stl_solid(path: Path):
    from ..mesh_audit import read_stl
    tris, _fmt, _sha = read_stl(path)
    return solid_from_triangles(tris)


# ---- reference parts: `self.reference("pi5.step")` inside a design --------------------------------------------------

_paths: dict = {}          # name -> absolute path, set by the worker for each call
_loaded: dict = {}         # (path, mtime, size) -> shape


def set_paths(paths: dict | None) -> None:
    _paths.clear()
    _paths.update(paths or {})


def load(name: str):
    from .base import RecipeError
    path = _paths.get(name)
    if not path or not Path(path).exists():
        known = ", ".join(sorted(_paths)) or "none"
        raise RecipeError(f"Reference part “{name}” is not in this project.", "",
                          f"Import it first (import_reference, or Brief → Import part…). Imported: {known}.")
    p = Path(path)
    k = (str(p), p.stat().st_mtime_ns, p.stat().st_size)
    if k not in _loaded:
        if len(_loaded) > 6:
            _loaded.pop(next(iter(_loaded)))
        _loaded[k] = import_shape(p)
    return _loaded[k]


def import_cad(p: Path, ext: str | None = None):
    """STEP, IGES or OCCT BREP as its B-rep (millimetres: OCCT converts a STEP's or an IGES's units on read)."""
    from build123d import import_brep, import_step
    ext = (ext or p.suffix).lower()
    if ext in (".step", ".stp"):
        return import_step(str(p))
    if ext in (".brep", ".brp"):
        return import_brep(str(p))
    if ext in (".iges", ".igs"):
        from build123d import Compound, Shape
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.IGESControl import IGESControl_Reader
        from OCP.Interface import Interface_Static
        Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
        r = IGESControl_Reader()
        if r.ReadFile(str(p)) != IFSelect_RetDone:
            raise ValueError(f"{p.name} is not a readable IGES file.")
        r.TransferRoots()
        shape = r.OneShape()
        if shape.IsNull():
            raise ValueError(f"{p.name} holds no shape the kernel can read.")
        out = Shape.cast(shape)
        return out if out is not None else Compound(shape)
    raise ValueError(f"{p.name} is not STEP, IGES or BREP.")


def import_shape(p: Path):
    """STEP, IGES or BREP as its B-rep; a mesh or point cloud (form/formats.py) as a sewn mesh solid."""
    from ..formats import extensions
    ext = p.suffix.lower()
    if ext in extensions("brep"):
        return import_cad(p)
    if ext == ".stl":
        return read_stl_solid(p)
    if ext in extensions("mesh", "pointcloud"):
        from ..recon.mesh import read_triangles
        return solid_from_triangles(read_triangles(p)[0].tolist())
    from ..formats import unsupported
    raise ValueError(unsupported(p))
