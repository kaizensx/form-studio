"""The part as CAM needs it, read from the kernel's B-rep (kernel worker only).

    triangles   the solid's tessellation at a stated tolerance (0.02 mm unless asked otherwise)
    holes       full cylindrical bores (form/dfm/geom.py): diameter, depth, axis, centre

Everything else in form/cam is plain numpy on these and runs outside the worker.
"""
from __future__ import annotations

import base64
import time

import numpy as np

VERSION = 1
TOL = 0.02


def triangles(model) -> np.ndarray:
    """(n, 3, 3) float64: every triangle of the model's faces."""
    out = []
    for f in model["faces"]:
        P, T = np.asarray(f["P"], float), np.asarray(f["T"], np.int64)
        if len(T):
            out.append(P[T])
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def of_model(model) -> dict:
    from ..dfm import geom
    tri = triangles(model)
    holes = []
    if not getattr(model.get("recipe"), "mesh", False) and model.get("shape") is not None:
        for h in geom.holes(model["shape"]):
            holes.append({"d": float(h["d"]), "depth": float(h["depth"]), "axis": [float(v) for v in h["axis"]],
                          "at": [float(v) for v in h["at"]]})
    return {"tri": tri, "holes": holes, "tol": float(model.get("tol", TOL))}


def of_shape(shape, tol: float = TOL) -> dict:
    """The same for a bare build123d solid (tests and callers without a design)."""
    from .. import thickness
    return of_model(thickness.model_of_shape(shape, tol))


def op_cam_target(key, recipe_id, values, tol=TOL):
    from .. import kernel
    t0 = time.perf_counter()
    model = kernel._get(key, recipe_id, values, tol)
    out = of_model(model)
    tri = out.pop("tri")
    return {"version": VERSION, "tol": tol, "triangles": int(len(tri)), "holes": out["holes"],
            "mesh": bool(getattr(model.get("recipe"), "mesh", False)),
            "positions": base64.b64encode(np.ascontiguousarray(tri, dtype=np.float64).tobytes()).decode(),
            "seconds": round(time.perf_counter() - t0, 3)}


KERNEL_OPS = {"cam_target": op_cam_target}
