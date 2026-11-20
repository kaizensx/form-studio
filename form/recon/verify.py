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


def _b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


def compare(V, F, P, T, spacing=None) -> dict:
    """Mesh (V, F) against reconstruction tessellation (P, T). Returns numbers plus per-triangle deviation of the mesh
    (key "_tri_dev") and per-vertex deviation of the reconstruction (key "_rec_dev")."""
    diag = float(np.linalg.norm(np.ptp(V, axis=0)))
    if spacing is None:
        spacing = max(diag / 300, 1e-3)
    SA, tA, spa = distance.sample_surface(V, F, spacing)
    SB, tB, spb = distance.sample_surface(P, T, spacing)
    dA = distance.MeshDistance(P, T, spacing).closest(SA)[0]
    dB = distance.MeshDistance(V, F, spacing).closest(SB)[0]
    tri_dev = np.zeros(len(F))
    np.maximum.at(tri_dev, tA, dA)
    rec_dev = distance.MeshDistance(V, F, spacing).closest(P)[0]
    return {"hausdorff_mm": float(max(dA.max(), dB.max())), "mesh_to_cad_max_mm": float(dA.max()),
            "cad_to_mesh_max_mm": float(dB.max()), "mean_mm": float(np.r_[dA, dB].mean()),
            "p99_mm": float(np.percentile(np.r_[dA, dB], 99)), "samples": int(len(SA) + len(SB)),
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
