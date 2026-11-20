"""What an agent needs to write a FORM design: the contract, the rules, and an example that builds."""

_TEMPLATE = """\
A Form Studio design is one Python file that defines one subclass of Recipe. Form Studio imports it, builds it in the
CAD kernel (build123d on OpenCascade), attributes every face to a feature, and runs the full pipeline:
{pipeline}

CONTRACT
  from build123d import *                      # algebra API only: Box, Cylinder, Pos, Rot, Plane, fillet, ...
  from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

  class Design(Recipe):
      title, summary = "...", "..."
      solids = 1                               # separate bodies in the result (2 for case + lid)
      params = [Param(key, label, default, min, max, step, unit, group, feature, doc, provenance), ...]
                                               # provenance of the default: "assumed" (yours), "specified" (a
                                               # datasheet or standard named in doc), "measured" only from the person
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
{rules_5_6}  7. Dimensions from datasheets or drawings (open them with read_document): put them in params with
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

ASSEMBLIES (for solids >= 2; without one the app can show the parts only as modelled and pulled apart, never
  assembled, and checks nothing about how they meet)
  from form.recipes.base import Access, Assembly, Hardware, Mate, Part, fixed, hinge, slide
  Part(id, label, solid, move, rotate, explode, note, attach="")   solid = index of the printed body, numbered left to
       right on the plate (bounding-box centre X, then Y, then Z), OR an (x, y, z) point inside that body as built: use a
       point whenever parts share an axis (a gearbox's housing, suns and carriers), so you never count solids by hand.
       Assembled placement = Pos(*move) * Rot(*rotate) applied to the
       part as printed. explode = offset in mm for the exploded view, RELATIVE TO ITS PARENT (a child separates with its
       parent and then by its own offset). List parts in assembly order; note is the assembly step ("Press the lid on.").
       attach="arm": the part is rigidly fixed to the arm and moves with it (a bolt in its hole, a cap on a tube).
  hinge(part, axis, origin, (lo_deg, hi_deg), samples, parent="", step=0, id=, label=) / slide(part, axis, (lo, hi), samples,
       parent="") / fixed(part, parent): the joint moves `part` AND everything attached below it, relative to `parent`
       ("" = the world). Axis and origin are in the assembled frame with every joint at 0; a child joint's axis rides
       with its parent's motion. 0 is the assembled position. step > 0 = a ratchet or detent: only multiples of step are
       checked (the positions it can rest at). samples = the coarse sweep; Form Studio adds positions near contact.
  KINEMATIC CHAINS: the parts form a tree. Each part has at most ONE link to a parent: attach=..., or one joint that
       moves it. Example, a wall arm with a tilting cup:
         Part("base", ...),                                   # fixed to the world
         Part("pin", ..., attach="base"),                    # rides with the base
         Part("arm", ...), Part("cup", ...), Part("cup_bolt", ..., attach="cup"),
         joints=[hinge("arm", (1, 0, 0), pivot1, (-60, 60), parent="base", id="arm_tilt", label="Arm tilt"),
                 hinge("cup", (1, 0, 0), pivot2, (-90, 90), parent="arm", id="cup_tilt", label="Cup tilt")]
       Moving Arm tilt swings the arm, the cup and the cup bolt together; Cup tilt swings the cup and its bolt about an
       axis that is wherever the arm put it. Never give a part both attach= and a joint, or two joints; no loops.
       A closed linkage (a four-bar) is a loop: declare its pins as Mate(..., "pin") and put its motion in derived()
       from craft.four_bar (swing, transmission angle), not as joints. Gears are not joints either: model them in mesh
       with their backlash as the gap.
  Mate(a, b, kind, clearance, label): two parts that touch or interlock BY DESIGN, kind = pin | thread | slip | snap |
       press | contact. Declare one for every pin in its hole and every thread in its thread: they are then not booleaned
       (fine threads are slow and always "collide"); their gap is measured once and compared with clearance (designed
       gap per side, mm). Everything not mated is checked for overlap at rest and through every joint's motion.
  Hardware(name, size, qty, source, note, after=part_id, access=(Access(at, axis, tool_d, length),))
       bought parts for the BOM; access = a straight tool path ending at the screw head, pointing the way it is driven,
       checked against the parts in place after `after`.
  Assembly(parts, joints, hardware, mates, clearance_warn=0.1, budget_s=None)   budget_s: seconds for the assembly checks
       (default [assembly].budget_s = 45); when it runs out the checks say which ranges they reached, never "clear".
  Form Studio then checks, from the solids: overlap when assembled, the smallest gap, each mated fit, each joint swept
  through its range with its whole chain (first contact angle, worst overlap; free between samples is proven where the
  clearance exceeds the travel, otherwise reported as sampled only), and tool access. A wrong declaration (unknown part,
  loop, two parents) is refused by create_design/update_design with the reason.
  The app shows Assembled / Exploded / Print layout with a slider per joint, and a release adds BOM.csv and ASSEMBLY.md.

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

  Anything complex (a mechanism, an organic or styled form, a texture, several parts) is staged, and the tools
  enforce it:
    1. design_brief: requirements, key dimensions with their source, constraints, style, and the unknowns (list
       them; never guess a dimension that changes fit, load or safety: ask_user / ask_measurement).
    2. design_guide(topic=...) for the topics the brief needs, and design_examples(query) for a close exemplar.
       Read the exemplar's source: it shows the construction a top designer would use.
    3. plan_design: every feature with HOW it is built (which form.craft helper, which sections), the parts, key
       dimensions, mechanisms with their clearances, textures with their tier, and the risks.
    4. create_design(..., plan=<brief id>): it returns a six-view sheet and a section. LOOK at both.
    5. critique(project): close-ups per feature, metrics, a checklist. Fix, update_design, critique again.
       A briefed design cannot be released until its head revision has a critique pass.
  The helper library for all of this is form.craft (topics surfacing, mechanisms, organic, texture).

WHEN IT FAILS OR LOOKS WRONG
  * A failed build comes back diagnosed: the operation (fillet, loft, fuse, cut, shell...), the feature, the line,
    the likely cause read from the shapes on that line (an invalid operand, parts 0.01 mm apart, sections with 6 and
    14 edges, a fillet wider than the shortest edge) and ranked fixes. Apply the first fix; do not guess.
  * Write risky operations with the robust helpers; each retries the way OCCT needs and notes what it gave up:
      craft.safe_union(a, b, ...)      fuse, fuzzy fuse, repaired shapes; closes a gap under 0.05 mm (noted); refuses
                                       parts that are really apart
      craft.safe_cut(body, tool)       cut, fuzzy cut, repaired shapes, nudged tool; a cut that removes nothing fails
      craft.safe_loft(sections)        smooth, re-seamed and resampled sections (craft.reseam), ruled, pairwise
      craft.safe_fillet / craft.safe_chamfer   smaller sizes, then edge by edge
      craft.safe_shell(solid, t, openings)     arc, intersection offset, then thinner walls
      craft.repair(shape), craft.inspect(shape)   ShapeFix + face merge; validity, faults, shortest edge
  * Two or three plausible constructions for a risky step: write them all and call build_candidates once. They build
    in parallel (one kernel worker each), are scored (builds, brief targets, quality, robustness, editability over
    each parameter's range) and the best becomes the design; failures carry their diagnosis.
  * design_examples(technique="...") returns just the block of an exemplar that does one thing well.
  * "The result is N solid(s); this design declares M. Solids per stage: ..." Read the per-stage counts: the step
    where the count jumps is the one that split a body (a slit that runs out of material) or fused two parts (they
    touch: leave 0.3 mm). "The X step left no solid": a boolean failed there; overlap by 0.2 mm, keep it off a loft
    seam, or simplify the shape.
  * get_project's craft_fallbacks lists every helper that could not do what you asked (a fillet built smaller or edge
    by edge, a loft in runs) and every stage that is not a valid solid. Fix them or say so; never hide them.
  * Check a risky boolean yourself while you write: (a - b).is_valid. A smooth loft through sections that are close
    together AND shifted sideways can fold over itself; its booleans then come back invalid and larger, not smaller.
  * Heavy designs (a helmet, 15 gears) take a minute or more: create_design/update_design say when exports and checks
    are still running; run_pipeline(project) finishes them and reuses what is done.
  * Through form tool (the CLI), pictures come back as file paths under "images": open them, they are the sheet,
    the section and the close-ups.
"""

# rules 5-6 depend on what the design is for (form/purpose.py): bed orientation, overhangs and nozzle walls only for a print
_PRINT = {"pipeline": "renders, checks, fit model, slice, revisions, optimizer, animation, release.",
          "rules_5_6": """\
  5. Print orientation: model every part as it sits on the bed (flat face on z = 0). Put multiple parts
     side by side with at least 5 mm between them and set solids = N.
  6. Prefer chamfers on bottom edges and 45° ceilings over flat overhangs. Walls >= 1.2 mm (3 lines).
"""}
_MODEL = {"pipeline": "renders, checks, exports (STEP, STL, 3MF, OBJ, GLB), revisions, optimizer, animation, release.",
          "rules_5_6": """\
  5. Model each part in the coordinates it is used in (base on z = 0 where it has one). Put multiple parts side
     by side with a gap and set solids = N, or declare an assembly() so they are shown in place.
  6. Design for how it will be made when the person says (CNC, moulding, casting, sheet metal: the checks name the
     smallest feature that process holds). Otherwise favour proportion and finish: real fillets and chamfers,
     consistent wall thickness, no knife edges.
"""}


def guide(purpose: str | None = "model") -> str:
    """The guide for a design made for `purpose`: "print" adds bed orientation, overhang and nozzle-wall rules."""
    v = _PRINT if purpose == "print" else _MODEL
    return _TEMPLATE.replace("{pipeline}", v["pipeline"]).replace("{rules_5_6}", v["rules_5_6"])


GUIDE = guide("model")

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


# ---- topics: design_guide(topic=...) ---------------------------------------------------------------------------------

SURFACING = """\
SURFACING (form.craft.surfaces)  from form import craft
A designed object is made of sections and transitions, not of boxes. Decide the sections first, then skin them.
  craft.superellipse(a, b, n)                 points; n = 2 ellipse, 2.5-4 product "soft square", >= 6 rounded rectangle
  craft.superellipse_face(a, b, n, z=, center=, squash_front=)    a section Face at height z
  craft.spline_profile(points, plane=Plane.XZ, closed=True)       smooth Face (or Wire) through points
  craft.loft_sections([face, face, ..., Vertex(tip)])             smooth B-spline skin; ruled loft as fallback (noted)
  craft.sweep_spline(profile_face, path_points)                   profile placed normal to the path start
  craft.revolve_profile([(r, z), ...], spline=True)               vases, knobs, lamp bodies, wheels
  craft.shell(solid, t, openings=craft.faces_at(solid, "top"))    hollow it; keeps the outside
  craft.safe_fillet(solid, edges, r)          tries r, 75 %, 50 %, 25 % on all edges, then edge by edge, then leaves
                                              them (all noted); never crashes
  craft.variable_fillet(solid, edges, r0, r1) a blend that grows along the edge
  craft.thicken(face, t)                      a solid from a surface
  craft.notes()                               what fell back; get_project shows them as craft_fallbacks
Rules:
  * 5-12 sections for a body; the same point count and start angle (seam) on every section, or the loft twists.
  * Make sections follow a law (an ellipse in elevation, a power curve) rather than hand-picked numbers: the
    surface then flows. craft.dome_sections() does this.
  * A loft has a seam line where its sections start (seam=0: +X, the nose). Fillets and booleans fail first where
    they cross it; keep pockets, vents and spoilers off it, or move it (section dicts take seam=180 for the back).
  * Fillet BEFORE shelling where you can (a shell follows the rounds), and big radii first, small ones last.
  * A pocket cut into a curved dome (a hex for a bolt head) leaves an edge OCCT will not round: cut a flat land
    (a shallow cylinder) first, then the pocket, then fillet the land's circle and the pocket mouth.
  * Profiles: spline_profile / polygon_profile faces always face the plane's normal, so extrude(face, d) goes along
    it whichever way the points run; extrude(face, d, both=True) for a cutter through a whole body.
  * Tangent and coincident faces break booleans: overlap cutters by 0.2 mm and avoid exactly touching surfaces.
"""

MECHANISMS = """\
MECHANISMS (form.craft.mechanisms, form.craft.fits, form.parts)
Each returns a Mech: .shapes {name: solid}, .dims (value, unit, provenance, source), .checks, .axis/.origin for joints.
  mech["name"] is a dimension's value or, for a name in .shapes, that solid (planetary()["ring"], hinge["leaf_a"]).
  craft.pin_hinge(length, outer_d, pin_d, knuckles, clearance)    print-in-place; leaf_a carries the pin. Lying flat,
       axis along X at z = outer_d / 2. Standing on a wall: place = Pos(0, y_axis, z_axis) * Rot(90, 0, 0) *
       Pos(0, 0, -outer_d / 2) puts leaf_a below the axis and leaf_b above it, both on the +Y side. Fuse each leaf to
       its body and cut place * hinge.info["relief_a"] from the body leaf_b joins (relief_b from the other), or the
       knuckles fuse the two bodies. Keep the axis just outside the walls and bridge leaves to walls with webs.
  craft.living_hinge(width, gap, web_t, material="PP")           warns for PLA/PETG
  craft.cantilever_snap(length, thickness, width, undercut)       strain = 1.5 t y / L^2 (computed) vs allowed. Beam
       along +Z, lip +X. Hanging from a lid with the lip pointing -Y: Pos(...) * Rot(0, 0, -90) * Rot(180, 0, 0).
  craft.annular_snap(d, undercut, height, wall)                   male bead + groove cutter, hoop strain y / d
  craft.bayonet(d, height, lugs, twist)   male and female_cutter share ONE frame: same placement for both, cutter open
       at its top; turn the male by twist - 2 deg about Z to show it locked; attach the male's top end (z = height).
  craft.dovetail(length, width, height, angle)    craft.detent(ball_d, depth)
  craft.ratchet(teeth, od)    craft.cam(base_r, lift, rise, dwell_top, fall, follower_r)  (pressure angle checked)
  craft.four_bar(ground, crank, coupler, rocker)   Grashof class, swing, transmission angle; .shapes = printable links
  craft.four_bar_pose(ground, crank, coupler, rocker, crank_deg)  A, B, C, D where the loop sits at that crank angle;
  craft.link_between(p, q, width, thickness, hole_d, z)           a link placed between two pivots (pins along Z)
  craft.gear_train(module, teeth=(14, 28, 14))      craft.planetary(module, sun, planet, planets, ring_height=)
       ring_height makes one ring for several stacked stages (a 3-stage 64:1 box: 12/12/36 three times in one ring).
       (via form.parts)
  craft.iso_fit("H7/g6", d)   craft.bearing_fit("608", "shaft")   ISO 286 limits; FDM holds ~0.15 mm, say so
Rules:
  * Every moving pair has a clearance per side you can name (FDM: 0.2-0.35 mm sliding, 0.35-0.5 print-in-place).
  * Declare the motion: assembly() with hinge()/slide() joints and Mate() for pins and threads, so Form Studio sweeps it.
  * Put strain, ratio, centre distance and clearance in derived() with their source (Mech.derived(feature)).
  * Snap hooks bend along the layers: lay the beam flat in XY. Living hinges need PP, PE, nylon or TPU.
"""

ORGANIC = """\
ORGANIC FORMS (form.craft.organic)
  craft.section_body([dict(z, a, b, n, cx, cy, squash), ...], tip=(x, y, z))   loft of superellipse sections
  craft.dome_sections(length, width, height, crown_back=, squash_front=)       sections of a smooth dome
  craft.section_shell(sections, wall, tip=, open_top=)                         hollow by inset sections (never fails
                                                                               where an offset of a crown point does)
  craft.inset_body(sections, wall, tip=)                                       the inner body section_shell removes
  craft.inflate(sections, amount, tip)                                         near-offset sections, for pads/ridges
  craft.helmet_shell(length, width, height, wall, skirt)                       outer form + hollow shell
  craft.helmet_sections(length, width, height, skirt)                          its sections, for visors, pads, liners
  craft.grip(length, d_max, d_min, flat, finger_grooves)                       revolved spline, oval section
  craft.handle(span, rise, section_w, section_h)                               swept D-handle with feet
 Silhouette-driven forms (draw three views, get sections):
  craft.profile_sections(front, back, half_width, z_eq=, crown=(x, z), n=, squash=, cy=)   sections from guide
      curves: front/back = the side silhouette as (z, x) knots, half_width = the front silhouette as (z, y) knots,
      a superellipse dome above z_eq to the crown; n, squash, cy constants or (z, v) knots. C2 splines throughout.
  craft.checked_body(secs, tip, label=)    section_body + check_sections (order, seams, steep steps) + loft_report
      (the skin's normals: a fold is a crease inside a face that should be smooth); leaves a note when it folds
  craft.loft_report(shape)                 {faces_checked, folds, worst_deg, where}: run it on any lofted solid
  craft.two_view_cutter(side, front, x_range)   a cutter drawn in two views (eye ports, visor windows, wrapped vents)
  craft.grow_outline(points, mm)           an outline moved outward (rims and gaskets round an opening)
  craft.surface_band(secs, tip, amount, region, depth)   the surface grown by amount, clipped to region, rooted
      depth inside the wall: pads, scoops, trim, spoilers, raised graphic panels; the region's walls are crisp lines
  craft.slot_grille(center, normal, count, length, width, pitch, taper=)   B-rep vent grille cutter
  craft.cut(body, tool) / craft.fuse(body, part, max_solids, min_solids)   booleans with fuzzy fallbacks; they
      refuse a result that lost the body or fused a part that must stay separate (a visor)
 Product families from named proportions (each returns the sections plus the outlines of its openings):
  craft.head_form("J")                      EN 960 / ECE 22.05 headform (A 500, E 540, J 570, M 600, O 620 mm
                                            circumference) scaled from the ANSUR II mean head: length, breadth, eye, chin
  craft.helmet_fullface(size, chin=, tail=) full-face helmet: head + comfort 10 + EPS 34 + shell 3.5 mm a side;
                                            keys sections, tip, edge, port_side/port_front, visor_side, pivot
  craft.helmet_open(size, kind="cycling"|"open")   half-shell and open-face helmets
  craft.mouse_form(length=, width=, height=, hand=, hump=, tilt=, flare=)   palm-grip mouse from the hand (ANSUR II:
                                            0.65 x hand length long); hump behind centre, tilt toward the thumb
  craft.grip_sections(length, hand_breadth) power grip (31-38 mm best for force), palm swell, flat across
  craft.bottle_profile(volume_ml)           revolve profile with a PCO 1881 neck, height solved from the volume
Method: start from the object's real measurements (a head is about 200 x 160 mm, a helmet adds 25-35 mm a side; a
power grip is 30-38 mm across), draw the side silhouette and the top silhouette as curves, and derive the sections
from them. Asymmetry front to back is what makes organic things read as designed (a helmet's crown sits behind
centre; a grip swells at the palm, not the middle). Cut openings with smooth cutters (lofted or swept), not boxes,
and round their edges.
Shape the OUTSIDE first, then hollow: a scoop or a flat cut into a shell leaves a fillet the wall cannot take.
    outer = craft.section_body(secs, tip); inner = craft.inset_body(secs, wall, tip)
    outer = craft.safe_fillet(outer - scoop, scoop_edges, 4)      # round the outside
    shell = outer - (inner - grown_scoop)                         # the inside follows, the wall stays even
Layers that follow the surface (a visor 1.2 mm off a helmet, a pad, a spoiler) are inflate() bodies subtracted from
each other and intersected with a window: skin = body(inflate(secs, g + 3)) - body(inflate(secs, g)). Shape the
window as a side profile extruded across (spline_profile on Plane.XZ, extrude(..., both=True)), not a box: the
outline is what reads. A visor reaches back to its pivots; a band that stops short leaves the pivot tabs floating.
Product shapes read from their silhouettes: a helmet's chin bar juts forward and its lower edge sweeps up behind the
jaw to the neck; a mouse's hump sits behind centre and its thumb side is fuller. Shift and pinch sections (cx, b) to
get there, a little at a time: large sideways shifts between close sections fold the loft.
What makes a styled product read as the real thing is its BREAK-UP, not its dome: a smoked visor as its own body on
pivots, rubber trim on the edges, intakes with grilles, a spoiler, split lines between buttons, a wheel. Every one is
a surface_band or a two_view_cutter that follows the main form. A smooth body with one cut reads as a pebble.
Face the product +X with Z up: critique compares its side, front and top silhouettes with the product class
(helmet_fullface, helmet_open, mouse, bottle), and render_photo's views and appearance() zones assume it.
 Sculpted forms (masks, cowls, character props) as subdivision cages, exact NURBS (from form.craft import subd):
  C = subd.dome_cage(L, W, H, n=14, rim=fn(theta), tuck=0.28)   a head-like skin cage (x forward, z up)
  C = subd.apply_handles(C, HANDLES, v)     subd.Handle(name, label, centre, radius, direction | "normal", ...) moves
      cage points smoothly; h.param(feature) makes each handle a Param ("stronger brow" is a number)
  shell = subd.sculpted_shell(C, wall)      skin + inside + ruled rim: three faces, C2 inside, fast booleans after
  subd.Cage(V, quads, levels=1).solid()     a closed Catmull-Clark cage as bicubic patches (G1 at odd vertices)
 Exact CAD on a sculpted skin (hybrid; see the character_mask exemplar):
  craft.organic.magnet_boss(body, at, axis, magnet_d, magnet_t)   a boss from the inside with the pocket in it
  craft.organic.split_with_magnets(body, x, organic.split_spots(body, x, heights, d), d, t)   front/back halves
  openings from a constrained sketch: from form.sketch2d import Sketch (lines, arcs, constraints, named dimensions
  that are Params; Sketch.face(v, plane=Plane.YZ)), never hand-typed coordinates for a shape that must keep intent.
 A sculpted MESH (a download, a scan): form.meshbody.organic_solid(triangles) gives a closed NURBS solid within a
 stated tolerance with its cage, or MeshBody keeps the mesh and cuts exact features into it. Say which tier it is.
"""

TEXTURE = """\
TEXTURE, two honest tiers
  B-rep (the CAD solid carries it; STEP, STL, checks and slices all include it). Capped at about 2000 elements:
    craft.knurl(diameter, height, pitch, depth, kind="diamond"|"straight")      exact faceted knurl, chamfered ends
    craft.spiral_ribbed_body([(r, z), ...], ribs, rib_depth, twist, fade=(0.1, 0.2))   one skin with spiral ribs;
        fade eases the ribs into a plain foot and collar; past 80 deg of twist it lofts in runs (noted)
    craft.wrapped_ribs(radius, height, count, rib_w, rib_h, twist)             ribs to fuse onto a cylinder
    craft.emboss_cells(w, d, cell, height, kind="hex"|"diamond"|"dots"|"pyramids", base=0)   raised tiles for a flat face
    form.patterns: hex_vents, perforation_grid, slot_array, knurl, grip_ribs (cutters / adds with computed webs)
  Mesh texture (fine surface: leather grain, stone, carbon-like cells, sand-cast): declare it on the design; the STL,
  OBJ, GLB and the renders carry it, the STEP keeps the smooth body. Say so: "mesh texture; STEP carries the smooth body".
    from form.craft import MeshTexture
    def mesh_texture(self, v):
        return [MeshTexture("cells", amplitude=0.4, scale=5, features=["shell"])]
    kinds: noise, cells, grain, hex, weave (carbon-like twill), knurl, ribs, heightmap (image=, projection=planar|
    cylindrical|spherical). amplitude mm (negative presses in), scale mm, features = which feature ids,
    facing="out" = only the outside of a shell, edge_falloff mm at borders and creases.
    region=((x0, y0, z0), (x1, y1, z1)) keeps it to a box (the flanks of a mouse, a band on a lofted face that is one
    feature), exclude=(box, ...) keeps areas smooth (a logo field, a seal face).
    Seeing it: the six-view sheet draws a 270 mm helmet at about 0.5 mm a pixel, so a 0.25 mm weave is invisible
    there; it shows in render_photo close-ups and in the app. Do not deepen it past what the material would have
    to make it show in the sheet.
Choose: if a person sees it from a metre away or it does work (grip, alignment), make it B-rep. If it is felt or seen
up close, make it a mesh texture. Printed texture needs >= 2 nozzle widths in plan and >= 0.3 mm depth to survive.
"""

AESTHETICS = """\
AESTHETICS: what separates a designed object from a crude one
  * One idea for the whole form (a soft square, a tapered cylinder, a dome), repeated in every detail.
  * Proportion: relate the main masses (1:1.414, 1:1.618, 1:2); avoid ratios that are almost but not quite equal.
  * Hierarchy of radii: big radii on the big form, smaller on secondary edges, the smallest on details. Never leave an
    edge a hand or eye meets sharp: 0.5-1 mm on printed details, 2-6 mm on hand-held forms.
  * Continuity: surfaces flow (smooth lofts), with crisp deliberate breaks where you want a line. A face that meets
    another at a random 10 deg reads as a mistake.
  * Openings, vents and seams follow the form: align them to the body's lines, space them on a rhythm, inset them.
  * Detail density: a large plain surface needs one considered detail (a parting line, a texture field, an inset).
  * Check every view (sheet), the section and the close-ups (critique). If any view looks like a primitive, it is not done.
  * Silhouette first: a product is recognised by its outline in three views before any detail. Draw them as guide
    curves (craft.profile_sections) and compare: critique scores the outline against the product class, checks the
    proportions against real products (with sources) and the class signature (an eye port, a palm hump).
  * Tension: a surface that is almost flat but not quite (a slight crown on a side, a taper toward the nose) reads as
    designed; a surface that bulges evenly everywhere reads as inflated. Put the fullness where the use is (the palm,
    the crown) and let the rest run taut. Express it as parameters (hump, tilt, chin, crown_back).
  * Character lines: one or two crisp lines that run the length of the form (a raised panel edge, a split line, the
    edge of a trim band), aligned with the flow. Make them with surface_band regions, not by chance where booleans meet.
  * Materials: real products are two or three materials. Declare appearance() zones (a smoked visor, rubber trim, a
    carbon shell, matte vents) and render_photo from at least three angles (view="three_quarter", "right", "left",
    "three_quarter_back") before you call it done; one colour over everything renders as a blob.
  * Be your own harshest critic: put a photo of the real thing in your mind next to yours. Answer critique's "reads
    as" question honestly; name what gives it away as a model and fix that first.
"""

DFM = """\
DESIGN FOR 3D PRINTING (purpose: print)
  * Lay the part as it prints: the biggest flat face on z = 0. Overhangs <= 45 deg, or chamfer instead of fillet on
    bottom edges; bridges <= 20 mm; teardrop or diamond holes when horizontal and > 8 mm.
  * Walls >= 3 perimeters (1.2 mm on a 0.4 nozzle); ribs 50-70 % of the wall they stiffen.
  * Clearances per side: press 0.05-0.1, sliding 0.2-0.3, print-in-place 0.35-0.5 mm. Calibrate with a coupon.
  * Layers are the weak direction: snap beams, hooks and pins in XY; screw bosses with heat-set inserts (form.parts).
  * Texture survives only above about 2 nozzle widths in plan and 0.3 mm in depth.
  * Large shells (a helmet) do not fit most beds in one piece: split them with alignment keys or say what bed it needs.
"""

REFERENCE_PARTS = """\
REFERENCE PARTS: meshes (STL, OBJ, 3MF) the person gives you to understand, make editable, or rebuild
When someone brings meshes and wants them editable, understood or changed, rebuild them as clean CAD: named features
and Params, like a part designed from scratch. The meshes stay blueprint references, never the design.

NEVER
  * never embed the raw meshes as the design (self.reference("part.stl") as the body): nothing is editable, every
    triangle is a face, and the viewport is a wireframe of facets. A reference mesh is only for looking and comparing.
  * never guess what a mechanism does from its outline: measure it (analyze_assembly) and read the sections.

STAGES
  1. Import every mesh into the project: import_reference(project, path), one per part, keeping their coordinates.
     "Make editable" (reconstruct) is the deterministic route; when it does not reach a verified Layer 2 recipe, do
     this workflow instead.
  2. analyze_reference(project, reference) for each mesh: principal axes, section pictures with dimensions (look at
     them), vector outlines, and features with sizes: holes, bosses, openings (pockets, slots, cutouts), walls, ribs,
     rails and grooves, plates, steps (levels), ramps with angles, draft, fillets and chamfers with radii and widths,
     detail areas (text, embossing, knurls), symmetry and wall thicknesses. Ask for sections where you need them
     (levels={"z": [3.2, 6.5]}).
  3. Several parts: analyze_assembly(project, references=[fixed part first, ...]) gives mating surfaces and clearances,
     each part's travel (slide axes with their range, hinge axes with their range, bumps on the way: detents, snaps or
     flexing arms) and couplings (a slide meshing with a part that turns: rack and gear or cam, with the ratio; a slide
     on a leaning face: a ramp, with the lift per mm). State the mechanism in one sentence before modelling it.
  4. Plan: the features in build order, each named after what it is ("base_plate", "side_rail", "card_slot",
     "pivot_pin", "rack", "cascade_steps"), with the dimension that drives it as a Param (card slot width, wall
     thickness, rail clearance, ramp angle, step height, pin diameter). Read sizes off the analysis: round to the
     designer's evident grid (0.1 mm, 0.5 mm, whole degrees) when the mesh agrees within the tolerance.
  5. Write clean build123d (algebra API, design_guide core): sketch the main profile from the section outlines and
     extrude it, then cut pockets and slots, add rails and ribs, then holes, then chamfers and fillets last. One Stage
     per feature. Model in the meshes' coordinates so the comparison lines up. For several parts: one Part per mesh
     (solid=(x, y, z) a point inside it, move=(0, 0, 0) when modelled in place) and the joints analyze_assembly found
     (slide(part, axis, (lo, hi)), hinge(part, axis, origin, (lo, hi))), Mate() for pins in holes; gears and racks are
     not joints: model their teeth in mesh and put the ratio in derived().
  6. compare_to_reference(project, reference, part=...) after every build: two-sided Hausdorff, the worst regions
     with where they are and whether the design has too much or too little material there, and per-feature
     differences (the design's diameters and radii next to the mesh's). Fix the worst first.
  7. Refine until every part is within the tolerance. The default for a remodel is 0.1 mm (two-sided Hausdorff);
     say which tolerance you used. Where you choose not to follow the mesh (scan noise, a facet artefact, text you
     left out), say where and by how much; never hide a difference.

TIPS
  * Sections across the up axis give the plan shapes (outlines and openings); sections along it give the steps,
    rails and chamfers in profile.
  * A narrow strip between two planes is usually a chamfer or a fillet; equal strips around a rim are one edge
    treatment with one Param.
  * Repeated openings with a pitch are one feature with a count and a pitch Param.
  * A "bump" in the travel of a slide is often a flexing detent arm: model the arm and its bump as features.
  * measure(project, at=[x, y, z]) and measure(project, from_point=[...], to_point=[...]) check single values on
    your design.
"""

TOPICS = {"core": None, "surfacing": SURFACING, "mechanisms": MECHANISMS, "organic": ORGANIC, "texture": TEXTURE,
          "aesthetics": AESTHETICS, "dfm": DFM, "reference_parts": REFERENCE_PARTS}


def topic(name: str = "core", purpose: str | None = None) -> dict:
    """The guide for one topic. core is the contract, the rules and an example that builds; dfm applies only to
    designs for printing."""
    name = (name or "core").strip().lower()
    if name not in TOPICS:
        raise KeyError(name)
    if name == "core":
        return {"topic": "core", "guide": guide(purpose), "purpose": purpose, "example_source": EXAMPLE, "topics": list(TOPICS)}
    if name == "dfm" and purpose == "model":
        return {"topic": "dfm", "guide": "Not applicable: this design is a 3D model, not for printing. Design for its "
                "process (CNC, moulding, rendering) instead; print rules would only constrain it.", "topics": list(TOPICS)}
    return {"topic": name, "guide": TOPICS[name], "topics": list(TOPICS)}
