"""What an agent needs to write a FORM design: the contract, the rules, and an example that builds."""

GUIDE = """\
A Form Studio design is one Python file that defines one subclass of Recipe. Form Studio imports it, builds it in the
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
      def assembly(self, v): return Assembly(parts=[Part(...)], joints=[hinge(...)], hardware=[Hardware(...)])  # optional

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
  The source is a .scad file. Each top-level number with a Customizer range comment becomes a Form Studio parameter:
      // Inner width (mm)          <- the comment line above is the label; "(deg)" sets the unit to degrees
      width = 40; // [20:1:120]    <- [min:step:max] or [min:max]; /* [Hidden] */ ends the parameters
  Form Studio runs `openscad -o part.stl -D width=...` and brings the mesh into the pipeline. It is a mesh design:
  no STEP export, no B-rep validity check, one feature only (no per-feature picking or impact), no FreeCAD
  re-check. Those are reported as "not available for mesh designs", never faked. Mesh volume, closed-mesh,
  wall thickness (ray-cast on the triangles), overhangs, build volume and the slice still run. Prefer Python
  (build123d) when the part needs STEP, feature-level edits or a fit interface.

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

ASSEMBLIES (optional, for solids >= 2)
  from form.recipes.base import Access, Assembly, Hardware, Part, hinge, slide
  Part(id, label, solid, move, rotate, explode, note)   solid = index of the printed body, numbered left to right on the
       plate (bounding-box centre X, then Y). Assembled placement = Pos(*move) * Rot(*rotate) applied to the part as printed.
       explode = offset in mm along the separation direction for the exploded view. List parts in assembly order;
       note is the assembly step ("Press the lid on.").
  hinge(part, axis, origin, (lo_deg, hi_deg), samples) / slide(part, axis, (lo_mm, hi_mm), samples): the part moves,
       every other part stays put; 0 is the assembled position. Use about one sample per 5 degrees.
  Hardware(name, size, qty, source, note, after=part_id, access=(Access(at, axis, tool_d, length),))
       bought parts for the BOM; access = a straight tool path ending at the screw head, pointing the way it is driven,
       checked against the parts in place after `after`.
  Form Studio then checks, from the solids: overlap when assembled, the smallest gap, each joint swept at its samples (worst
  overlap and the angle), and tool access. Sampled motion never proves the motion is free between samples.
  The app shows Assembled / Exploded / Print layout, and a release adds BOM.csv and ASSEMBLY.md.

TEXT AND MARKS: form.marks   PATTERNS: form.patterns
  from form import marks, patterns
  marks.emboss_text(shape, "DOCK", on=(x, y, z), normal=(0, -1, 0), height=6, depth=0.6)   # raised; returns the new shape
  marks.deboss_text(shape, "v2", on=a_planar_face, height=5, depth=0.5)                    # sunk
  marks.revision_stamp(shape)        # "r04 a3f1" (revision + hash of its values) sunk 0.4 mm into the underside
       on = a planar Face, a Plane, or a point with normal=. height is the CAP height in mm. Flat faces only.
       The font ships with Form Studio (never a system font). Text reads left to right seen from outside; on walls capitals point up.
       marks.context() gives {"rev", "text", "hash", "nozzle"} while Form Studio builds for a project: "text" is the project's
       label text (form mark <project> --text ..., or the Label text field), so use marks.context().get("text") or "FORM".
       If the geometry depends on it, declare on the class:  mark_params = ("label", "stamp")  (the parameters that switch
       marks on; Form Studio then keys the geometry by label text and revision) and  wall_exempt = ("mark",)  (the feature whose
       faces are lettering, so letter corners are not reported as thin walls).
       Printability: statics() can return checks from marks.checks(marks.analyse(text, height), raised=True): stroke
       width against the nozzle (computed) and cap height against a 4 mm legibility floor (heuristic). Raised text on a
       wall is a small overhang; sunk text prints cleaner. Keep capitals >= 5 mm on a 0.4 mm nozzle.
  patterns.hex_vents(w, d, cell, web, depth)   patterns.perforation_grid(w, d, hole_d, web, depth, stagger)
  patterns.slot_array(slot_w, slot_l, count | w=, web, depth)   patterns.knurl(diameter, height, pitch, depth)
  patterns.grip_ribs(w, d, rib_w, pitch, height)      # kind "add"; the others are cutters
       Each returns a Pattern: .shape (cutter: centred, opening at z = 0, going down, like form.parts), .computed
       {"count", "open_area_ratio", "min_web_mm", ...}, .derived(feature, prefix) rows, .check() (webs >= 2 perimeters),
       .apply(body, on=(x, y, z), normal=(0, 0, 1)). Through-cut: depth = wall + 0.2.
       lid = lid - Pos(0, 0, lid_t) * patterns.hex_vents(60, 36, cell=5, web=1.2, depth=lid_t + 0.2).shape

WORKFLOW
  design_guide -> write source -> create_design (or update_design) -> render -> get_project (checks, slice)
  -> fix -> request_release. Parameter-only changes: preview_change / commit_change, as for any project.
"""

EXAMPLE = '''\
"""Two-part box with a press-fit lid and a cable notch. Form Studio example design."""
from build123d import Align, Axis, Box, Pos, fillet

from form.recipes.base import Assembly, Feature, Param, Part, Recipe, RecipeError, Stage

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

    def assembly(self, v):
        """The lid is printed upside down beside the box: flip it about X, move it over the box, rest it on the walls."""
        W, H, t = v["inner_w"] + 2 * v["wall"], v["inner_h"] + v["wall"], v["wall"]
        return Assembly(parts=[
            Part("box", "Box", 0, note="Set the box down, open side up."),
            Part("lid", "Lid", 1, move=(-(W + 8), 0, H + t), rotate=(180, 0, 0), explode=(0, 0, 30),
                 note="Press the lid on, plug first."),
        ])
'''
