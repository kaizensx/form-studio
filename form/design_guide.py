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

HARDWARE: form.parts  (use it; do not guess screw, nut, insert, bearing or gear dimensions)
  from form import parts
  Each call returns a HardwarePart: .shape (build123d solid), .kind ("cut" or "add"), .dims {name: {value, unit,
  provenance, source}}; part["hole_d"] reads one value; part.derived(feature, prefix) gives derived() rows.
  Cutters: axis on Z, opening at z = 0, going down (-Z). Place with body - Pos(x, y, z_top) * part.shape;
  turn with Rot(180, 0, 0) for a hole opening on the bed face, Rot(90, 0, 0) for a hole along +Y.
    parts.screw_clearance("M3", length, head="socket"|"pan"|"countersunk", fit="close"|"normal", recess=True)
    parts.heat_insert_pocket("M3")      # CNC Kitchen hole; ["boss_min_d"] = smallest boss that keeps the wall
    parts.self_tap_pilot("M3", depth)   parts.nut_trap("M3", "hex"|"square", slot=0)   parts.magnet_pocket(d, h)
    parts.bearing_seat("608")           parts.thread(major_d, pitch, length, external=True)   # pitch >= 1 mm
    parts.spur_gear(module, teeth, thickness, bore)   parts.gear_pair(module, z1, z2, thickness, bore_a, bore_b,
    backlash)  -> .a, .b (b at +X, in mesh), .centre_distance = m (z1 + z2) / 2, .contact_ratio
  M2-M6 screws, nuts, inserts and 6xx bearings work everywhere. Other sizes, threads and gears need the
  [parts] extra (bd_warehouse, py_gearworks); without it they raise a RecipeError that says how to install.
  Example: a boss with an insert, sized from the published minimum wall
    ins = parts.heat_insert_pocket("M3")
    boss = Cylinder(ins["boss_min_d"] / 2 + 0.4, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    boss = boss - Pos(0, 0, 10) * ins.shape        # derived(): rows += ins.derived("boss", "insert.")

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
