"""Designs written in OpenSCAD. FORM runs `openscad -o part.stl -D key=value ...` and brings the mesh into the pipeline.

OpenSCAD's output is a triangle mesh, not a boundary representation. What that means in FORM, stated wherever it
matters: no STEP export, no B-rep validity check, no per-feature attribution (the whole part is one feature), and
no FreeCAD re-check (it needs a STEP). Volume, the closed-mesh check, wall thickness by ray casting on the mesh,
overhangs, build volume and the slice all run on the real triangles.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .base import Feature, Param, Recipe, RecipeError, Stage

SCAD_PREFIX = "scad:"
MESH_NOTES = [
    "OpenSCAD produces a triangle mesh, not a CAD solid, so there is no STEP file for this design.",
    "B-rep checks (OCCT solid validity, STL-against-CAD volume) are not available for mesh designs.",
    "The whole part is one feature: picking a face cannot name a feature, and impact cannot say which feature moved.",
    "FreeCAD re-import needs a STEP file, so it does not run for mesh designs.",
]


class ScadRecipe(Recipe):
    mesh = True
    language = "openscad"
    solids = 1

    def __init__(self, path: Path, rid: str):
        from ..cad_bridges import parse_scad_params, scad_title
        self.path, self.id = Path(path), rid
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise RecipeError(f"Design source {rid} is missing from the source store.", "",
                              "Restore the project's .sources folder, or submit the source again.")
        self.title, self.summary = scad_title(text)
        parsed = parse_scad_params(text)
        self.fixed = parsed["fixed"]
        self.params = [Param(p["key"], p["label"], p["default"], p["min"], p["max"], p["step"], p["unit"], "form", "body",
                             (f"OpenSCAD parameter{' in [' + p['group_name'] + ']' if p['group_name'] else ''}.")[:200])
                       for p in parsed["params"]]
        self.features = [Feature("body", "Body", "structure", "The OpenSCAD model as one mesh.")]
        if not self.params:
            raise RecipeError("This OpenSCAD file declares no parameters Form Studio can edit.", "",
                              "Give each editable top-level number a Customizer range comment, e.g. `width = 40; // [20:1:120]`.")

    def build(self, v):
        from ..cad_bridges import find_openscad, run_openscad
        from .meshsolid import read_stl_solid
        exe = find_openscad()
        if not exe:
            raise RecipeError("OpenSCAD is not installed, so this design cannot be built.", "body",
                              "Install OpenSCAD (https://openscad.org/downloads.html) or set [cad].openscad in studio.toml.")
        with tempfile.TemporaryDirectory(prefix="form-scad-") as d:
            out = Path(d) / "part.stl"
            try:
                run_openscad(exe, self.path, v, out)
                shape = read_stl_solid(out)
            except (RuntimeError, ValueError) as e:
                raise RecipeError(str(e), "body", "Fix the OpenSCAD source or step back to values that rendered.")
        return [Stage("body", shape)]

    def public(self) -> dict:
        out = super().public()
        out.update({"mesh": True, "language": "openscad", "notes": MESH_NOTES,
                    "fixed_in_source": [f"{f['key']} ({f['why']})" for f in self.fixed]})
        return out
