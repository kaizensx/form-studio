"""Mesh to editable CAD, end to end. Kernel worker only (form/kernel.py runs `op_reconstruct`).

    Layer 0  the mesh as an exact solid (always built)             solid.layer0
    Layer 1  analytic faces where they fit, frozen facets elsewhere segment.segment + brep.build
    Layer 2  a feature recipe (build123d source with Params)        features.recipe

Each layer is verified against the mesh before it is offered; the best layer that passes is the result. Nothing is
decimated, nothing is repaired without being listed under "repairs".
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from . import mesh as meshmod
from . import verify

LIMITS = [
    "Units are taken as millimetres unless the file says otherwise (3MF does).",
    "Accuracy is measured against the mesh, not against the object it was made from: the mesh's own chord error "
    "and any scan noise are part of the input.",
    "Only planes, cylinders, cones, spheres and tori are recognised. Freeform surfaces (splines, sculpted or scanned "
    "shapes) stay as frozen facets: exact to the mesh, but not parametric.",
    "A curved surface is accepted when every mesh vertex on it is within the tolerance; a freeform surface that a "
    "simple one approximates within the tolerance is reported as that simple surface.",
]


def _step(shape, path: Path) -> None:
    from build123d import Shape, export_step
    export_step(Shape.cast(shape) if not hasattr(shape, "wrapped") else shape, str(path))


def _round(d, n=6):
    return {k: (round(v, n) if isinstance(v, float) else v) for k, v in d.items() if not k.startswith("_")}


def load(path: Path, fill: bool = True, weld_tol: float = 1e-6):
    """Read, weld, inspect. Returns (V, F, input_report, repairs)."""
    T, info = meshmod.read_triangles(path)
    V, F, w = meshmod.weld(T, weld_tol)
    top = meshmod.topology(V, F)
    repairs = []
    if w["dropped_collapsed"] or w["dropped_zero_area"] or w["dropped_duplicate"]:
        repairs.append({"repair": "dropped triangles", "collapsed": w["dropped_collapsed"], "zero_area": w["dropped_zero_area"],
                        "duplicate": w["dropped_duplicate"]})
    if w["merged_near_vertices"]:
        repairs.append({"repair": "welded near vertices", "count": w["merged_near_vertices"], "within_mm": weld_tol})
    if top["boundary_loops"] and fill and not top["non_manifold_edges"]:
        V, F, rec = meshmod.fill_holes(V, F, top["_loops"])
        repairs += rec
        top2 = meshmod.topology(V, F)
        top = {**top2, "before_repair": _round({k: v for k, v in top.items() if k in ("boundary_edges", "boundary_loops")})}
    if top["volume_mm3"] < 0:                          # inside out as a whole
        F = F[:, [0, 2, 1]]
        repairs.append({"repair": "turned the whole mesh outside in (its volume was negative)"})
        top = meshmod.topology(V, F)
    report = {**info, "weld": w, "topology": _round(top)}
    if top["_non_manifold_at"]:
        report["topology"]["non_manifold_at"] = top["_non_manifold_at"]
    return V, F, report, repairs


def reconstruct(path, out_dir, name: str | None = None, tolerance: float = 0.02, layer: int = 2,
                budget_s: float = 240.0, progress=None, fill_holes: bool = True) -> dict:
    """Reconstruct a mesh file as CAD. Writes <name>.step (the best verified layer), <name>_layer0.step,
    <name>_report.json, <name>_deviation.json and, when Layer 2 succeeds, <name>_recipe.py. Returns the report."""
    from . import solid
    t0 = time.perf_counter()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = Path(path)
    name = name or path.stem
    say = progress or (lambda d: None)
    say({"stage": "read", "text": f"Reading {path.name}", "fraction": 0.0})
    V, F, inp, repairs = load(path, fill=fill_holes)
    n = len(F)
    if n > 200_000:
        say({"stage": "read", "text": f"{n:,} triangles: this takes a while; nothing is decimated", "fraction": 0.01})
    tol = float(tolerance)
    rep = {"version": 1, "evidence": "computed", "input": inp, "repairs": repairs, "tolerance_mm": tol,
           "layer_requested": int(layer), "layers": {}, "limits": list(LIMITS)}
    mvol = verify.mesh_volume(V, F)
    if not inp["topology"]["closed"]:
        rep["error"] = ("The mesh is not closed (" + f"{inp['topology']['boundary_loops']} open boundaries, "
                        f"{inp['topology']['non_manifold_edges']} non-manifold edges), so it does not bound a solid.")
        rep["hint"] = "Close it in the program that made it, or reconstruct with hole filling on (it is listed as a repair)."
        return _finish(rep, out, name, t0)

    # Layer 0
    say({"stage": "layer0", "text": "Building the exact solid", "fraction": 0.02})
    P0 = T0 = c0 = None
    sh0, i0 = solid.layer0(V, F, progress=lambda d: say({**d, "fraction": 0.02 + 0.25 * d.get("fraction", 0)}))
    L0 = {"built": bool(i0.get("solid")), **{k: i0[k] for k in ("valid", "faces", "solids", "volume_mm3", "seconds") if k in i0}}
    if i0.get("solid"):
        P0, T0 = solid.tessellate(sh0, max(tol / 10, 1e-4))
        c0 = verify.compare(V, F, P0, T0)
        L0.update(_round(c0))
        _step(sh0, out / f"{name}_layer0.step")
        L0["step"] = f"{name}_layer0.step"
    else:
        L0["error"] = f"Sewing left {i0.get('free_edges', 0)} free edges; the triangles do not close into a solid."
    rep["layers"]["0"] = L0
    best = ("0", sh0, P0, T0, c0, None) if L0.get("valid") else None

    # Layer 1
    regions = None
    if layer >= 1 and best is not None:
        say({"stage": "layer1", "text": "Finding planes, cylinders, cones, spheres and tori", "fraction": 0.3})
        try:
            got = _layer1(V, F, tol, budget_s=max(10.0, budget_s * 0.5 - (time.perf_counter() - t0)),
                          progress=lambda d: say({**d, "fraction": 0.3 + 0.4 * d.get("fraction", 0)}))
        except Exception as e:                          # noqa: BLE001
            got = {"report": {"error": f"{type(e).__name__}: {e}"[:300]}}
        rep["layers"]["1"] = got["report"]
        if got.get("shape") is not None:
            regions = got["regions"]
            best = ("1", got["shape"], got["P"], got["T"], got["cmp"], regions)

    # Layer 2
    recipe = None
    if layer >= 2 and regions is not None:
        say({"stage": "layer2", "text": "Looking for features: extrusions, revolutions, holes, patterns", "fraction": 0.72})
        from . import features
        try:
            limit = max(tol, rep["layers"]["1"].get("hausdorff_mm", 0.0) * 1.05)
            r2 = features.recipe(V, F, regions, tol, name=name, limit=limit,
                                 progress=lambda d: say({**d, "fraction": 0.72 + 0.25 * d.get("fraction", 0)}))
        except Exception as e:                          # noqa: BLE001
            r2 = {"report": {"error": f"{type(e).__name__}: {e}"[:300]}}
        rep["layers"]["2"] = r2["report"]
        if r2.get("source"):
            recipe = r2["source"]
            (out / f"{name}_recipe.py").write_text(recipe, encoding="utf-8")
            rep["layers"]["2"]["file"] = f"{name}_recipe.py"
            if r2.get("verified"):
                best = ("2", r2["shape"], r2["P"], r2["T"], r2["cmp"], regions)

    if best is None:
        rep["error"] = "No layer produced a valid solid."
        return _finish(rep, out, name, t0)
    lay, shape, P, T, cmp, regs = best
    _step(shape, out / f"{name}.step")
    vol = solid.check(shape)["volume_mm3"]
    area = rep["layers"]["1"] if lay in ("1", "2") else None
    par = (area or {}).get("parametric_area_pct", 0.0)       # surfaces, also under a recipe: a profile edge read off facets is still facets
    rep["layer_achieved"] = int(lay)
    rep["result"] = {"layer": int(lay), "step": f"{name}.step", "recipe": f"{name}_recipe.py" if recipe else None,
                     "recipe_verified": bool(lay == "2"), "volume_mm3": round(vol, 4), "mesh_volume_mm3": round(mvol, 4),
                     "volume_delta_mm3": round(vol - mvol, 4), "volume_delta_pct": round(100 * (vol - mvol) / mvol, 5) if mvol else None,
                     "hausdorff_mm": round(cmp["hausdorff_mm"], 6), "parametric_area_pct": par,
                     "frozen_area_pct": round(100.0 - par, 2)}
    dmap = verify.deviation_map(P, T, cmp["_rec_dev"], tol)
    (out / f"{name}_deviation.json").write_text(json.dumps(dmap), encoding="utf-8")
    rep["result"]["deviation_map"] = f"{name}_deviation.json"
    return _finish(rep, out, name, t0)


def _finish(rep, out, name, t0):
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    (out / f"{name}_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def vertex_dev(r, V, F) -> float:
    return float(np.abs(r.prim.dist(V[np.unique(F[r.tris])])).max())


def _allowance(V, F, tris, reg, tol, chord=None):
    """Largest deviation each triangle of a region may have: the tolerance, plus on a curved surface the chord error a
    straight-edged triangle of that size must have there. `chord` is the mesh's chord error measured on surfaces that
    fit exactly; when known it caps that allowance."""
    if not reg.parametric or reg.kind == "plane":
        return np.full(len(tris), tol)
    from .segment import chord_error
    ce = chord_error(reg.prim, V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]])
    return tol + (np.minimum(ce, chord * 1.25) if chord is not None else ce)


def _layer1(V, F, tol, budget_s, progress):
    from . import brep, segment, solid
    t0 = time.perf_counter()
    regions, st = segment.segment(V, F, tol, budget_s=budget_s, progress=progress)
    rounds = []
    for attempt in range(5):
        shape, info = brep.build(V, F, regions, tol, progress=progress)
        frozen = []
        if shape is None or not info.get("valid"):
            ids = [f["region"] for f in info.get("face_failures", [])]
            if shape is not None and not ids:
                ids = brep.bad_regions(shape, regions, V, F)
            if not ids:
                rounds.append({"build": _round(info), "frozen": []})
                break
            frozen = ids
            cmp = None
        else:
            P, T = solid.tessellate(shape, max(tol / 10, 1e-4))
            cmp = verify.compare(V, F, P, T)
            dev = cmp["_tri_dev"]
            # the mesh's own chord error, seen where a curved surface fits the vertices almost exactly
            exact = [r for r in regions if r.parametric and r.kind != "plane" and vertex_dev(r, V, F) < tol / 20]
            chord = max((float(dev[r.tris].max()) for r in exact), default=None)
            for r in regions:
                if r.parametric and np.any(dev[r.tris] > _allowance(V, F, r.tris, r, tol, chord)):
                    frozen.append(r.id)
        rounds.append({"build": {k: info[k] for k in ("faces", "valid", "edges_line", "edges_circle", "edges_arc", "edges_segment")
                                 if k in info}, "hausdorff_mm": round(cmp["hausdorff_mm"], 6) if cmp else None,
                       "frozen_regions": [{"id": i, "kind": regions[i].kind} for i in frozen]})
        if not frozen:
            break
        regions = _freeze(V, F, regions, frozen)
        shape = None
    summ = segment.summary(regions)
    rep = {**summ, "segmentation": st, "rounds": rounds,
           "surfaces": [{"kind": r.kind, "triangles": int(len(r.tris)), "area_mm2": round(r.area, 4), **(r.prim.public() if r.prim else {})}
                        for r in sorted(regions, key=lambda r: -r.area) if r.parametric][:300]}
    if shape is None or not rounds or rounds[-1].get("frozen_regions"):
        rep["error"] = "The analytic faces did not close into a valid solid; Layer 0 is the result."
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep}
    vol = solid.check(shape)["volume_mm3"]
    rep.update({"valid": True, "volume_mm3": round(vol, 4), **_round(cmp), "seconds": round(time.perf_counter() - t0, 2)})
    return {"report": rep, "shape": shape, "regions": regions, "P": P, "T": T, "cmp": cmp}


def _freeze(V, F, regions, ids):
    """Turn regions into frozen facets, one per triangle, and renumber."""
    from .segment import Region
    _, A = meshmod.tri_normals(V, F)
    ids = set(ids)
    out = []
    for r in regions:
        if r.id in ids:
            out += [Region(0, "facet", np.array([t]), None, float(A[t])) for t in r.tris.tolist()]
        else:
            out.append(r)
    for i, r in enumerate(out):
        r.id = i
    return out
