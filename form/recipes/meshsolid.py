"""Triangle meshes as kernel shapes, and reference parts a design can use. Kernel worker only (imports OCCT).

A mesh brought into the kernel stays a mesh: every triangle becomes one planar face, sewn into a closed shell. That
lets volume, ray-cast wall thickness and the exported STL work on it, but it is not a boundary representation of the
intended surfaces, so FORM never writes it to STEP and never calls it a CAD solid.
"""
from __future__ import annotations

from pathlib import Path

MAX_TRIANGLES = 200_000


def solid_from_triangles(tris, tol: float = 1e-4):
    """Sew triangles into a solid (one face per triangle). Raises ValueError if they do not close."""
    from build123d import Compound, Solid
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid,
                                    BRepBuilderAPI_Sewing)
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    if len(tris) > MAX_TRIANGLES:
        raise ValueError(f"The mesh has {len(tris):,} triangles; FORM handles up to {MAX_TRIANGLES:,}. Lower $fn or simplify.")
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


def import_shape(p: Path):
    """A STEP as its B-rep, an STL as a sewn mesh solid."""
    from build123d import import_step
    ext = p.suffix.lower()
    if ext in (".step", ".stp"):
        return import_step(str(p))
    if ext == ".stl":
        return read_stl_solid(p)
    raise ValueError(f"Unsupported reference format {ext}; use STEP or STL.")
