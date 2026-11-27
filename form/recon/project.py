"""Mesh to editable CAD inside Form Studio: run the reconstruction in the kernel, make a design from the result.

Engine side (no OCCT here). The kernel op writes the files; this module turns them into a project:

- a verified Layer 2 recipe becomes the design's source (Params with provenance "mesh": computed from the mesh);
- otherwise the best verified solid (Layer 1 hybrid or Layer 0) becomes a reference part, and the design is a short
  source that reads it, so features can be added on top in build123d.

The report, the deviation map, the Layer 0 solid and any recipe are kept in the project's `reconstruction` folder, and
the original mesh is imported as a reference part so it can be compared in the viewport.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np

from .mesh import FORMATS

WRAPPER = '''"""{title}: the solid reconstructed from {file} (Layer {layer}). Form Studio.

{summary}
Add features in build(): cut, add or fillet the body like any build123d solid.
"""
from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = {title!r}
    summary = "Solid reconstructed from a mesh; edit it by adding features in build()."
    params = [Param("scale_pct", "Scale", 100, 1, 1000, 0.1, "%", "form", "body", "100 = the size of the mesh.")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        body = self.reference({step!r})
        if abs(v["scale_pct"] - 100) > 1e-9:
            body = body.scale(v["scale_pct"] / 100)
        return [Stage("body", body)]
'''


EDITABLE_TITLE_PCT = 50.0   # "(editable)" only when at least half the Params are dimensions a person can change


def title_for(stem: str, res: dict) -> str:
    """The new design's name says what it is: "(editable)" when at least EDITABLE_TITLE_PCT % of its Params are real
    dimensions that move (at that point most of what the person sees in Params is a size they can change),
    "(partly editable)" when some are, else "(exact copy)"."""
    edit = float(res.get("editable_pct") or 0.0)
    if res.get("recipe_verified") and edit >= EDITABLE_TITLE_PCT:
        return f"{stem} (editable)"
    if res.get("recipe_verified") and edit > 0:
        return f"{stem} (partly editable)"
    return f"{stem} (exact copy)"


def headline(res: dict, tol: float | None = None) -> str:
    """The one line every surface shows first: how much of the part its Params drive, how far it is from the mesh,
    and whether that is within the tolerance asked for."""
    if res.get("headline"):
        return res["headline"]
    edit = res.get("editable_pct") or 0.0
    h = res.get("hausdorff_mm")
    line = f"{edit:g}% editable"
    if h is not None:
        line += f", {h:.4g} mm from the mesh"
        if tol is not None and h > tol + 1e-12:
            line += f", outside the {tol:g} mm asked for"
    return line


def summary(rep: dict) -> dict:
    """The few numbers worth showing, editable share and deviation first: then layer, the geometric split of the
    surface, holes, and why a layer was not reached."""
    res = rep.get("result") or {}
    L = rep.get("layers", {})
    edit = res.get("editable_pct")
    dims = res.get("dimensions") or {}
    out = {"headline": headline(res, rep.get("tolerance_mm")) if res else None, "editable_pct": edit,
           "hausdorff_mm": res.get("hausdorff_mm"), "within_tolerance": res.get("within_tolerance"),
           "feature_area_pct": res.get("feature_area_pct", res.get("driven_by_params_pct")),
           "dimension_params": dims.get("movable"), "dimensions_total": dims.get("dimensions"),
           "params_total": dims.get("params"),
           "layer": rep.get("layer_achieved"), "layer_requested": rep.get("layer_requested"), "tolerance_mm": rep.get("tolerance_mm"),
           "volume_delta_pct": res.get("volume_delta_pct"), "method": res.get("method"), "params": res.get("params"),
           "parametric_area_pct": res.get("parametric_area_pct"), "freeform_area_pct": res.get("freeform_area_pct"),
           "frozen_area_pct": res.get("frozen_area_pct"), "driven_by_params_pct": res.get("driven_by_params_pct"),
           "recipe_verified": res.get("recipe_verified"), "repairs": rep.get("repairs", []), "seconds": rep.get("seconds"),
           "budget_s": rep.get("budget_s"), "brep_pct": res.get("brep_pct"),
           **({"cut_short": res["cut_short"], "note": res.get("note")} if res.get("cut_short") else {}),
           "evidence": "computed"}
    if "1" in L:
        out["layer1"] = {k: L["1"].get(k) for k in ("parametric_area_pct", "freeform_area_pct", "hausdorff_mm", "by_kind", "error",
                                                    "skipped") if L["1"].get(k) is not None}
    if "2" in L:
        l2 = L["2"]
        out["layer2"] = {k: l2.get(k) for k in ("method", "kind", "base", "verified", "hausdorff_mm", "editable_pct", "features",
                                                "holes", "patterns", "symmetry", "left_in_base", "kept", "regularised",
                                                "directions", "fit", "error", "params") if l2.get(k) is not None}
    if res.get("warning"):
        out["warning"] = res["warning"]
    if rep.get("error"):
        out["error"] = rep["error"]
    return {k: v for k, v in out.items() if v is not None or k in ("layer", "hausdorff_mm")}


ROUTES = ("auto", "parametric", "surface_body", "mesh_body")
UNITS = {"auto": 1.0, "mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}


def reconstruct(st, src, name: str | None = None, tolerance: float = 0.02, layer: int = 2, purpose: str | None = None,
                budget_s: float = 240.0, on_progress=None, route: str = "auto", scale: float = 1.0,
                units: str = "auto") -> dict:
    """A mesh file as a new design, by the route its triage chooses (form/triage.py). Returns {"project", "name",
    "summary", "files", "triage"}.

    route="auto": a mechanical or mixed part goes through the parametric reconstruction (verified against the mesh);
    an organic one becomes a surface body or a mesh body (form/sculpt.py); several bodies in one file become one
    design with a part each; a surface that does not close is refused with the next call to make. A route can be
    forced ("parametric", "surface_body", "mesh_body"). When the parametric route fails on a mesh that closes, the
    mesh body is made instead and the result says so. units: what the file's numbers are ("mm", "cm", "m", "in";
    "auto": millimetres, unless the size makes no sense in millimetres: then nothing is built and the one question to
    put to the person comes back as the refusal). scale: multiply the file's coordinates by a number instead."""
    from ..studio import StudioError
    from .. import triage as triage_mod
    src = Path(src).expanduser()
    if not src.is_file():
        raise StudioError(f"File not found: {src}", "Give the absolute path of an STL, OBJ or 3MF file.")
    if src.suffix.lower() not in FORMATS:
        if src.suffix.lower() in (".step", ".stp"):
            raise StudioError(f"{src.name} is already CAD (STEP): there is nothing to reconstruct.",
                              "Next: create_design(..., references=[path]) and use it with self.reference(name).",
                              next="cad_reference")
        raise StudioError(f"{src.name} is not a mesh Form Studio reads.", "Use an STL (binary or ASCII), OBJ or 3MF file.")
    if not (0.0005 <= float(tolerance) <= 5):
        raise StudioError("The tolerance must be between 0.0005 and 5 mm.")
    if int(layer) not in (0, 1, 2):
        raise StudioError("The layer must be 0, 1 or 2.")
    if route not in ROUTES:
        raise StudioError(f"Unknown route “{route}”.", "Use one of: " + ", ".join(ROUTES) + ".")
    if units not in UNITS:
        raise StudioError(f"Unknown units “{units}”.", "Use one of: " + ", ".join(UNITS) + ".")
    if units != "auto":
        scale = float(scale) * UNITS[units]
    if not (1e-6 <= float(scale) <= 1e6):
        raise StudioError("The scale must be a positive number (metres to millimetres: 1000).")
    say = on_progress or (lambda d: None)
    say({"stage": "triage", "text": f"Looking at {src.name}", "fraction": 0.0})
    try:
        tri = triage_mod.assess_mesh(src, float(tolerance))
    except (ValueError, OSError) as e:
        raise StudioError(f"Could not read {src.name} as a mesh: {e}", "Export it again as a binary STL, OBJ or 3MF.")
    chosen = tri["route"] if route == "auto" else route
    say({"stage": "triage", "text": f"{tri['class'].capitalize()} mesh: {chosen.replace('_', ' ')}", "fraction": 0.01})
    extra = {"triage": _triage_brief(tri, chosen)}
    if tri.get("ask") and units == "auto" and abs(float(scale) - 1.0) < 1e-12:
        # the size makes no sense in millimetres and nobody said what the units are: every dimension of the result
        # depends on the answer, so nothing is built on a guess
        q = tri["ask"]
        raise StudioError(q["question"],
                          "Put this one question to the person (ask_user, choices: " + ", ".join(q["choices"]) + "), then "
                          "call reconstruct again with units=\"m\" (or \"cm\", \"in\"), or units=\"mm\" when they "
                          "confirm millimetres. Do not ask anything else first.",
                          next="ask_units", ask=q, triage=extra["triage"])
    if chosen == "reference_only" or (not tri["facts"]["after_repair"]["closed"] and chosen != "parametric"):
        raise StudioError(tri["why"] if tri["route"] == "reference_only" else
                          f"{src.name} does not close into a body, so it cannot be a {chosen.replace('_', ' ')}.",
                          "Do not call reconstruct again with this file: the safe repairs already ran. Next: "
                          "import_reference(project, path) keeps it as a reference to design around (create_design first "
                          "when there is no project); tell the person the surface is open and what that leaves out.",
                          next="reference_only", triage=extra["triage"])
    if chosen in ("surface_body", "mesh_body"):
        from .. import sculpt
        out = sculpt.make(st, src, name=name, route=chosen, tolerance=float(tolerance), purpose=purpose,
                          budget_s=min(float(budget_s), sculpt.BUDGET_S), on_progress=on_progress, scale=float(scale),
                          tri=tri)
        return {**out, **extra}
    if chosen == "assembly":
        return {**_bodies(st, src, tri, name, tolerance, layer, purpose, budget_s, on_progress, scale), **extra}
    try:
        out = _parametric(st, src, tri, name, tolerance, layer, purpose, budget_s, on_progress, scale)
    except StudioError as e:
        if route != "auto" or not tri["facts"]["after_repair"]["closed"] or e.extra.get("kind") == "cancelled":
            raise
        # the parametric route did not reach a result on a mesh that closes: the mesh body is safe, and says why
        from .. import sculpt
        say({"stage": "triage", "text": "No parametric result: keeping it as a mesh body", "fraction": 0.5})
        out = sculpt.make(st, src, name=name, route="mesh_body", tolerance=float(tolerance), purpose=purpose,
                          on_progress=on_progress, scale=float(scale), tri=tri)
        out["summary"]["fell_back_from"] = {"route": "parametric", "error": str(e)[:300]}
        out["summary"]["headline"] = ("The parametric reconstruction did not reach a result, so the part is kept as a "
                                      "mesh body (not editable CAD). " + out["summary"]["headline"])
        extra["triage"]["taken"] = "mesh_body"
    return {**out, **extra}


def _triage_brief(tri: dict, chosen: str) -> dict:
    f = tri["facts"]
    return {"class": tri["class"], "route": tri["route"], "taken": chosen, "why": tri["why"], "cannot": tri["cannot"],
            "alternates": tri["alternates"], "prepare": tri["prepare"], "triangles": f["triangles"], "size_mm": f["size_mm"],
            "mechanical_pct": f["mechanical_pct"], "as_given": f["as_given"], "after_repair": f["after_repair"],
            "units": f["units"], "bodies": f["bodies"], "genus": f["genus"], "seconds": tri["seconds"]}


def _prepared(src: Path, tri: dict, tolerance: float, scale: float, folder: Path) -> tuple[Path, list]:
    """The file the parametric route reads: the file itself, or a prepared copy of it (scaled, and a heavy mesh
    simplified within a quarter of the tolerance with the deviation measured). Returns (path, what was done)."""
    from .. import meshrepair, triage as triage_mod
    from . import mesh as meshmod
    heavy = tri["facts"]["after_repair"]["triangles"] > triage_mod.PARAMETRIC_TRIANGLES
    if not heavy and abs(scale - 1.0) < 1e-12:
        return src, []
    done = []
    T, _info = meshmod.read_triangles(src)
    if abs(scale - 1.0) > 1e-12:
        T = T * scale
        done.append({"repair": "scaled", "factor": scale})
    V, F, _w = meshmod.weld(T, 1e-6)
    if heavy:
        V, F, _r, top = meshrepair.repair(V, F)
        if top["closed"]:
            V, F, wc = meshrepair.working_copy(V, F, triage_mod.PARAMETRIC_TRIANGLES, tol=tolerance / 4, max_tol=tolerance / 4)
            if wc.get("simplified"):
                wc["repair"] = "simplified before reconstruction"
                done.append(wc)
    dst = folder / (re.sub(r"[^A-Za-z0-9_\-]+", "_", src.stem).strip("_")[:50] + ".stl")
    meshmod.write_stl(dst, V, F, "Form Studio prepared mesh")
    return dst, done


def _bodies(st, src, tri, name, tolerance, layer, purpose, budget_s, on_progress, scale) -> dict:
    """A file that holds several separate closed bodies: one design with one part per body (form/multipart.py)."""
    from .. import meshrepair, multipart
    from . import mesh as meshmod
    (st.root / ".recon").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="bodies-", dir=st.root / ".recon"))
    try:
        T, _info = meshmod.read_triangles(src)
        V, F, _w = meshmod.weld(T * scale if abs(scale - 1.0) > 1e-12 else T, 1e-6)
        V, F, repairs, top = meshrepair.repair(V, F, cap_planar=True, drop_debris=True)
        lab = top["_piece_of"]
        area = np.bincount(lab, weights=meshmod.tri_normals(V, F)[1])
        stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", src.stem).strip("_")[:40] or "mesh"
        files = []
        for k, i in enumerate(np.argsort(-area)):
            if area[i] < 0.02 * area.sum():
                continue
            Fi = F[lab == i]
            used = np.unique(Fi)
            remap = -np.ones(len(V), np.int64)
            remap[used] = np.arange(len(used))
            f = work / f"{stem}_body{k + 1}.stl"
            meshmod.write_stl(f, V[used], remap[Fi], "Form Studio body")
            files.append(f)
        out = multipart.reconstruct_parts(st, files, name=name, tolerance=tolerance, layer=layer, purpose=purpose,
                                          budget_s=budget_s, on_progress=on_progress)
        out["split"] = {"from": src.name, "bodies": len(files), "repairs": [r["repair"] for r in repairs]}
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _parametric(st, src, tri, name, tolerance, layer, purpose, budget_s, on_progress, scale) -> dict:
    """The parametric reconstruction (the kernel's "reconstruct" op) as a new design."""
    from ..studio import StudioError
    orig = src
    (st.root / ".recon").mkdir(parents=True, exist_ok=True)
    prep = Path(tempfile.mkdtemp(prefix="prep-", dir=st.root / ".recon"))
    try:
        src, prepared = _prepared(orig, tri, float(tolerance), float(scale), prep)
        out = _run(st, src, orig, name, tolerance, layer, purpose, budget_s, on_progress)
        if prepared:
            out["summary"]["prepared"] = prepared
            out["summary"]["repairs"] = prepared + list(out["summary"].get("repairs") or [])
        return out
    finally:
        shutil.rmtree(prep, ignore_errors=True)


def _run(st, src, orig, name, tolerance, layer, purpose, budget_s, on_progress) -> dict:
    from ..studio import StudioError
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", src.stem).strip("_")[:50] or "mesh"
    (st.root / ".recon").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="recon-", dir=st.root / ".recon"))
    try:
        rep = st._k("reconstruct", timeout=float(budget_s) * 1.5 + 120, on_progress=on_progress, path=str(src.resolve()),
                    out_dir=str(work), name=stem, tolerance=float(tolerance), layer=int(layer), budget_s=float(budget_s))
        res = rep.get("result")
        if not res:
            raise StudioError(rep.get("error") or "The mesh could not be reconstructed.", rep.get("hint", ""),
                              **({"next": rep["next"]} if rep.get("next") else {}))
        summ = summary(rep)
        title = (name or title_for(orig.stem, res)).strip()
        brief = (f"Reconstructed from the mesh {orig.name}: {headline(res, float(tolerance))} (two-sided Hausdorff, computed). "
                 f"Layer {res['layer']}" + (f", {res['method']}" if res.get("method") else "")
                 + f"; geometry: {res['parametric_area_pct']:g}% of the area on planes, cylinders, cones, spheres or tori"
                 + (f", {res['freeform_area_pct']:g}% freeform" if res.get("freeform_area_pct") else "")
                 + (f", {res['frozen_area_pct']:g}% the mesh's own facets" if res.get("frozen_area_pct") else "") + ".")
        if res.get("recipe_verified"):
            refs = [str(work / r) for r in res.get("recipe_references") or []]
            p = st.create_design(title, (work / res["recipe"]).read_text(encoding="utf-8"), brief=brief, purpose=purpose,
                                 references=refs or None)
        else:
            step = work / res["step"]
            text = WRAPPER.format(title=title, file=orig.name, layer=res["layer"], step=res["step"],
                                  summary=brief + (" " + summ["layer2"]["error"] if summ.get("layer2", {}).get("error") else ""))
            p = st.create_design(title, text, brief=brief, references=[str(step)], purpose=purpose)
        keep = st.dir(p["id"]) / "reconstruction"
        keep.mkdir(parents=True, exist_ok=True)
        files = []
        for f in sorted(work.iterdir()):
            shutil.copyfile(f, keep / f.name)
            files.append(f.name)
        try:                                           # the mesh itself, drawn in blueprint for comparison
            st.import_reference(p, orig)
        except StudioError:
            pass
        with st.lock(p["id"]):
            p = st.load(p["id"])
            p["reconstruction"] = {"from": orig.name, "ts": time.time(), "summary": summ, "files": files}
            st.decide(p, "reconstruct", brief + (f" Repairs: {len(summ['repairs'])} (listed in the report)." if summ["repairs"] else ""))
            st.save(p)
        st.activity(p["id"], "reconstruct", brief, by="engine")
        return {"project": p["id"], "name": p["name"], "summary": summ, "files": files, "folder": str(keep)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def reconstruct_reference(st, p: dict, file: str, **kw) -> dict:
    """"Make editable": reconstruct a mesh imported as a reference part of project p as its own design."""
    from ..studio import StudioError
    refs = {r["file"]: r for r in st.references(p)}
    if file not in refs:
        raise StudioError(f"There is no reference part “{file}” in this project.", "Import the mesh first (Brief > Import part).")
    if Path(file).suffix.lower() not in FORMATS:
        raise StudioError(f"{file} is already CAD (STEP); only meshes need reconstructing.")
    kw.setdefault("name", f"{Path(file).stem} (editable)")
    return reconstruct(st, st.dir(p["id"]) / "references" / file, **kw)
