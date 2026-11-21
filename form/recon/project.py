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


def reconstruct(st, src, name: str | None = None, tolerance: float = 0.02, layer: int = 2, purpose: str | None = None,
                budget_s: float = 240.0, on_progress=None) -> dict:
    """Reconstruct a mesh file as a new design. Returns {"project", "name", "summary", "files"}."""
    from ..studio import StudioError
    src = Path(src).expanduser()
    if not src.is_file():
        raise StudioError(f"File not found: {src}", "Give the absolute path of an STL, OBJ or 3MF file.")
    if src.suffix.lower() not in FORMATS:
        raise StudioError(f"{src.name} is not a mesh Form Studio reads.", "Use an STL (binary or ASCII), OBJ or 3MF file.")
    if not (0.0005 <= float(tolerance) <= 5):
        raise StudioError("The tolerance must be between 0.0005 and 5 mm.")
    if int(layer) not in (0, 1, 2):
        raise StudioError("The layer must be 0, 1 or 2.")
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", src.stem).strip("_")[:50] or "mesh"
    (st.root / ".recon").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="recon-", dir=st.root / ".recon"))
    try:
        rep = st._k("reconstruct", timeout=float(budget_s) * 1.5 + 120, on_progress=on_progress, path=str(src.resolve()),
                    out_dir=str(work), name=stem, tolerance=float(tolerance), layer=int(layer), budget_s=float(budget_s))
        res = rep.get("result")
        if not res:
            raise StudioError(rep.get("error") or "The mesh could not be reconstructed.", rep.get("hint", ""))
        summ = summary(rep)
        title = (name or title_for(src.stem, res)).strip()
        brief = (f"Reconstructed from the mesh {src.name}: {headline(res, float(tolerance))} (two-sided Hausdorff, computed). "
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
            text = WRAPPER.format(title=title, file=src.name, layer=res["layer"], step=res["step"],
                                  summary=brief + (" " + summ["layer2"]["error"] if summ.get("layer2", {}).get("error") else ""))
            p = st.create_design(title, text, brief=brief, references=[str(step)], purpose=purpose)
        keep = st.dir(p["id"]) / "reconstruction"
        keep.mkdir(parents=True, exist_ok=True)
        files = []
        for f in sorted(work.iterdir()):
            shutil.copyfile(f, keep / f.name)
            files.append(f.name)
        try:                                           # the mesh itself, drawn in blueprint for comparison
            st.import_reference(p, src)
        except StudioError:
            pass
        with st.lock(p["id"]):
            p = st.load(p["id"])
            p["reconstruction"] = {"from": src.name, "ts": time.time(), "summary": summ, "files": files}
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
