"""Kernel side of a strength study (worker only): the solid as STEP for the mesher, and the picked faces.

`op_fea_prepare` writes the design's B-rep to a STEP file in the frame the study is solved in, and resolves every
picked point to the B-rep face under it. A design of one solid is solved as built. A design that declares an assembly
is solved assembled: each part is moved to its assembled placement, and a point picked on a part as printed (the frame
of every other selection in Form Studio) is moved with it.

A face reaches the mesher as points on it (centroids of its tessellation's largest triangles) and its exact area: the
mesh's boundary triangles nearest to those points name the face, and the area is compared, so a pick that no longer
describes the geometry is refused instead of loading the wrong face.
"""
from __future__ import annotations

import numpy as np

SAMPLES = 7
OFF_SURFACE_MM = 1.0


def _matrix(loc) -> np.ndarray:
    t = loc.wrapped.Transformation()
    return np.array([[t.Value(r, c) for c in range(1, 5)] for r in range(1, 4)], dtype=float)


def _surface_axis(face):
    """Axis direction of a cylindrical face, or the normal of a planar one (unit vectors, build frame); else None."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    s = BRepAdaptor_Surface(face.wrapped)
    if s.GetType() == GeomAbs_Cylinder:
        d = s.Cylinder().Axis().Direction()
        return "cylinder", [d.X(), d.Y(), d.Z()], float(s.Cylinder().Radius())
    if s.GetType() == GeomAbs_Plane:
        d = s.Plane().Axis().Direction()
        return "plane", [d.X(), d.Y(), d.Z()], None
    return face.geom_type.name.lower(), None, None


def op_fea_prepare(key, recipe_id, values, out_step, picks, tol=0.05):
    """{"step", "assembled", "parts", "picks", "bbox", "volume_mm3"}, or {"error": sentence} when the design or a
    pick cannot carry a study."""
    try:
        return _prepare(key, recipe_id, values, out_step, picks, tol)
    except ValueError as e:
        return {"error": str(e)}


def _prepare(key, recipe_id, values, out_step, picks, tol):
    from build123d import Compound, export_step

    from .. import assembly as asm
    from .. import kernel, selection
    model = kernel._get_near(key, recipe_id, values, tol)
    if getattr(model["recipe"], "mesh", False):
        raise ValueError("A strength study needs a CAD solid: this design is a mesh (OpenSCAD), which has no faces to "
                         "pick and no B-rep to mesh from.")
    a = asm.get(model)
    several = bool(a and not a.get("error") and len(a.get("placed") or []) >= 2)
    if several:
        solids = list(a["placed"])
        mats = [_matrix(loc) for loc in a["locs"]]
        parts = [{"id": p.id, "label": p.label, "material": p.material or ""} for p in a["spec"].parts]
        shape = Compound(children=solids)
    else:
        shape = model["shape"]
        solids = list(shape.solids())
        mats = [np.hstack([np.eye(3), np.zeros((3, 1))])]
        parts = [{"id": "", "label": "", "material": ""}]
        if len(solids) != 1:
            raise ValueError(f"The design has {len(solids)} separate solids and declares no assembly, so it is not known "
                             "how they sit together. Declare assembly() in the design, or fuse them.")
    for part, s in zip(parts, solids):
        c = s.center()
        part.update({"centre": [c.X, c.Y, c.Z], "volume_mm3": float(s.volume)})
    ctx = selection._Ctx(model, "as_modelled")
    out_picks = []
    for it in picks:
        p = np.asarray(it["at"], dtype=np.float64)
        dist, fi, on, _tk = ctx.nearest(p)
        if dist > OFF_SURFACE_MM:
            raise ValueError(f"The point {np.round(p, 3).tolist()} is {dist:.2f} mm off the part's surface: pick a point "
                             "on the face (analyze_selection shows where a point lands).")
        x = model["faces"][fi]
        k = (a["face_part"][fi] if several else 0)
        if several and k < 0:
            raise ValueError("The picked face belongs to no declared part of the assembly.")
        M = mats[k]
        P, T = x["P"], x["T"]
        A, B, C = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
        area = np.linalg.norm(np.cross(B - A, C - A), axis=1) / 2
        order = np.argsort(-area)[:SAMPLES]
        cen = (A[order] + B[order] + C[order]) / 3
        face = x["face"]
        kind, axis, radius = _surface_axis(face)
        info = {"at": [float(t) for t in p], "part": parts[k]["id"], "feature": x.get("feature"), "face_index": int(fi),
                "type": kind, "area": float(face.area),
                "samples": (cen @ M[:, :3].T + M[:, 3]).tolist(),
                "on": (np.asarray(on) @ M[:, :3].T + M[:, 3]).tolist()}
        if axis is not None:
            info["axis"] = (M[:, :3] @ np.asarray(axis)).tolist()
        if radius is not None:
            info["radius"] = radius
        out_picks.append(info)
    export_step(shape, str(out_step))
    bb = shape.bounding_box()
    return {"step": str(out_step), "assembled": several, "parts": parts, "picks": out_picks,
            "bbox": [[bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]],
            "volume_mm3": float(sum(pt["volume_mm3"] for pt in parts))}


KERNEL_OPS = {"fea_prepare": op_fea_prepare}
