"""What an agent needs to write a FORM design: the contract, the rules, and an example that builds."""

GUIDE = """\
A FORM design is one Python file that defines one subclass of Recipe. FORM imports it, builds it in the
CAD kernel (build123d on OpenCascade), attributes every face to a feature, and runs the full pipeline:
renders, checks, fit model, slice, revisions, optimizer, animation, release.

CONTRACT
  from build123d import *                      # algebra API only: Box, Cylinder, Pos, Rot, Plane, fillet, ...
  from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

  class Design(Recipe):
      title, summary = "...", "..."
      solids = 1                               # separate printed bodies in the result (2 for case + lid)
      params = [Param(key, label, default, min, max, step, unit, group, feature, doc), ...]
      features = [Feature(id, label, role), ...]          # role: structure | interface | access | finish
      fit = None or {"cavity": derived_key, "mating": param_key, "clearance": param_key,
                     "label": "...", "per_side": True, "window": [min_gap, max_gap]}
      def constraints(self, v): return [RecipeError(msg, feature, hint, [param keys]), ...]
      def build(self, v): return [Stage(feature_id, whole_solid_after_this_feature), ...]
      def derived(self, v): return [{"key", "label", "value", "unit", "feature", "formula", "interface": bool}]
      def measure(self, v, faces_by_feature): return [{"key", "label", "intended", "modelled"}]   # read back off the solid
      def statics(self, v, volume_mm3, com): return {"some_metric": x, "checks": [{...}]}          # optional models
      def test_piece(self, v, shape): return (small_solid, {"label", "doc", "height"})              # optional

RULES
  1. Units: mm, degrees, grams. Every Param has a unit and a range. Integers use step=1 and unit "".
  2. group: "brief" = facts about the world (measure them; record provenance), "interface" = how parts
     meet (clearances), "form" = free design choices, "process" = printing assumptions.
  3. Use the build123d ALGEBRA API (Box(...), a + b, a - b, Pos(...) * shape). Do NOT use BuildPart/with-blocks:
     objects created inside an active builder silently join the part.
  4. Each Stage holds the WHOLE solid after that feature. Order matters: a face belongs to the last stage
     that created its surface. Give each feature its own stage so renders and impact can name it.
  5. Print orientation: model every part as it sits on the bed (flat face on z = 0). Put multiple parts
     side by side with at least 5 mm between them and set solids = N.
  6. Prefer chamfers on bottom edges and 45° ceilings over flat overhangs. Walls >= 1.2 mm (3 lines).
  7. Dimensions from datasheets or drawings (open them with read_document): put them in params with
     provenance="specified" and the source in doc ("Raspberry Pi 5 mechanical drawing"). Values the user
     measured: provenance="measured". Your own estimates stay "assumed". Say in your reply which you could not confirm.
  8. constraints() must catch every combination that would build something useless or invalid, naming the
     feature, the parameters, and a fix.
  9. After every create/update: render(view="sheet") and LOOK. Most mistakes are visible before any check.
 10. Fit: if something must slide in/onto the part, declare `fit`, derive the cavity and measure() it.

 11. Designing around an existing part (a board, a device, a motor): import its STEP or STL with
     import_reference(project, path) (or create_design(..., references=[path])). It is drawn in the 3D view as a
     blueprint companion. In build(), self.reference("pi5.step") returns it as a build123d shape in the file's own
     coordinates (STEP: its B-rep; STL: a sewn mesh). Use it for clearance cuts, e.g.
         pi = self.reference("pi5.step"); bb = pi.bounding_box()
         body = body - Pos(bb.center().X, bb.center().Y, bb.min.Z) * Box(bb.size.X + 2 * c, bb.size.Y + 2 * c, bb.size.Z, align=A)
     Boolean cuts with a full manufacturer STEP are slow and fragile; cut its bounding box or a few chosen
     features rather than the whole assembly. Its dimensions are "computed" from the file, not "measured".

OPENSCAD (create_design(..., language="openscad"))
  The source is a .scad file. Each top-level number with a Customizer range comment becomes a FORM parameter:
      // Inner width (mm)          <- the comment line above is the label; "(deg)" sets the unit to degrees
      width = 40; // [20:1:120]    <- [min:step:max] or [min:max]; /* [Hidden] */ ends the parameters
  FORM runs `openscad -o part.stl -D width=...` and brings the mesh into the pipeline. It is a mesh design:
  no STEP export, no B-rep validity check, one feature only (no per-feature picking or impact), no FreeCAD
  re-check. Those are reported as "not available for mesh designs", never faked. Mesh volume, closed-mesh,
  wall thickness (ray-cast on the triangles), overhangs, build volume and the slice still run. Prefer Python
  (build123d) when the part needs STEP, feature-level edits or a fit interface.

WORKFLOW
  design_guide -> write source -> create_design (or update_design) -> render -> get_project (checks, slice)
  -> fix -> request_release. Parameter-only changes: preview_change / commit_change, as for any project.
"""

EXAMPLE = '''\
"""Two-part box with a press-fit lid and a cable notch. FORM example design."""
from build123d import Align, Axis, Box, Pos, fillet

from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

A = (Align.CENTER, Align.CENTER, Align.MIN)


class Design(Recipe):
    title = "Box with lid"
    summary = "Rounded box and a press-fit lid printed side by side, with a cable notch."
    solids = 2
    fit = None          # use fit when an outside object (measured param) goes into a cavity
    params = [
        Param("inner_w", "Inner width", 60, 20, 150, 0.5, "mm", "brief", "body", "What it must hold."),
        Param("inner_d", "Inner depth", 40, 20, 150, 0.5, "mm", "brief", "body"),
        Param("inner_h", "Inner height", 30, 5, 120, 0.5, "mm", "brief", "body"),
        Param("wall", "Wall", 2.0, 1.2, 5, 0.1, "mm", "form", "body"),
        Param("corner_r", "Corner radius", 4, 0.5, 12, 0.5, "mm", "form", "body"),
        Param("lid_clearance", "Lid clearance / side", 0.15, 0, 0.6, 0.05, "mm", "interface", "plug"),
        Param("notch_w", "Cable notch width", 8, 0, 20, 0.5, "mm", "form", "notch", "0 = none."),
    ]
    features = [Feature("body", "Body", "structure"), Feature("notch", "Cable notch", "access"),
                Feature("lid", "Lid", "structure"), Feature("plug", "Lid plug", "interface")]

    def constraints(self, v):
        if v["corner_r"] >= min(v["inner_w"], v["inner_d"]) / 2 + v["wall"]:
            return [RecipeError("Corner radius is larger than the box", "body", "Reduce the corner radius.", ["corner_r"])]
        if v["notch_w"] > v["inner_w"] - 6:
            return [RecipeError("Notch is wider than the wall allows", "notch", "Narrow the notch.", ["notch_w"])]
        return []

    def build(self, v):
        W, D, H, t = v["inner_w"] + 2 * v["wall"], v["inner_d"] + 2 * v["wall"], v["inner_h"] + v["wall"], v["wall"]
        outer = Box(W, D, H, align=A)
        outer = fillet(outer.edges().filter_by(Axis.Z), v["corner_r"])
        body = outer - Pos(0, 0, t) * Box(v["inner_w"], v["inner_d"], H, align=A)
        stages = [Stage("body", body)]
        if v["notch_w"] > 0:
            body = body - Pos(0, D / 2, H - 6) * Box(v["notch_w"], 3 * t, 7, align=A)
            stages.append(Stage("notch", body))
        x = W + 8                                            # lid printed beside the box, upside down = flat on the bed
        lid = Pos(x, 0, 0) * fillet(Box(W, D, t, align=A).edges().filter_by(Axis.Z), v["corner_r"])
        s = body + lid
        stages.append(Stage("lid", s))
        c = v["lid_clearance"]
        plug = Pos(x, 0, t) * Box(v["inner_w"] - 2 * c, v["inner_d"] - 2 * c, 4, align=A)
        stages.append(Stage("plug", s + plug))
        return stages

    def derived(self, v):
        return [{"key": "inner_w", "label": "Box opening width", "value": v["inner_w"], "unit": "mm", "feature": "body",
                 "formula": "inner width", "interface": True},
                {"key": "plug_w", "label": "Lid plug width", "value": v["inner_w"] - 2 * v["lid_clearance"], "unit": "mm",
                 "feature": "plug", "formula": "inner width - 2 x clearance", "interface": True}]
'''
