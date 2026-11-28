"""Kernel operations for drawings (worker process only): views, sections, measurements, perturbed builds, PMI."""
from __future__ import annotations

import time


def _model(key, recipe_id, values):
    from ..kernel import _brep
    return _brep(key, recipe_id, values)


def op_drawing_views(key, recipe_id, values, views=("front", "top", "right", "iso"), sections=(), perturb=None,
                     budget_s: float = 60.0):
    """Every view by hidden-line removal, the sections asked for, the B-rep's measurements, and the measurements of
    builds with one parameter nudged (to prove which size a parameter drives)."""
    from . import views as V
    base = _model(key, recipe_id, values)
    shape = base["shape"]
    out = {"views": {}, "sections": [], "measure": V.measure(shape, base.get("face_features"))}
    t0 = time.perf_counter()
    for v in views:
        out["views"][v] = V.project(shape, v, hidden=(v != "iso"))
    for s in sections or ():
        sec = V.section(shape, s["origin"], s["normal"], s["right"])
        sec["id"] = s.get("id", "A")
        out["sections"].append(sec)
    out["t_views"] = round(time.perf_counter() - t0, 3)
    out["perturbed"] = {}
    if perturb:
        from ..kernel import _build_brep
        from ..recipes import resolve
        recipe = resolve(recipe_id)
        v0 = recipe.validate(values)
        t1 = time.perf_counter()
        for k, delta in perturb.items():
            if time.perf_counter() - t1 > budget_s:
                out["perturbed"][k] = {"skipped": "time budget"}
                continue
            vals = dict(v0)
            vals[k] = v0[k] + delta
            try:
                b = _build_brep(recipe_id, vals)
                out["perturbed"][k] = {"delta": delta, "measure": V.measure(b["shape"], b.get("face_features"))}
            except Exception as e:  # noqa: BLE001  (a nudge that breaks the design proves nothing; say so)
                out["perturbed"][k] = {"delta": delta, "error": f"{type(e).__name__}: {e}"[:200]}
        out["t_perturb"] = round(time.perf_counter() - t1, 3)
    return out


def op_drawing_pmi(key, recipe_id, values, path, annotations):
    """Write the solid as STEP AP242 with semantic PMI on its faces, read the file back and list what it holds."""
    from . import pmi
    base = _model(key, recipe_id, values)
    written = pmi.write(base["shape"], path, annotations)
    return {"path": path, "written": written, "read_back": pmi.read(path)}


KERNEL_OPS = {"drawing_views": op_drawing_views, "drawing_pmi": op_drawing_pmi}
