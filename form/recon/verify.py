"""How close a reconstruction is to the mesh it came from: Hausdorff both ways, volume, and a deviation map.

The reconstruction is tessellated finely (its deflection is reported; for planar faces the tessellation is exact) and
compared with the mesh by exact point-to-triangle distances (distance.py). The deviation map follows the analysis-map
conventions (form/analysis.py): positions, indices, per-vertex values in mm and RGBA colours, with a legend that says
how the numbers are known and what they do not tell you.
"""
from __future__ import annotations

import base64

import numpy as np

from . import distance

EXACT_ABOVE = 1e-4          # mm: a sample already this close to the other surface keeps that (upper-bound) distance


def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def _off_shape(shapes, pts, eps):
    """Which of these points are not on their face (more than eps from it): samples of a tessellation triangle the
    mesher laid across a thin face, outside the face itself. shapes[i] is the face (or solid) point i should be on."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    out = np.zeros(len(pts), dtype=bool)
    for i, p in enumerate(pts):
        d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex(), shapes[i])
        out[i] = d.IsDone() and d.Value() > eps
    return out


def compare(V, F, P, T, spacing=None, shape=None, check_above=None, faces=None) -> dict:
    """Mesh (V, F) against reconstruction tessellation (P, T). Returns numbers plus per-triangle deviation of the mesh
    (key "_tri_dev") and per-vertex deviation of the reconstruction (key "_rec_dev").

    With `shape` (the reconstructed solid), samples of the reconstruction that are more than `check_above` from the
    mesh are checked against the solid itself (against their own face, when `faces` lists (face, triangle count) in
    the tessellation's order, which is much faster): a sample that is not on the surface (a tessellation triangle laid
    across a thin face, outside it) is left out and counted as "tessellation_artifacts"."""
    diag = float(np.linalg.norm(np.ptp(V, axis=0)))
    if spacing is None:
        spacing = max(diag / 300, 1e-3)
    SA, tA, spa = distance.sample_surface(V, F, spacing)
    SB, tB, spb = distance.sample_surface(P, T, spacing)
    ex = EXACT_ABOVE                                     # nearer than this, an upper bound is enough (see closest)
    dA = distance.MeshDistance(P, T, spacing).closest(SA, exact_above=ex)[0]
    to_mesh = distance.MeshDistance(V, F, spacing)
    dB = to_mesh.closest(SB, exact_above=ex)[0]
    artifacts = 0
    if shape is not None and check_above is not None:
        idx = np.flatnonzero(dB > check_above)
        if len(idx):
            # one check per small cell of the bad samples (they come in clusters)
            cell = np.floor(SB[idx] / max(spacing, 1e-3)).astype(np.int64)
            _, first, inv = np.unique(cell, axis=0, return_index=True, return_inverse=True)
            first = first[:4000]
            if faces:
                fo = np.repeat(np.arange(len(faces)), [n for _, n in faces])
                owners = [faces[int(fo[t])][0] for t in tB[idx[first]]]
            else:
                owners = [shape] * len(first)
            off = _off_shape(owners, SB[idx[first]], max(1e-5 * diag, 1e-6))
            bad_cell = np.zeros(int(inv.max()) + 1, dtype=bool)
            bad_cell[:len(off)] = off
            drop = idx[bad_cell[inv.reshape(-1)]]
            artifacts = int(len(drop))
            dB[drop] = 0.0
    tri_dev = np.zeros(len(F))
    np.maximum.at(tri_dev, tA, dA)
    rec_dev = to_mesh.closest(P, exact_above=ex)[0]
    return {"hausdorff_mm": float(max(dA.max(), dB.max())), "mesh_to_cad_max_mm": float(dA.max()),
            "cad_to_mesh_max_mm": float(dB.max()), "mean_mm": float(np.r_[dA, dB].mean()),
            "p99_mm": float(np.percentile(np.r_[dA, dB], 99)), "samples": int(len(SA) + len(SB)),
            **({"tessellation_artifacts": artifacts} if artifacts else {}),
            "sample_spacing_mm": round(float(max(spa, spb)), 4), "_tri_dev": tri_dev, "_rec_dev": rec_dev}


def mesh_volume(V, F) -> float:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def deviation_map(P, T, dev, tol, face_kind=None) -> dict:
    """Analysis-map style colouring of the reconstruction by its distance to the mesh."""
    from ..analysis import AMBER, BLUEPRINT, CLAY, SIGNAL, _hex, _legend, _rgba
    rgb = np.tile(np.asarray(CLAY, dtype=np.float64), (len(P), 1))
    rgb[dev > 0.5 * tol] = AMBER
    rgb[dev > tol] = SIGNAL
    out = {"map": "deviation", "label": "Deviation from the mesh", "evidence": "computed", "tolerance_mm": tol,
           "vertices": int(len(P)), "triangles": int(len(T)),
           "stats": {"max_mm": round(float(dev.max()), 6) if len(dev) else 0.0,
                     "mean_mm": round(float(dev.mean()), 6) if len(dev) else 0.0,
                     "over_tolerance_pct": round(100 * float((dev > tol).mean()), 3) if len(dev) else 0.0}}
    out["legend"] = _legend(
        "Deviation from the mesh", "mm",
        [{"color": _hex(CLAY), "label": f"under {0.5 * tol:g} mm", "note": "within half the tolerance"},
         {"color": _hex(AMBER), "label": f"{0.5 * tol:g} to {tol:g} mm", "note": "within the tolerance"},
         {"color": _hex(SIGNAL), "label": f"over {tol:g} mm", "note": "outside the tolerance"}]
        + ([{"color": _hex(BLUEPRINT), "label": "frozen facets", "note": "kept exactly as the mesh's triangles"}] if face_kind is not None else []),
        "Distance from each point of the reconstructed solid's tessellation to the nearest point of the input mesh "
        "(exact point-to-triangle distance).",
        "It compares with the mesh, not with the object the mesh was made from: a mesh's own chord error and any "
        "scan noise are in the input.", hover="{v} mm from the mesh", none="")
    out["positions"], out["indices"] = _b64(P.astype(np.float32)), _b64(T.astype(np.uint32))
    out["values"], out["colors"] = _b64(dev.astype(np.float32)), _b64(_rgba(rgb))
    return out
