"""The organic route of "make editable": a sculpted or scanned mesh as a design, within a time limit.

form/triage.py sends a mesh here when it is organic (a figure, a scan, a sculpt): there are no sketches and holes to
read off it, so the parametric reconstruction (form/recon) would spend its whole budget to return an exact copy with
nothing to edit. Two results are possible instead, and the report says which one was reached and how far it is from
the file (measured, never assumed):

    surface body  one closed body without handles and without sharp detail: a closed quad cage fitted to the mesh,
                  its limit surface as exact NURBS faces (form/meshbody.organic_solid). The design holds the cage; it
                  exports STEP. The cage grows (CAGES) until the surface is within the tolerance or the time is up; a
                  fit that is not within the tolerance is not offered: the mesh body is.
    mesh body     everything else: the repaired mesh (a lighter working copy when it is heavy) is the body, closed,
                  with a Scale and a Flat base parameter (one feature, so a rebuild stays fast), and exact CAD features are cut into it or added
                  (form.meshbody.MeshBody). It exports STL and 3MF, not STEP.

`op_sculpt` runs in the kernel worker (it writes the body's files and the report); `make` is the engine side: it calls
the op, writes the design's source and creates the project. The original file is imported as a reference part beside
the design, unchanged, so both can be compared in the viewport.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

CAGES = ((3, 6.0), (5, 10.0), (8, 26.0), (12, 62.0))   # (cage size, seconds it takes on a 45,000-triangle mesh, about)
FIT_TRIANGLES = 45_000       # the surface is fitted to a copy of at most this many triangles (and verified on it)
SURFACE_TOL_FRAC = 1e-3      # a surface body is accepted within this share of the part's size (or the tolerance asked)
SURFACE_BUDGET_S = 75.0      # seconds the surface fit may take in all
BUDGET_S = 150.0

MESH_SOURCE = '''"""{title}: the mesh {file} as a body you can scale, flatten and cut. Form Studio.

{summary}
The body is a triangle mesh, not CAD surfaces: it exports STL and 3MF, not STEP. Exact CAD features go in build():
    body.cut(Pos(0, 0, 20) * Cylinder(5, 60), "hole")     a build123d shape cut out of the mesh, exactly
    body.add(shape, "boss")                               a shape joined to it
    body.trim((0, 0, z), (0, 0, 1))                       everything below a plane removed, the cut closed flat
"""
from form.meshbody import MeshBody
from form.recipes.base import Feature, Param, Recipe, Stage

BODY = {stl!r}                      # the repaired working copy of {file}, a reference part of this design
Z0, HEIGHT = {z0!r}, {height!r}     # where the body starts and how tall it is, as given (mm)


class Design(Recipe):
    mesh = True                     # a triangle mesh: no STEP, no B-rep checks
    crease_deg = 62                 # only real edges are drawn as lines (folds and hair are shading, not linework)
    title = {title!r}
    summary = "A sculpted mesh body: scale it, give it a flat base, cut exact features into it."
    params = [
        Param("scale_pct", "Scale", 100, 1, 1000, 0.1, "%", "form", "body", "100 = the size of the file."),
        Param("base_cut", "Flat base", 0, 0, {cut_max!r}, {cut_step!r}, "mm", "form", "body",
              "Cut this much off the bottom (at the size of the file) so it stands on a flat face. 0 = as given."),
    ]
    features = [Feature("body", "Body", "structure", "The mesh, repaired and closed, with its exact cuts.")]

    def build(self, v):
        body = MeshBody.load(BODY)
        if v["base_cut"] > 1e-9:                    # in the file's own millimetres, before scaling
            body.trim((0, 0, Z0 + v["base_cut"]), (0, 0, 1), "flat base")
        s = v["scale_pct"] / 100
        if abs(s - 1) > 1e-9:
            body.scale(s, about=(0, 0, Z0))
        return [Stage("body", body.solid())]
'''

SURFACE_SOURCE = '''"""{title}: the mesh {file} as a smooth NURBS solid with a cage you can edit. Form Studio.

{summary}
CAGE holds the control points (V) and quads (F) of the fitted cage: move points to reshape the body. Exact CAD
features go in build() like on any build123d solid (body - Cylinder(...), split, fillet).
"""
import numpy as np

from form import meshsource
from form.craft import subd
from form.recipes.base import Feature, Param, Recipe, Stage

{cage}

class Design(Recipe):
    title = {title!r}
    summary = "A sculpted body as exact NURBS faces over a quad cage; edit the cage or add features."
    params = [Param("scale_pct", "Scale", 100, 1, 1000, 0.1, "%", "form", "body", "100 = the size of the file.")]
    features = [Feature("body", "Body", "structure", "The cage's limit surface as a closed solid.")]

    def build(self, v):
        body = subd.Cage(np.asarray(CAGE.V) * (v["scale_pct"] / 100), CAGE.F).solid(label="body", merge=False)
        return [Stage("body", body)]                # one face per cage quad: the solid the distance was measured on
'''


# ---- kernel side -----------------------------------------------------------------------------------------------------

def _fit_child(V, F, tol, cage, progress=None):
    """One surface fit (in the bounded helper): the cage and the measured report, nothing that cannot be pickled."""
    from . import meshbody
    _solid, rep = meshbody.organic_solid((V, F), tol=tol, kind="closed", cage=cage)
    cg = rep.pop("cage_obj")
    return {"V": np.asarray(cg.V), "F": np.asarray(cg.F), "report": {k: v for k, v in rep.items() if k != "cages"}}


def op_sculpt(path, out_dir, name=None, route="mesh_body", tolerance=0.02, budget_s=BUDGET_S, scale=1.0):
    """Kernel op: a sculpted mesh file as a body, into out_dir. Writes <name>_body.stl (the repaired working copy),
    <name>_report.json and, for a surface body, <name>_cage.json. Returns the report."""
    from . import kernel, meshrepair
    from .recon import bounded
    from .recon import mesh as meshmod
    t0 = time.perf_counter()
    say = kernel.PROGRESS or (lambda d: None)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = Path(path)
    name = name or path.stem
    say({"stage": "read", "text": f"Reading {path.name}", "fraction": 0.02})
    T, info = meshmod.read_triangles(path)
    if abs(float(scale) - 1.0) > 1e-12:
        T = T * float(scale)
    V, F, w = meshmod.weld(T, 1e-6)
    del T
    n_in = int(info.get("triangles_in", len(F)))
    say({"stage": "repair", "text": f"{n_in:,} triangles: repairing", "fraction": 0.1})
    V, F, repairs, top = meshrepair.repair(V, F, cap_planar=True, drop_debris=True)
    rep = {"version": 1, "evidence": "computed", "file": path.name, "triangles_in": n_in, "scale": float(scale),
           "repairs": repairs, "tolerance_mm": float(tolerance), "route_asked": route, "budget_s": float(budget_s),
           "size_mm": [round(float(x), 4) for x in (V.max(axis=0) - V.min(axis=0))],
           "bbox": [V.min(axis=0).round(4).tolist(), V.max(axis=0).round(4).tolist()]}
    if not top["closed"]:
        rep["error"] = (f"{path.name} does not close into a body ({meshrepair.open_text(top)} after the safe repairs).")
        rep["hint"] = ("Do not call this again with the same file. Next: import_reference(project, path) keeps it as a "
                       "reference to design around.")
        rep["next"] = "reference_only"
        return _done(rep, out, name, t0)
    diag = float(np.linalg.norm(V.max(axis=0) - V.min(axis=0)))
    say({"stage": "copy", "text": "Making the working copy", "fraction": 0.25})
    W, G, wc = meshrepair.working_copy(V, F)
    rep["working_copy"] = wc
    rep["triangles"] = int(len(G))
    meshmod.write_stl(out / f"{name}_body.stl", W, G, "Form Studio mesh body")
    rep["body"] = f"{name}_body.stl"
    rep["volume_mm3"] = round(float(meshmod.topology(W, G)["volume_mm3"]), 1)
    dev = wc.get("deviation") or {"max_mm": 0.0, "mean_mm": 0.0, "p99_mm": 0.0, "points": 0,
                                  "evidence": "the body is the repaired mesh itself"}
    rep["result"] = {"route": "mesh_body", "tier": "mesh body (sculpted; CAD features exact)", "deviation": dev,
                     "hausdorff_mm": dev["max_mm"], "step": False}
    if route == "surface_body":
        accept = max(float(tolerance), SURFACE_TOL_FRAC * diag)
        Vf, Ff, _fc = meshrepair.working_copy(V, F, FIT_TRIANGLES, measure=False)
        hard = t0 + min(float(budget_s), SURFACE_BUDGET_S + (time.perf_counter() - t0))
        tried, best = [], None
        with bounded.session():
            for k, (cage, est) in enumerate(CAGES):
                left = hard - time.perf_counter()
                est_s = est * max(1.0, len(Ff) / 45_000)
                if left < 1.3 * est_s:
                    tried.append({"cage": cage, "skipped": f"needs about {est_s:.0f} s, {max(left, 0):.0f} s left"})
                    break
                say({"stage": "surface", "text": f"Fitting the surface (cage {cage})", "fraction": 0.3 + 0.15 * k})
                run = bounded.run(_fit_child, (Vf, Ff, accept, cage), timeout_s=left)
                if run["status"] not in ("ok", "unbounded"):
                    tried.append({"cage": cage, "status": run["status"], "error": run.get("error"), "seconds": run.get("seconds")})
                    break
                r = run["value"]["report"]
                tried.append({"cage": cage, "faces": r.get("faces"), "max_mm": r.get("max_mm"), "valid": r.get("valid"),
                              "closed": r.get("closed"), "seconds": r.get("seconds")})
                if r.get("valid") and r.get("closed") and (best is None or r["max_mm"] < best["report"]["max_mm"]):
                    best = run["value"]
                if best is not None and best["report"]["max_mm"] <= accept:
                    break
        rep["surface"] = {"accept_mm": round(accept, 4), "tried": tried, "fitted_to_triangles": int(len(Ff))}
        if best is not None and best["report"]["max_mm"] <= accept:
            r = best["report"]
            (out / f"{name}_cage.json").write_text(json.dumps({"V": np.round(best["V"], 5).tolist(), "F": best["F"].tolist()}),
                                                  encoding="utf-8")
            rep["cage"] = f"{name}_cage.json"
            rep["result"] = {"route": "surface_body", "tier": r["tier"], "hausdorff_mm": r["max_mm"],
                             "deviation": {"max_mm": r["max_mm"], "mesh_to_solid_max_mm": r["mesh_to_solid_max_mm"],
                                           "solid_to_mesh_max_mm": r["solid_to_mesh_max_mm"],
                                           "rms_mm": r["mesh_to_solid_rms_mm"], "points": r["verified_points"],
                                           "evidence": "computed (the solid against the mesh, both ways)"},
                             "faces": r["faces"], "cage": r["cage"], "smoothness": r.get("smoothness"), "step": True,
                             "volume_mm3": r.get("volume_mm3")}
        else:
            why = ("no fit finished in the time there was" if best is None else
                   f"the closest fit is {best['report']['max_mm']:g} mm from the mesh, more than the "
                   f"{accept:g} mm accepted")
            rep["surface"]["not_taken"] = f"The surface body was not taken: {why}. The mesh body is the result."
    return _done(rep, out, name, t0)


def _done(rep, out, name, t0):
    rep["seconds"] = round(time.perf_counter() - t0, 2)
    (Path(out) / f"{name}_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


KERNEL_OPS = {"sculpt": op_sculpt}


# ---- engine side -----------------------------------------------------------------------------------------------------

def headline(rep: dict) -> str:
    res = rep["result"]
    wc = rep.get("working_copy") or {}
    h = res["hausdorff_mm"]
    if res["route"] == "surface_body":
        s = (f"Surface body: {res['faces']} NURBS faces over a cage you can edit, {h:.4g} mm from the mesh "
             "(measured both ways)")
    else:
        s = f"Mesh body: {rep['triangles']:,} triangles, closed"
        s += (f"; a working copy of the file's {rep['triangles_in']:,}, at most {h:.4g} mm from it (measured)"
              if wc.get("simplified") else "; the file's own triangles")
        s += "; no dimensions to type in: Scale and Flat base are its parameters"
    if rep.get("repairs"):
        s += "; repaired: " + ", ".join(r["repair"] for r in rep["repairs"])
    return s


def summary(rep: dict, tri: dict | None = None) -> dict:
    res = rep.get("result") or {}
    out = {"headline": headline(rep) if res else None, "route": res.get("route"), "tier": res.get("tier"),
           "editable_pct": 0.0, "hausdorff_mm": res.get("hausdorff_mm"), "deviation": res.get("deviation"),
           "within_tolerance": None, "layer": None, "method": res.get("route"), "recipe_verified": False,
           "triangles_in": rep.get("triangles_in"), "triangles": rep.get("triangles"),
           "working_copy": rep.get("working_copy"), "repairs": rep.get("repairs", []), "step": res.get("step"),
           "volume_mm3": res.get("volume_mm3") or rep.get("volume_mm3"),
           "surface": rep.get("surface"), "seconds": rep.get("seconds"), "tolerance_mm": rep.get("tolerance_mm"),
           "evidence": "computed"}
    if tri:
        out["triage"] = {"class": tri.get("class"), "route": tri.get("route"), "why": tri.get("why"),
                         "cannot": tri.get("cannot"), "seconds": tri.get("seconds")}
    return {k: v for k, v in out.items() if v is not None or k in ("layer", "hausdorff_mm")}


def make(st, src, name: str | None = None, route: str = "mesh_body", tolerance: float = 0.02,
         purpose: str | None = None, budget_s: float = BUDGET_S, on_progress=None, scale: float = 1.0,
         tri: dict | None = None) -> dict:
    """A sculpted mesh file as a new design (a surface body or a mesh body). Returns what reconstruct returns:
    {"project", "name", "summary", "files", "folder"}."""
    from .studio import StudioError
    src = Path(src).expanduser()
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", src.stem).strip("_")[:50] or "mesh"
    (st.root / ".recon").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sculpt-", dir=st.root / ".recon"))
    try:
        rep = st._k("sculpt", timeout=float(budget_s) * 1.5 + 120, on_progress=on_progress, path=str(src.resolve()),
                    out_dir=str(work), name=stem, route=route, tolerance=float(tolerance), budget_s=float(budget_s),
                    scale=float(scale))
        res = rep.get("result")
        if not res:
            raise StudioError(rep.get("error") or "The mesh could not be made into a body.", rep.get("hint", ""),
                              next=rep.get("next"))
        summ = summary(rep, tri)
        brief = f"Made from the mesh {src.name}. {summ['headline']}."
        (lo, hi) = rep["bbox"]
        if res["route"] == "surface_body":
            title = (name or f"{src.stem} (surface body)").strip()
            cg = json.loads((work / rep["cage"]).read_text(encoding="utf-8"))
            cage = (f"CAGE = meshsource.cage(\n    V={json.dumps(cg['V'])},\n    F={json.dumps(cg['F'])},\n"
                    "    creases=[],\n    regions={})\n")
            text = SURFACE_SOURCE.format(title=title, file=src.name, summary=brief, cage=cage)
            p = st.create_design(title, text, brief=brief, purpose=purpose)
        else:
            title = (name or f"{src.stem} (mesh body)").strip()
            height = round(float(hi[2] - lo[2]), 4)
            text = MESH_SOURCE.format(title=title, file=src.name, summary=brief, stl=rep["body"], z0=round(float(lo[2]), 4),
                                      height=height, cut_max=round(max(height * 0.25, 0.1), 3),
                                      cut_step=round(max(height / 1000, 0.01), 3))
            p = st.create_design(title, text, brief=brief, purpose=purpose, references=[str(work / rep["body"])])
        keep = st.dir(p["id"]) / "reconstruction"
        keep.mkdir(parents=True, exist_ok=True)
        files = []
        for f in sorted(work.iterdir()):
            if f.suffix == ".stl":
                continue                                 # the body is already a reference part of the design
            shutil.copyfile(f, keep / f.name)
            files.append(f.name)
        try:                                             # the file itself, drawn in blueprint for comparison
            if abs(float(scale) - 1.0) < 1e-12:
                st.import_reference(p, src)
        except StudioError:
            pass
        with st.lock(p["id"]):
            p = st.load(p["id"])
            p["reconstruction"] = {"from": src.name, "ts": time.time(), "summary": summ, "files": files}
            st.decide(p, "reconstruct", brief)
            st.save(p)
        st.activity(p["id"], "reconstruct", brief, by="engine")
        return {"project": p["id"], "name": p["name"], "summary": summ, "files": files, "folder": str(keep)}
    finally:
        shutil.rmtree(work, ignore_errors=True)
