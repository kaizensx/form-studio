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
    "Planes, cylinders, cones, spheres and tori are recognised as such. Smooth regions none of them explains are fitted "
    "with B-spline patches (freeform: smooth CAD within the tolerance, not a dimension you can change); what neither "
    "explains stays as frozen facets.",
    "Layer 2 rebuilds a base (extrusion stack, revolution, or the reconstructed solid kept exactly) and puts holes, "
    "fillets and chamfers back as operations; a feature that does not verify stays in the base and is listed.",
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

    # A spur gear is recognised from the mesh itself (gears.py); when its parametric gear is within the tolerance,
    # it is the result and the surface-by-surface layer is not needed
    gear = None
    if layer >= 2 and best is not None:
        gear = _gear(V, F, tol, name, say)
        if gear is not None and gear.get("verified"):
            rep["layers"]["1"] = {"skipped": "A parametric gear was found and verified against the mesh first (Layer 2)."}

    # Layer 1
    regions = l1shape = None
    if layer >= 1 and best is not None and not (gear and gear.get("verified")):
        say({"stage": "layer1", "text": "Finding planes, cylinders, cones, spheres and tori", "fraction": 0.3})
        try:
            got = _layer1(V, F, tol, budget_s=max(10.0, budget_s * 0.5 - (time.perf_counter() - t0)),
                          progress=lambda d: say({**d, "fraction": 0.3 + 0.4 * d.get("fraction", 0)}))
        except Exception as e:                          # noqa: BLE001
            got = {"report": {"error": f"{type(e).__name__}: {e}"[:300]}}
        rep["layers"]["1"] = got["report"]
        if got.get("shape") is not None:
            regions = got["regions"]
            l1shape = got["shape"]
            best = ("1", got["shape"], got["P"], got["T"], got["cmp"], regions)

    # Layer 2
    recipe = None
    refs = []
    if gear is not None and gear.get("verified"):
        recipe = gear["source"]
        (out / f"{name}_recipe.py").write_text(recipe, encoding="utf-8")
        rep["layers"]["2"] = {**gear["report"], "file": f"{name}_recipe.py", "driven_by_params_pct": 100.0}
        best = ("2", gear["shape"], gear["P"], gear["T"], gear["cmp"], None)
    elif layer >= 2 and regions is not None:
        say({"stage": "layer2", "text": "Looking for features: base, holes, fillets, chamfers, patterns", "fraction": 0.72})
        r2 = layer2(V, F, regions, l1shape, tol, name, out, rep["layers"]["1"],
                    progress=lambda d: say({**d, "fraction": 0.72 + 0.25 * d.get("fraction", 0)}),
                    deadline=t0 + 0.92 * float(budget_s))
        if gear is not None:
            r2["report"]["also_tried"] = r2["report"].get("also_tried", []) + [
                {k: gear["report"].get(k) for k in ("method", "base", "verified", "hausdorff_mm", "error") if gear["report"].get(k) is not None}]
        rep["layers"]["2"] = r2["report"]
        if r2.get("source"):
            recipe = r2["source"]
            (out / f"{name}_recipe.py").write_text(recipe, encoding="utf-8")
            rep["layers"]["2"]["file"] = f"{name}_recipe.py"
            if r2.get("verified"):
                best = ("2", r2["shape"], r2["P"], r2["T"], r2["cmp"], regions)
                refs = sorted(r2.get("refs") or [])

    if best is None:
        rep["error"] = "No layer produced a valid solid."
        return _finish(rep, out, name, t0)
    lay, shape, P, T, cmp, regs = best
    _step(shape, out / f"{name}.step")
    vol = solid.check(shape)["volume_mm3"]
    # what the surfaces are (Layer 1's split; a gear found first is all recipe), and for a recipe how much of the
    # area its Params drive
    area = rep["layers"]["1"] if lay in ("1", "2") else None
    if lay == "2" and (area or {}).get("skipped"):
        par, ff = 100.0, 0.0
    else:
        par = (area or {}).get("parametric_area_pct", 0.0)
        ff = (area or {}).get("freeform_area_pct", 0.0)
    rep["layer_achieved"] = int(lay)
    rep["result"] = {"layer": int(lay), "step": f"{name}.step", "recipe": f"{name}_recipe.py" if recipe else None,
                     "recipe_references": refs if lay == "2" else [],
                     "recipe_verified": bool(lay == "2"), "volume_mm3": round(vol, 4), "mesh_volume_mm3": round(mvol, 4),
                     "volume_delta_mm3": round(vol - mvol, 4), "volume_delta_pct": round(100 * (vol - mvol) / mvol, 5) if mvol else None,
                     "hausdorff_mm": round(cmp["hausdorff_mm"], 6), "parametric_area_pct": par, "freeform_area_pct": ff,
                     "frozen_area_pct": round(max(0.0, 100.0 - par - ff), 2),
                     "driven_by_params_pct": rep["layers"]["2"].get("driven_by_params_pct") if lay == "2" else 0.0}
    dmap = verify.deviation_map(P, T, cmp["_rec_dev"], tol)
    (out / f"{name}_deviation.json").write_text(json.dumps(dmap), encoding="utf-8")
    rep["result"]["deviation_map"] = f"{name}_deviation.json"
    return _finish(rep, out, name, t0)


def _gear(V, F, tol, name, say):
    """The parametric spur gear of the mesh, or None when the mesh is not one (checked about its principal axes)."""
    from . import gears
    c = V.mean(axis=0)
    _, _, vt = np.linalg.svd(V - c, full_matrices=False)
    for d in vt[::-1]:
        try:
            g, _ = gears.analyse(V, F, d, tol)
        except Exception:                               # noqa: BLE001
            continue
        if g is not None and g["flank_fit_mm"] <= max(3 * tol, 0.05 * g["module"]):
            say({"stage": "layer2", "text": f"A spur gear: {g['teeth']} teeth; building it as a parametric gear", "fraction": 0.3})
            try:
                return gears.recipe(V, F, [d], tol, name=name)
            except Exception as e:                      # noqa: BLE001
                return {"report": {"method": "spur gear", "error": f"{type(e).__name__}: {e}"[:300]}}
    return None


def layer2(V, F, regions, l1shape, tol, name, out, l1rep, progress=None, deadline=None) -> dict:
    """The best verified recipe: the feature tree (tree.py) first, the single extrusion or revolution (features.py)
    when the tree is not within the limit. Both are reported."""
    from . import features, tree
    limit = max(tol, l1rep.get("hausdorff_mm", 0.0) * 1.05)
    say = progress or (lambda d: None)
    tried = []
    try:
        t = tree.recipe(V, F, l1shape, tol, name=name, limit=limit, out_dir=out,
                        progress=lambda d: say({**d, "fraction": 0.8 * d.get("fraction", 0)}), deadline=deadline)
    except Exception as e:                              # noqa: BLE001
        t = {"report": {"method": "feature tree", "error": f"{type(e).__name__}: {e}"[:300]}}
    tried.append(t)
    if not t.get("verified") and (deadline is None or time.perf_counter() < deadline):
        try:
            f = features.recipe(V, F, regions, tol, name=name, limit=limit,
                                progress=lambda d: say({**d, "fraction": 0.8 + 0.2 * d.get("fraction", 0)}))
            f["report"]["method"] = "single extrusion or revolution"
        except Exception as e:                          # noqa: BLE001
            f = {"report": {"method": "single extrusion or revolution", "error": f"{type(e).__name__}: {e}"[:300]}}
        tried.append(f)
    best = next((r for r in tried if r.get("verified")), None) or next((r for r in tried if r.get("source")), tried[0])
    rep = dict(best["report"])
    others = [r["report"] for r in tried if r is not best]
    if others:
        rep["also_tried"] = [{k: o.get(k) for k in ("method", "base", "kind", "verified", "hausdorff_mm", "error") if o.get(k) is not None}
                             for o in others]
    return {**best, "report": rep}


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
    if reg.kind == "bspline":                       # the flat facet's middle against the smooth surface: its chord error
        a, b, c = V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]]
        sag = np.max(np.abs(np.c_[reg.prim.dist((a + b + c) / 3), reg.prim.dist((a + b) / 2), reg.prim.dist((b + c) / 2),
                                  reg.prim.dist((c + a) / 2)]), axis=1)
        return tol + 1.25 * sag
    from .segment import chord_error
    ce = chord_error(reg.prim, V[F[tris, 0]], V[F[tris, 1]], V[F[tris, 2]])
    return tol + (np.minimum(ce, chord * 1.25) if chord is not None else ce)


def _layer1(V, F, tol, budget_s, progress):
    from . import brep, segment, solid
    t0 = time.perf_counter()
    regions, st = segment.segment(V, F, tol, budget_s=budget_s, progress=progress)
    from . import freeform
    try:
        regions, st["freeform"] = freeform.apply(V, F, regions, tol, progress=progress)
    except Exception as e:                              # noqa: BLE001
        st["freeform"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    rounds = []
    cmp = None
    for attempt in range(5):
        shape, info = brep.build(V, F, regions, tol, progress=progress)
        frozen = []
        partial = {}                                    # region id -> its triangles that are off the surface
        if shape is None or not info.get("valid"):
            ids = sorted({f["region"] for f in info.get("face_failures", [])} | set(info.get("free_edge_regions", [])))
            if shape is not None and not ids:
                ids = brep.bad_regions(shape, regions, V, F)
            if not ids:                                 # no face to blame: the B-spline patches go first
                ids = [r.id for r in regions if r.kind == "bspline"]
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
                off = dev[r.tris] > _allowance(V, F, r.tris, r, tol, chord)
                if r.parametric and np.any(off):
                    frozen.append(r.id)
                    if r.kind == "plane" and attempt < 3:         # a plane keeps the triangles that are on it
                        partial[r.id] = r.tris[off]
        rounds.append({"build": {k: info[k] for k in ("faces", "valid", "edges_line", "edges_circle", "edges_arc", "edges_segment")
                                 if k in info}, "hausdorff_mm": round(cmp["hausdorff_mm"], 6) if cmp else None,
                       "frozen_regions": [{"id": i, "kind": regions[i].kind} for i in frozen]})
        if not frozen:
            break
        regions = _freeze(V, F, regions, frozen, partial)
        shape = None
    summ = segment.summary(regions)
    rep = {**summ, "segmentation": st, "rounds": rounds,
           "surfaces": [{"kind": r.kind, "triangles": int(len(r.tris)), "area_mm2": round(r.area, 4), **(r.prim.public() if r.prim else {})}
                        for r in sorted(regions, key=lambda r: -r.area) if r.parametric][:300]}
    if shape is None or cmp is None or not rounds or rounds[-1].get("frozen_regions"):
        rep["error"] = "The analytic faces did not close into a valid solid; Layer 0 is the result."
        rep["seconds"] = round(time.perf_counter() - t0, 2)
        return {"report": rep}
    vol = solid.check(shape)["volume_mm3"]
    rep.update({"valid": True, "volume_mm3": round(vol, 4), **_round(cmp), "seconds": round(time.perf_counter() - t0, 2)})
    return {"report": rep, "shape": shape, "regions": regions, "P": P, "T": T, "cmp": cmp}


def _freeze(V, F, regions, ids, partial=None):
    """Turn regions into frozen facets, one per triangle, and renumber. A region in `partial` freezes only the given
    triangles; the rest keep its surface, one region per connected piece (a plane with a bad corner stays a plane)."""
    from .segment import Region
    _, A = meshmod.tri_normals(V, F)
    ids = set(ids)
    partial = partial or {}
    out = []
    for r in regions:
        if r.id in ids and r.id in partial and len(partial[r.id]) < len(r.tris):
            bad = set(partial[r.id].tolist())
            good = np.array([t for t in r.tris.tolist() if t not in bad])
            out += [Region(0, "facet", np.array([t]), None, float(A[t])) for t in sorted(bad)]
            for piece in _pieces(F, good):
                out.append(Region(0, r.kind, piece, r.prim, float(A[piece].sum()), dict(r.info)))
        elif r.id in ids:
            out += [Region(0, "facet", np.array([t]), None, float(A[t])) for t in r.tris.tolist()]
        else:
            out.append(r)
    for i, r in enumerate(out):
        r.id = i
    return out


def _pieces(F, tris):
    """Triangles split into pieces connected through shared edges."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    tris = np.asarray(tris)
    if len(tris) < 2:
        return [tris] if len(tris) else []
    sub = F[tris]
    E = np.sort(np.concatenate([sub[:, [0, 1]], sub[:, [1, 2]], sub[:, [2, 0]]]), axis=1)
    owner = np.tile(np.arange(len(tris)), 3)
    _, inv = np.unique(E, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    o = np.argsort(inv, kind="stable")
    a, b = owner[o][:-1], owner[o][1:]
    same = inv[o][1:] == inv[o][:-1]
    g = coo_matrix((np.ones(int(same.sum())), (a[same], b[same])), shape=(len(tris), len(tris)))
    k, lab = connected_components(g, directed=False)
    return [tris[lab == i] for i in range(k)]
