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


def summary(rep: dict) -> dict:
    """The few numbers worth showing: layer, accuracy, parametric share, holes, and why a layer was not reached."""
    res = rep.get("result") or {}
    L = rep.get("layers", {})
    out = {"layer": rep.get("layer_achieved"), "layer_requested": rep.get("layer_requested"), "tolerance_mm": rep.get("tolerance_mm"),
           "hausdorff_mm": res.get("hausdorff_mm"), "volume_delta_pct": res.get("volume_delta_pct"),
           "parametric_area_pct": res.get("parametric_area_pct"), "frozen_area_pct": res.get("frozen_area_pct"),
           "recipe_verified": res.get("recipe_verified"), "repairs": rep.get("repairs", []), "seconds": rep.get("seconds"),
           "evidence": "computed"}
    if "1" in L:
        out["layer1"] = {k: L["1"].get(k) for k in ("parametric_area_pct", "hausdorff_mm", "by_kind", "error") if L["1"].get(k) is not None}
    if "2" in L:
        l2 = L["2"]
        out["layer2"] = {k: l2.get(k) for k in ("kind", "verified", "hausdorff_mm", "holes", "patterns", "symmetry", "error", "params")
                         if l2.get(k) is not None}
    if rep.get("error"):
        out["error"] = rep["error"]
    return out


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
        title = (name or f"{src.stem} (editable)").strip()
        brief = (f"Reconstructed from the mesh {src.name}: Layer {res['layer']}, two-sided Hausdorff distance "
                 f"{res['hausdorff_mm']:.4g} mm, {res['parametric_area_pct']:g}% of the area parametric (computed).")
        if res.get("recipe_verified"):
            p = st.create_design(title, (work / res["recipe"]).read_text(encoding="utf-8"), brief=brief, purpose=purpose)
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
